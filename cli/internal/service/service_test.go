package service

import (
	"context"
	"errors"
	"net/url"
	"path/filepath"
	"runtime"
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
