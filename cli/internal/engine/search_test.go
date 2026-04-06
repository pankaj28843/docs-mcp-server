package engine

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/storage"
)

// goldenResult matches the JSON structure in tests/fixtures/golden/
type goldenResult struct {
	URL   string  `json:"url"`
	Title string  `json:"title"`
	Rank  int     `json:"rank"`
	Score float64 `json:"score"`
}

type goldenFile struct {
	Tenant  string         `json:"tenant"`
	Query   string         `json:"query"`
	Results []goldenResult `json:"results"`
}

func projectRoot(t *testing.T) string {
	t.Helper()
	_, filename, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot determine project root")
	}
	// cli/internal/engine/ -> project root
	return filepath.Join(filepath.Dir(filename), "..", "..", "..")
}

func fixtureSegmentPath(t *testing.T, tenant string) string {
	t.Helper()
	root := projectRoot(t)
	segDir := filepath.Join(root, "tests", "fixtures", "ci_mcp_data", tenant, "__search_segments")
	dbPath, err := storage.FindLatestDB(segDir)
	if err != nil {
		t.Fatalf("fixture segment not found for %s: %v", tenant, err)
	}
	return dbPath
}

func loadGolden(t *testing.T, filename string) goldenFile {
	t.Helper()
	root := projectRoot(t)
	path := filepath.Join(root, "tests", "fixtures", "golden", filename)
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read golden %s: %v", filename, err)
	}
	var g goldenFile
	if err := json.Unmarshal(data, &g); err != nil {
		t.Fatalf("parse golden %s: %v", filename, err)
	}
	return g
}

func searchFixture(t *testing.T, tenant, query string) []SearchResult {
	t.Helper()
	dbPath := fixtureSegmentPath(t, tenant)
	seg, err := storage.OpenSegment(dbPath)
	if err != nil {
		t.Fatalf("open segment: %v", err)
	}
	defer seg.Close()

	results, err := SearchSegment(seg, query, 10)
	if err != nil {
		t.Fatalf("search: %v", err)
	}
	return results
}

func TestSearchWebapiRouting(t *testing.T) {
	golden := loadGolden(t, "search_webapi_ci_routing.json")
	results := searchFixture(t, "webapi-ci", "routing")
	if len(results) == 0 {
		t.Fatal("expected results")
	}
	if results[0].URL != golden.Results[0].URL {
		t.Errorf("rank-1 URL = %q, want %q", results[0].URL, golden.Results[0].URL)
	}
}

func TestSearchWebapiSecurity(t *testing.T) {
	golden := loadGolden(t, "search_webapi_ci_security.json")
	results := searchFixture(t, "webapi-ci", "security")
	if len(results) == 0 {
		t.Fatal("expected results")
	}
	if results[0].URL != golden.Results[0].URL {
		t.Errorf("rank-1 URL = %q, want %q", results[0].URL, golden.Results[0].URL)
	}
}

func TestSearchGitdocsThemes(t *testing.T) {
	golden := loadGolden(t, "search_gitdocs_ci_themes.json")
	results := searchFixture(t, "gitdocs-ci", "themes")
	if len(results) == 0 {
		t.Fatal("expected results")
	}
	if results[0].URL != golden.Results[0].URL {
		t.Errorf("rank-1 URL = %q, want %q", results[0].URL, golden.Results[0].URL)
	}
}

func TestSearchLocaldocsTools(t *testing.T) {
	golden := loadGolden(t, "search_localdocs_ci_tools.json")
	results := searchFixture(t, "localdocs-ci", "tools")
	if len(results) == 0 {
		t.Fatal("expected results")
	}
	if results[0].URL != golden.Results[0].URL {
		t.Errorf("rank-1 URL = %q, want %q", results[0].URL, golden.Results[0].URL)
	}
}

func TestSearchGitdocsPlugins(t *testing.T) {
	golden := loadGolden(t, "search_gitdocs_ci_plugins.json")
	results := searchFixture(t, "gitdocs-ci", "plugins")
	if len(results) == 0 {
		t.Fatal("expected results")
	}
	if results[0].URL != golden.Results[0].URL {
		t.Errorf("rank-1 URL = %q, want %q", results[0].URL, golden.Results[0].URL)
	}
}
