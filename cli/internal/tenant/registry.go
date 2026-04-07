// Package tenant discovers and manages documentation source metadata from
// the mcp-data directory. It provides a registry for tenant lookup and
// fuzzy matching for tenant discovery by topic.
package tenant

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Tenant holds metadata about a documentation source discovered from mcp-data/.
type Tenant struct {
	Codename    string   `json:"codename"`
	DisplayName string   `json:"display_name"`
	Description string   `json:"description"`
	DocCount    int      `json:"doc_count"`
	DataDir     string   `json:"-"` // Absolute path to tenant directory
	SegmentDB   string   `json:"-"` // Path to latest segment .db
	URLPrefixes []string `json:"url_prefixes,omitempty"`
	SourceType  string   `json:"source_type,omitempty"` // filesystem, online, git
}

// deploymentTenant is the JSON shape of a tenant in deployment.json.
// Fields that can be string or []string in the config use interface{}.
type deploymentTenant struct {
	Codename     string      `json:"codename"`
	DocsName     string      `json:"docs_name"`
	SourceType   string      `json:"source_type"`
	DocsEntryURL any `json:"docs_entry_url"` // string or []string
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
		}

		// Read manifest for doc count and segment ID
		t.loadManifest(segDir)

		// Try to discover URL prefixes and description from meta.json files
		t.loadMetadata(tenantDir)

		r.tenants[codename] = t
	}

	// Build sorted list
	r.ordered = make([]*Tenant, 0, len(r.tenants))
	for _, t := range r.tenants {
		r.ordered = append(r.ordered, t)
	}
	sort.Slice(r.ordered, func(i, j int) bool {
		return r.ordered[i].Codename < r.ordered[j].Codename
	})

	return nil
}

func (t *Tenant) loadManifest(segDir string) {
	data, err := os.ReadFile(filepath.Join(segDir, "manifest.json"))
	if err != nil {
		return
	}
	var manifest struct {
		LatestSegmentID string `json:"latest_segment_id"`
		DocCount        int    `json:"doc_count"`
	}
	if json.Unmarshal(data, &manifest) == nil {
		t.DocCount = manifest.DocCount
		if manifest.LatestSegmentID != "" {
			dbPath := filepath.Join(segDir, manifest.LatestSegmentID+".db")
			if _, err := os.Stat(dbPath); err == nil {
				t.SegmentDB = dbPath
			}
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

	for _, dt := range config.Tenants {
		t := r.tenants[dt.Codename]
		if t == nil {
			continue
		}
		if dt.DocsName != "" {
			t.DisplayName = dt.DocsName
		}
		if dt.SourceType != "" {
			t.SourceType = dt.SourceType
		}
		// Extract entry URL(s) if we don't have URL prefixes from mcp-data scan.
		if len(t.URLPrefixes) == 0 {
			switch v := dt.DocsEntryURL.(type) {
			case string:
				if v != "" {
					t.URLPrefixes = append(t.URLPrefixes, v)
				}
			case []any:
				for _, u := range v {
					if s, ok := u.(string); ok && s != "" {
						t.URLPrefixes = append(t.URLPrefixes, s)
					}
				}
			}
		}
		// Rebuild description with better display name.
		if len(t.URLPrefixes) > 0 {
			t.Description = fmt.Sprintf("Documentation from %s", strings.Join(t.URLPrefixes, ", "))
		} else {
			t.Description = fmt.Sprintf("%s documentation", t.DisplayName)
		}
	}
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
