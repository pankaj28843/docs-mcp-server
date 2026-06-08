package tenant

import (
	"os"
	"path/filepath"
	"reflect"
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
