// Package tenant discovers and manages documentation source metadata from
// the mcp-data directory. It provides a registry for tenant lookup and
// fuzzy matching for tenant discovery by topic.
package tenant

import (
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// Freshness describes the strength and timestamp of persisted source evidence.
type Freshness struct {
	State     string `json:"state"`
	UpdatedAt string `json:"updated_at,omitempty"`
	Evidence  string `json:"evidence,omitempty"`
}

// Provenance identifies the indexed corpus without exposing local paths.
type Provenance struct {
	SourceType           string    `json:"source_type"`
	CanonicalURLPrefixes []string  `json:"canonical_url_prefixes,omitempty"`
	IndexID              string    `json:"index_id,omitempty"`
	IndexCreatedAt       string    `json:"index_created_at,omitempty"`
	DocumentCount        int       `json:"document_count"`
	Freshness            Freshness `json:"freshness"`
	SourceRevision       string    `json:"source_revision,omitempty"`
	SourceRevisionType   string    `json:"source_revision_type,omitempty"`
}

// Tenant holds metadata about a documentation source discovered from mcp-data/.
type Tenant struct {
	Codename    string     `json:"codename"`
	DisplayName string     `json:"display_name"`
	Description string     `json:"description"`
	DocCount    int        `json:"doc_count"`
	DataDir     string     `json:"-"` // Absolute path to tenant directory
	SegmentDB   string     `json:"-"` // Path to latest segment .db
	URLPrefixes []string   `json:"url_prefixes,omitempty"`
	SourceType  string     `json:"source_type,omitempty"` // filesystem, online, git
	Provenance  Provenance `json:"provenance"`
}

// deploymentTenant is the JSON shape of a tenant in deployment.json.
// Fields that can be string or []string in the config use interface{}.
type deploymentTenant struct {
	Codename             string `json:"codename"`
	DocsName             string `json:"docs_name"`
	Description          string `json:"description"`
	SourceType           string `json:"source_type"`
	DocsEntryURL         any    `json:"docs_entry_url"` // string or []string
	DocsSitemapURL       any    `json:"docs_sitemap_url"`
	URLWhitelistPrefixes string `json:"url_whitelist_prefixes"`
}

// Registry discovers and holds all tenants from a data directory.
type Registry struct {
	dataDir string
	tenants map[string]*Tenant
	ordered []*Tenant // sorted by codename
}

// NewRegistry scans dataDir for tenant directories and optionally enriches
// tenant metadata from a deployment config file (deployment.json).
// If configPath is empty, only mcp-data directory scanning is used.
func NewRegistry(dataDir string, configPaths ...string) (*Registry, error) {
	r := &Registry{
		dataDir: dataDir,
		tenants: make(map[string]*Tenant),
	}
	if err := r.scan(); err != nil {
		return nil, err
	}
	for _, cp := range configPaths {
		if cp != "" {
			r.loadDeploymentConfig(cp)
		}
	}
	return r, nil
}

func (r *Registry) rebuildOrdered() {
	r.ordered = make([]*Tenant, 0, len(r.tenants))
	for _, t := range r.tenants {
		r.ordered = append(r.ordered, t)
	}
	sort.Slice(r.ordered, func(i, j int) bool {
		return r.ordered[i].Codename < r.ordered[j].Codename
	})
}

func (r *Registry) scan() error {
	entries, err := os.ReadDir(r.dataDir)
	if err != nil {
		return fmt.Errorf("scan data dir %s: %w", r.dataDir, err)
	}

	for _, e := range entries {
		if !e.IsDir() || strings.HasPrefix(e.Name(), ".") {
			continue
		}
		codename := e.Name()
		tenantDir := filepath.Join(r.dataDir, codename)
		segDir := filepath.Join(tenantDir, "__search_segments")

		// Must have a search segments directory
		if _, err := os.Stat(segDir); os.IsNotExist(err) {
			continue
		}

		t := &Tenant{
			Codename:    codename,
			DisplayName: formatDisplayName(codename),
			DataDir:     tenantDir,
			Provenance:  unknownProvenance(),
		}

		// Read manifest for doc count and segment ID
		t.loadManifest(segDir)
		t.loadLegacyFreshness(tenantDir)

		// Try to discover URL prefixes and description from meta.json files
		t.loadMetadata(tenantDir)
		t.refreshProvenance()

		r.tenants[codename] = t
	}

	// Build sorted list
	r.rebuildOrdered()

	return nil
}

func (t *Tenant) loadManifest(segDir string) {
	data, err := os.ReadFile(filepath.Join(segDir, "manifest.json"))
	if err != nil {
		return
	}
	var manifest struct {
		LatestSegmentID string `json:"latest_segment_id"`
		CreatedAt       string `json:"created_at"`
		DocCount        int    `json:"doc_count"`
		Provenance      struct {
			SourceType         string `json:"source_type"`
			FreshnessState     string `json:"source_freshness_state"`
			SourceUpdatedAt    string `json:"source_updated_at"`
			SourceEvidence     string `json:"source_evidence"`
			SourceRevision     string `json:"source_revision"`
			SourceRevisionType string `json:"source_revision_type"`
		} `json:"provenance"`
	}
	if json.Unmarshal(data, &manifest) == nil {
		t.DocCount = manifest.DocCount
		t.Provenance.DocumentCount = manifest.DocCount
		t.Provenance.IndexID = strings.TrimSpace(manifest.LatestSegmentID)
		t.Provenance.IndexCreatedAt = normalizedUTC(manifest.CreatedAt)
		if sourceType := strings.TrimSpace(manifest.Provenance.SourceType); sourceType != "" {
			t.Provenance.SourceType = sourceType
		}
		state := normalizedFreshnessState(manifest.Provenance.FreshnessState)
		updatedAt := normalizedUTC(manifest.Provenance.SourceUpdatedAt)
		if state != "unknown" && updatedAt != "" {
			t.Provenance.Freshness = Freshness{
				State:     state,
				UpdatedAt: updatedAt,
				Evidence:  strings.TrimSpace(manifest.Provenance.SourceEvidence),
			}
			t.Provenance.SourceRevision = strings.TrimSpace(manifest.Provenance.SourceRevision)
			t.Provenance.SourceRevisionType = strings.TrimSpace(manifest.Provenance.SourceRevisionType)
		}
		if manifest.LatestSegmentID != "" {
			dbPath := filepath.Join(segDir, manifest.LatestSegmentID+".db")
			if _, err := os.Stat(dbPath); err == nil {
				t.SegmentDB = dbPath
			}
		}
	}
}

func (t *Tenant) loadLegacyFreshness(tenantDir string) {
	if t.Provenance.Freshness.State != "unknown" {
		return
	}
	paths := []struct {
		path  string
		field string
	}{
		{path: filepath.Join(tenantDir, "__scheduler_meta", "metadata_summary.json"), field: "last_success_at"},
		{path: filepath.Join(tenantDir, "__scheduler_meta", "meta_last_sync.json"), field: "last_sync_at"},
	}
	for _, candidate := range paths {
		data, err := os.ReadFile(candidate.path)
		if err != nil {
			continue
		}
		var payload map[string]any
		if json.Unmarshal(data, &payload) != nil {
			continue
		}
		value, _ := payload[candidate.field].(string)
		if updatedAt := normalizedUTC(value); updatedAt != "" {
			t.Provenance.Freshness = Freshness{
				State:     "partial",
				UpdatedAt: updatedAt,
				Evidence:  "scheduler_summary_unbound",
			}
			return
		}
	}
}

func (t *Tenant) loadMetadata(tenantDir string) {
	metaDir := filepath.Join(tenantDir, "__docs_metadata")
	entries, err := os.ReadDir(metaDir)
	if err != nil {
		return
	}

	// URL prefixes from subdirectory names (hostnames)
	for _, e := range entries {
		if e.IsDir() && !strings.HasPrefix(e.Name(), ".") {
			t.URLPrefixes = append(t.URLPrefixes, "https://"+e.Name())
		}
	}

	// Try to read first meta.json for description hints
	if len(t.URLPrefixes) > 0 {
		t.Description = fmt.Sprintf("Documentation from %s", strings.Join(t.URLPrefixes, ", "))
	} else {
		t.Description = fmt.Sprintf("%s documentation", t.DisplayName)
	}
}

// Get returns a tenant by codename.
func (r *Registry) Get(codename string) *Tenant {
	return r.tenants[codename]
}

// List returns all tenants sorted by codename.
func (r *Registry) List() []*Tenant {
	return r.ordered
}

// Codenames returns sorted codename list.
func (r *Registry) Codenames() []string {
	names := make([]string, len(r.ordered))
	for i, t := range r.ordered {
		names[i] = t.Codename
	}
	return names
}

// Count returns the number of tenants.
func (r *Registry) Count() int {
	return len(r.tenants)
}

// loadDeploymentConfig reads deployment.json and enriches tenant metadata.
// It overlays docs_name (better display names) and source URLs.
func (r *Registry) loadDeploymentConfig(configPath string) {
	data, err := os.ReadFile(configPath)
	if err != nil {
		return
	}
	var config struct {
		Tenants []deploymentTenant `json:"tenants"`
	}
	// Ignore unmarshal errors — partial parsing is fine since deployment.json
	// has polymorphic fields (string or []string) that may cause type errors
	// but still populate most tenants correctly.
	json.Unmarshal(data, &config)

	configured := make(map[string]deploymentTenant, len(config.Tenants))
	for _, dt := range config.Tenants {
		if dt.Codename != "" {
			configured[dt.Codename] = dt
		}
	}
	if len(configured) == 0 {
		return
	}

	for codename := range r.tenants {
		if _, ok := configured[codename]; !ok {
			delete(r.tenants, codename)
		}
	}

	for _, dt := range config.Tenants {
		t := r.tenants[dt.Codename]
		if t == nil {
			t = &Tenant{
				Codename:    dt.Codename,
				DisplayName: formatDisplayName(dt.Codename),
				DataDir:     filepath.Join(r.dataDir, dt.Codename),
				Provenance:  unknownProvenance(),
			}
			r.tenants[dt.Codename] = t
		}
		if dt.DocsName != "" {
			t.DisplayName = dt.DocsName
		}
		if dt.SourceType != "" {
			t.SourceType = dt.SourceType
		}

		configPrefixes := splitCSV(dt.URLWhitelistPrefixes)
		if len(configPrefixes) == 0 {
			configPrefixes = append(configPrefixes, normalizeURLValues(dt.DocsEntryURL)...)
		}
		if len(configPrefixes) == 0 {
			configPrefixes = append(configPrefixes, normalizeURLValues(dt.DocsSitemapURL)...)
		}
		configPrefixes = publicURLPrefixes(configPrefixes)
		if len(configPrefixes) > 0 {
			t.URLPrefixes = configPrefixes
		}

		// Rebuild description with better display name.
		if strings.TrimSpace(dt.Description) != "" {
			t.Description = strings.TrimSpace(dt.Description)
		} else if len(t.URLPrefixes) > 0 {
			t.Description = fmt.Sprintf("Documentation from %s", strings.Join(t.URLPrefixes, ", "))
		} else {
			t.Description = fmt.Sprintf("%s documentation", t.DisplayName)
		}
		t.refreshProvenance()
	}
	r.rebuildOrdered()
}

func unknownProvenance() Provenance {
	return Provenance{
		SourceType: "unknown",
		Freshness:  Freshness{State: "unknown"},
	}
}

func (t *Tenant) refreshProvenance() {
	if strings.TrimSpace(t.SourceType) != "" {
		t.Provenance.SourceType = t.SourceType
	}
	if t.Provenance.SourceType == "" {
		t.Provenance.SourceType = "unknown"
	}
	t.Provenance.CanonicalURLPrefixes = append([]string(nil), t.URLPrefixes...)
	t.Provenance.DocumentCount = t.DocCount
	if normalizedFreshnessState(t.Provenance.Freshness.State) == "unknown" {
		t.Provenance.Freshness = Freshness{State: "unknown"}
		t.Provenance.SourceRevision = ""
		t.Provenance.SourceRevisionType = ""
	}
}

func normalizedFreshnessState(value string) string {
	state := strings.TrimSpace(value)
	switch state {
	case "known", "partial":
		return state
	default:
		return "unknown"
	}
}

func normalizedUTC(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	parsed, err := time.Parse(time.RFC3339Nano, value)
	if err != nil {
		return ""
	}
	return parsed.UTC().Format(time.RFC3339Nano)
}

func normalizeURLValues(raw any) []string {
	switch v := raw.(type) {
	case string:
		return splitCSV(v)
	case []any:
		values := make([]string, 0, len(v))
		for _, item := range v {
			if s, ok := item.(string); ok && strings.TrimSpace(s) != "" {
				values = append(values, strings.TrimSpace(s))
			}
		}
		return values
	default:
		return nil
	}
}

func splitCSV(raw string) []string {
	if raw == "" {
		return nil
	}
	parts := strings.Split(raw, ",")
	values := make([]string, 0, len(parts))
	for _, part := range parts {
		if trimmed := strings.TrimSpace(part); trimmed != "" {
			values = append(values, trimmed)
		}
	}
	return values
}

func publicURLPrefixes(values []string) []string {
	prefixes := make([]string, 0, len(values))
	for _, value := range values {
		parsed, err := url.Parse(strings.TrimSpace(value))
		if err != nil || (parsed.Scheme != "https" && parsed.Scheme != "http") || parsed.Host == "" {
			continue
		}
		parsed.User = nil
		parsed.RawQuery = ""
		parsed.Fragment = ""
		prefixes = append(prefixes, parsed.String())
	}
	return prefixes
}

// formatDisplayName converts "django-rest-framework" to "Django Rest Framework".
func formatDisplayName(codename string) string {
	parts := strings.FieldsFunc(codename, func(r rune) bool {
		return r == '-' || r == '_'
	})
	for i, p := range parts {
		if len(p) > 0 {
			parts[i] = strings.ToUpper(p[:1]) + p[1:]
		}
	}
	return strings.Join(parts, " ")
}
