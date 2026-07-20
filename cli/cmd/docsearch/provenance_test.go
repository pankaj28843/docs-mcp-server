package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/tenant"
)

func TestCommandsExposeComparableProvenance(t *testing.T) {
	dataDir := makeCLIDataDir(t)
	writeEmptySegment(t, dataDir, "docs")
	tenantDir := filepath.Join(dataDir, "docs")
	pagePath := filepath.Join(tenantDir, "example.com", "page.md")
	if err := os.MkdirAll(filepath.Dir(pagePath), 0o700); err != nil {
		t.Fatalf("mkdir page dir: %v", err)
	}
	if err := os.WriteFile(pagePath, []byte("content"), 0o600); err != nil {
		t.Fatalf("write page: %v", err)
	}
	manifest := `{
  "latest_segment_id":"empty-segment",
  "created_at":"2026-07-18T08:00:00Z",
  "doc_count":0,
  "provenance":{
    "source_type":"online",
    "source_freshness_state":"known",
    "source_updated_at":"2026-07-18T07:00:00Z",
    "source_evidence":"document_last_fetched_at"
  }
}`
	if err := os.WriteFile(filepath.Join(tenantDir, "__search_segments", "manifest.json"), []byte(manifest), 0o600); err != nil {
		t.Fatalf("rewrite manifest: %v", err)
	}
	writeDeployment(t, dataDir, `[{"codename":"docs","docs_name":"Docs","source_type":"online","docs_entry_url":"https://example.com"}]`)

	commands := [][]string{
		{"list", "--json"},
		{"describe", "docs", "--json"},
		{"search", "docs", "nothing", "--json"},
		{"fetch", "docs", "https://example.com/page", "--json"},
	}
	for _, args := range commands {
		code, stdout, stderr := runCLI(t, dataDir, args...)
		if code != exitOK || stderr != "" {
			t.Fatalf("args=%q code=%d stdout=%q stderr=%q", args, code, stdout, stderr)
		}
		var payload any
		if err := json.Unmarshal([]byte(stdout), &payload); err != nil {
			t.Fatalf("args=%q invalid JSON: %v", args, err)
		}
		if !strings.Contains(stdout, `"index_id": "empty-segment"`) || !strings.Contains(stdout, `"source_type": "online"`) {
			t.Fatalf("args=%q missing provenance: %s", args, stdout)
		}
		if strings.Contains(stdout, dataDir) {
			t.Fatalf("args=%q leaks absolute data path: %s", args, stdout)
		}
	}
}

func TestProvenanceSummaryShowsEvidenceAndAge(t *testing.T) {
	now := time.Date(2026, 7, 18, 12, 0, 0, 0, time.UTC)
	fresh := tenant.Provenance{
		SourceType:     "online",
		IndexCreatedAt: "2026-07-18T11:30:00Z",
		Freshness: tenant.Freshness{
			State:     "known",
			UpdatedAt: "2026-07-18T10:00:00Z",
		},
	}
	stale := fresh
	stale.IndexCreatedAt = "2025-06-13T12:00:00Z"
	stale.Freshness.UpdatedAt = "2025-06-13T12:00:00Z"

	if got := provenanceSummary(fresh, now); !strings.Contains(got, "known") || !strings.Contains(got, "2h ago") || !strings.Contains(got, "30m ago") {
		t.Fatalf("fresh summary = %q", got)
	}
	if got := provenanceSummary(stale, now); !strings.Contains(got, "400d ago") {
		t.Fatalf("stale summary = %q", got)
	}
}
