package tenant

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestRegistryDeploymentConfigIsAuthoritative(t *testing.T) {
	dataDir := t.TempDir()
	mkdirTenantSegments(t, dataDir, "atlassian-onprem-dev")
	mkdirTenantSegments(t, dataDir, "confluence-server-dev")

	configPath := filepath.Join(t.TempDir(), "deployment.json")
	config := `{
  "tenants": [
    {
      "codename": "atlassian-onprem-dev",
      "docs_name": "Atlassian On-Prem Developer Docs",
      "description": "Self-hosted/Data Center Atlassian docs for Confluence, Jira, and JSM.",
      "source_type": "online",
      "url_whitelist_prefixes": "https://developer.atlassian.com/server/confluence/, https://developer.atlassian.com/server/jira/"
    },
    {
      "codename": "jira-cloud-dev",
      "docs_name": "Atlassian Jira Cloud Developer Docs",
      "description": "Jira Cloud docs for Platform, Software, and Service Management.",
      "source_type": "online",
      "docs_sitemap_url": [
        "https://developer.atlassian.com/cloud/jira/platform/sitemap.xml",
        "https://developer.atlassian.com/cloud/jira/software/sitemap.xml"
      ]
    }
  ]
}`
	if err := os.WriteFile(configPath, []byte(config), 0o600); err != nil {
		t.Fatalf("write config: %v", err)
	}

	reg, err := NewRegistry(dataDir, configPath)
	if err != nil {
		t.Fatalf("new registry: %v", err)
	}

	if got := reg.Get("confluence-server-dev"); got != nil {
		t.Fatalf("stale tenant should be filtered, got %#v", got)
	}

	onprem := reg.Get("atlassian-onprem-dev")
	if onprem == nil {
		t.Fatal("configured indexed tenant missing")
	}
	if onprem.DisplayName != "Atlassian On-Prem Developer Docs" {
		t.Fatalf("DisplayName = %q", onprem.DisplayName)
	}
	if onprem.Description != "Self-hosted/Data Center Atlassian docs for Confluence, Jira, and JSM." {
		t.Fatalf("Description = %q", onprem.Description)
	}
	wantPrefixes := []string{
		"https://developer.atlassian.com/server/confluence/",
		"https://developer.atlassian.com/server/jira/",
	}
	if !reflect.DeepEqual(onprem.URLPrefixes, wantPrefixes) {
		t.Fatalf("URLPrefixes = %#v, want %#v", onprem.URLPrefixes, wantPrefixes)
	}

	cloud := reg.Get("jira-cloud-dev")
	if cloud == nil {
		t.Fatal("configured unsynced tenant should be discoverable")
	}
	if cloud.DocCount != 0 || cloud.SegmentDB != "" {
		t.Fatalf("unsynced tenant should not have index data: %#v", cloud)
	}
	if len(cloud.URLPrefixes) != 2 {
		t.Fatalf("cloud URLPrefixes = %#v, want sitemap URLs", cloud.URLPrefixes)
	}
}

func mkdirTenantSegments(t *testing.T, dataDir, codename string) {
	t.Helper()
	segmentsDir := filepath.Join(dataDir, codename, "__search_segments")
	if err := os.MkdirAll(segmentsDir, 0o700); err != nil {
		t.Fatalf("mkdir tenant segments: %v", err)
	}
}

func TestRegistryLoadsIndexBoundProvenance(t *testing.T) {
	dataDir := t.TempDir()
	segmentsDir := filepath.Join(dataDir, "docs", "__search_segments")
	if err := os.MkdirAll(segmentsDir, 0o700); err != nil {
		t.Fatalf("mkdir segments: %v", err)
	}
	manifest := `{
  "latest_segment_id": "segment-123",
  "created_at": "2026-07-18T10:00:00+02:00",
  "doc_count": 42,
  "provenance": {
    "source_type": "git",
    "source_freshness_state": "known",
    "source_updated_at": "2026-07-18T09:30:00+02:00",
    "source_evidence": "git_sync",
    "source_revision": "abc123",
    "source_revision_type": "git_commit"
  }
}`
	if err := os.WriteFile(filepath.Join(segmentsDir, "manifest.json"), []byte(manifest), 0o600); err != nil {
		t.Fatalf("write manifest: %v", err)
	}
	configPath := filepath.Join(t.TempDir(), "deployment.json")
	config := `{"tenants":[{"codename":"docs","docs_name":"Docs","source_type":"git","docs_entry_url":"https://example.com/docs"}]}`
	if err := os.WriteFile(configPath, []byte(config), 0o600); err != nil {
		t.Fatalf("write config: %v", err)
	}

	reg, err := NewRegistry(dataDir, configPath)
	if err != nil {
		t.Fatalf("new registry: %v", err)
	}
	got := reg.Get("docs")
	if got == nil {
		t.Fatal("tenant missing")
	}
	provenance := got.Provenance
	if provenance.SourceType != "git" || provenance.IndexID != "segment-123" || provenance.DocumentCount != 42 {
		t.Fatalf("provenance identity = %#v", provenance)
	}
	if provenance.IndexCreatedAt != "2026-07-18T08:00:00Z" || provenance.Freshness.UpdatedAt != "2026-07-18T07:30:00Z" {
		t.Fatalf("timestamps were not normalized to UTC: %#v", provenance)
	}
	if provenance.Freshness.State != "known" || provenance.Freshness.Evidence != "git_sync" {
		t.Fatalf("freshness = %#v", provenance.Freshness)
	}
	if provenance.SourceRevision != "abc123" || provenance.SourceRevisionType != "git_commit" {
		t.Fatalf("source revision = %#v", provenance)
	}
	if !reflect.DeepEqual(provenance.CanonicalURLPrefixes, []string{"https://example.com/docs"}) {
		t.Fatalf("canonical prefixes = %#v", provenance.CanonicalURLPrefixes)
	}

	encoded, err := json.Marshal(got)
	if err != nil {
		t.Fatalf("marshal tenant: %v", err)
	}
	if strings.Contains(string(encoded), dataDir) {
		t.Fatalf("tenant JSON leaks local data path: %s", encoded)
	}
}

func TestRegistryUsesLegacySummaryOnlyAsPartialEvidence(t *testing.T) {
	dataDir := t.TempDir()
	segmentsDir := filepath.Join(dataDir, "docs", "__search_segments")
	metadataDir := filepath.Join(dataDir, "docs", "__scheduler_meta")
	if err := os.MkdirAll(segmentsDir, 0o700); err != nil {
		t.Fatalf("mkdir segments: %v", err)
	}
	if err := os.MkdirAll(metadataDir, 0o700); err != nil {
		t.Fatalf("mkdir metadata: %v", err)
	}
	if err := os.WriteFile(filepath.Join(segmentsDir, "manifest.json"), []byte(`{"latest_segment_id":"old","created_at":"2026-07-18T08:00:00Z","doc_count":1}`), 0o600); err != nil {
		t.Fatalf("write manifest: %v", err)
	}
	if err := os.WriteFile(filepath.Join(metadataDir, "metadata_summary.json"), []byte(`{"last_success_at":"2026-07-17T12:00:00+02:00"}`), 0o600); err != nil {
		t.Fatalf("write summary: %v", err)
	}
	configPath := filepath.Join(t.TempDir(), "deployment.json")
	if err := os.WriteFile(configPath, []byte(`{"tenants":[{"codename":"docs","source_type":"online"}]}`), 0o600); err != nil {
		t.Fatalf("write config: %v", err)
	}

	reg, err := NewRegistry(dataDir, configPath)
	if err != nil {
		t.Fatalf("new registry: %v", err)
	}
	provenance := reg.Get("docs").Provenance
	if provenance.Freshness.State != "partial" || provenance.Freshness.UpdatedAt != "2026-07-17T10:00:00Z" {
		t.Fatalf("legacy freshness = %#v", provenance.Freshness)
	}
	if provenance.Freshness.Evidence != "scheduler_summary_unbound" {
		t.Fatalf("legacy evidence = %q", provenance.Freshness.Evidence)
	}
}

func TestRegistryTreatsMissingAndMalformedProvenanceAsUnknown(t *testing.T) {
	dataDir := t.TempDir()
	for _, codename := range []string{"missing", "malformed"} {
		mkdirTenantSegments(t, dataDir, codename)
	}
	malformedManifest := `{"latest_segment_id":"bad","created_at":"not-a-time","doc_count":2,"provenance":{"source_freshness_state":"known","source_updated_at":"also-bad","source_revision":"should-not-leak"}}`
	if err := os.WriteFile(filepath.Join(dataDir, "malformed", "__search_segments", "manifest.json"), []byte(malformedManifest), 0o600); err != nil {
		t.Fatalf("write malformed manifest: %v", err)
	}

	reg, err := NewRegistry(dataDir)
	if err != nil {
		t.Fatalf("new registry: %v", err)
	}
	for _, codename := range []string{"missing", "malformed"} {
		provenance := reg.Get(codename).Provenance
		if provenance.Freshness.State != "unknown" || provenance.Freshness.UpdatedAt != "" {
			t.Fatalf("%s freshness = %#v", codename, provenance.Freshness)
		}
		if provenance.IndexCreatedAt != "" || provenance.SourceRevision != "" {
			t.Fatalf("%s fabricated provenance = %#v", codename, provenance)
		}
	}
}

func TestRegistryDoesNotInferIndexedCommitFromCurrentSyncMetadata(t *testing.T) {
	dataDir := t.TempDir()
	segmentsDir := filepath.Join(dataDir, "docs", "__search_segments")
	metadataDir := filepath.Join(dataDir, "docs", "__scheduler_meta")
	if err := os.MkdirAll(segmentsDir, 0o700); err != nil {
		t.Fatalf("mkdir segments: %v", err)
	}
	if err := os.MkdirAll(metadataDir, 0o700); err != nil {
		t.Fatalf("mkdir metadata: %v", err)
	}
	if err := os.WriteFile(filepath.Join(segmentsDir, "manifest.json"), []byte(`{"latest_segment_id":"old","created_at":"2026-07-18T08:00:00Z","doc_count":1}`), 0o600); err != nil {
		t.Fatalf("write manifest: %v", err)
	}
	if err := os.WriteFile(filepath.Join(metadataDir, "meta_last_sync.json"), []byte(`{"last_sync_at":"2026-07-18T09:00:00Z","source_revision":"newer-than-index"}`), 0o600); err != nil {
		t.Fatalf("write sync metadata: %v", err)
	}

	reg, err := NewRegistry(dataDir)
	if err != nil {
		t.Fatalf("new registry: %v", err)
	}
	if revision := reg.Get("docs").Provenance.SourceRevision; revision != "" {
		t.Fatalf("source revision = %q, want empty without index-bound evidence", revision)
	}
}

func TestRegistrySanitizesCanonicalPublicPrefixes(t *testing.T) {
	dataDir := t.TempDir()
	mkdirTenantSegments(t, dataDir, "docs")
	configPath := filepath.Join(t.TempDir(), "deployment.json")
	config := `{"tenants":[{"codename":"docs","docs_entry_url":["file:///private/secret","https://user:token@example.com/docs?key=secret#fragment"]}]}`
	if err := os.WriteFile(configPath, []byte(config), 0o600); err != nil {
		t.Fatalf("write config: %v", err)
	}

	reg, err := NewRegistry(dataDir, configPath)
	if err != nil {
		t.Fatalf("new registry: %v", err)
	}
	prefixes := reg.Get("docs").Provenance.CanonicalURLPrefixes
	if !reflect.DeepEqual(prefixes, []string{"https://example.com/docs"}) {
		t.Fatalf("canonical prefixes = %#v", prefixes)
	}
	encoded, err := json.Marshal(reg.Get("docs"))
	if err != nil {
		t.Fatalf("marshal tenant: %v", err)
	}
	if strings.Contains(string(encoded), "secret") || strings.Contains(string(encoded), "token") {
		t.Fatalf("tenant JSON leaks URL secrets: %s", encoded)
	}
}
