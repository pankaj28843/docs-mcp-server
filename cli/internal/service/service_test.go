package service

import (
	"context"
	"database/sql"
	"errors"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/tenant"
)

func fixtureData(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve fixture root")
	}
	return filepath.Join(filepath.Dir(file), "..", "..", "..", "tests", "fixtures", "ci_mcp_data")
}

func TestServiceUsesRealSegmentsAndDocuments(t *testing.T) {
	svc, err := New(fixtureData(t), "", 2)
	if err != nil {
		t.Fatal(err)
	}
	list, err := svc.List(context.Background())
	if err != nil || list.Count != 3 {
		t.Fatalf("list count=%d err=%v", list.Count, err)
	}
	search, err := svc.Search(context.Background(), "webapi-ci", "routing", 5, 5)
	if err != nil || len(search.Results) == 0 || search.Results[0].URL != "https://webapi.example.com/tutorial/routing/" {
		t.Fatalf("search=%#v err=%v", search, err)
	}
	fetch, err := svc.Fetch(context.Background(), "webapi-ci", search.Results[0].URL, 20)
	if err != nil || fetch.Content == nil || fetch.Truncated == nil {
		t.Fatalf("fetch=%#v err=%v", fetch, err)
	}
}

func TestServiceReturnsStableMissingTenantError(t *testing.T) {
	svc, err := New(fixtureData(t), "", 2)
	if err != nil {
		t.Fatal(err)
	}
	_, err = svc.Describe(context.Background(), "missing")
	var domainErr *Error
	if !errors.As(err, &domainErr) || domainErr.Code != "tenant_not_found" {
		t.Fatalf("error=%v", err)
	}
}

func TestServiceHonorsCancelledContext(t *testing.T) {
	svc, err := New(fixtureData(t), "", 2)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err = svc.List(ctx)
	var domainErr *Error
	if !errors.As(err, &domainErr) || domainErr.Code != "request_cancelled" {
		t.Fatalf("error=%v", err)
	}
}

func TestDiskCandidatesStayInsideTenantRoot(t *testing.T) {
	item := &tenant.Tenant{DataDir: "/srv/mcp-data/docs"}
	parsed, err := url.Parse("https://docs.example/../../private/secret")
	if err != nil {
		t.Fatal(err)
	}
	if candidates := diskCandidates(item, parsed); len(candidates) != 0 {
		t.Fatalf("path traversal produced candidates: %v", candidates)
	}
}

func TestSearchAndFetchRebaseImportedFileURLs(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(fixtureData(t), "gitdocs-ci", "__search_segments")
	target := filepath.Join(root, "gitdocs-ci", "__search_segments")
	if err := os.MkdirAll(target, 0755); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"manifest.json", "ci_fixture_001.db"} {
		data, err := os.ReadFile(filepath.Join(source, name))
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(target, name), data, 0644); err != nil {
			t.Fatal(err)
		}
	}
	db, err := sql.Open("sqlite", filepath.Join(target, "ci_fixture_001.db"))
	if err != nil {
		t.Fatal(err)
	}
	_, err = db.Exec("UPDATE documents SET url = 'file:///missing/producer/gitdocs-ci/' || path WHERE path IS NOT NULL")
	if err != nil {
		t.Fatal(err)
	}
	db.Close()
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	relativeRoot, err := filepath.Rel(cwd, root)
	if err != nil {
		t.Fatal(err)
	}
	svc, err := New(relativeRoot, "", 2)
	if err != nil {
		t.Fatal(err)
	}
	got, err := svc.Search(context.Background(), "gitdocs-ci", "themes", 5, 5)
	if err != nil || len(got.Results) == 0 {
		t.Fatalf("search=%#v err=%v", got, err)
	}
	if !strings.HasPrefix(got.Results[0].URL, "file://"+root+"/gitdocs-ci/") {
		t.Fatalf("URL=%q", got.Results[0].URL)
	}
	fetched, err := svc.Fetch(context.Background(), "gitdocs-ci", got.Results[0].URL, 0)
	if err != nil || fetched.Content == nil || *fetched.Content == "" {
		t.Fatalf("fetch=%#v err=%v", fetched, err)
	}
}

func TestLocalDocumentURLWithRelativeDataDir(t *testing.T) {
	item := &tenant.Tenant{DataDir: "relative/docs"}
	root, err := filepath.Abs(item.DataDir)
	if err != nil {
		t.Fatal(err)
	}
	want := (&url.URL{Scheme: "file", Path: filepath.ToSlash(filepath.Join(root, "guide.md"))}).String()
	if got := localDocumentURL(item, "file:///producer/docs/guide.md", "guide.md"); got != want {
		t.Fatalf("got %q want %q", got, want)
	}
}

func TestLocalDocumentURLPreservesCanonicalAndUnsafePaths(t *testing.T) {
	item := &tenant.Tenant{DataDir: "/consumer/docs"}
	for _, tc := range []struct{ raw, path, want string }{
		{"https://example.com/guide", "guide.md", "https://example.com/guide"},
		{"file:///producer/docs/guide%20one.md", "guide one.md", "file:///consumer/docs/guide%20one.md"},
		{"file:///producer/other.md", "guide.md", "file:///producer/other.md"},
		{"file:///producer/docs/guide.md", "../guide.md", "file:///producer/docs/guide.md"},
	} {
		if got := localDocumentURL(item, tc.raw, tc.path); got != tc.want {
			t.Errorf("got %q want %q", got, tc.want)
		}
	}
}
