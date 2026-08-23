package api

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/cache"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/service"
)

type fakeReader struct {
	searchCalls int
	err         error
}

func (f *fakeReader) List(context.Context) (output.ListResponse, error) {
	return output.ListResponse{Count: 1, Tenants: []output.TenantInfo{{Codename: "docs", DocCount: 2}}}, f.err
}

func (f *fakeReader) Find(context.Context, string) (output.FindResponse, error) {
	return output.FindResponse{Query: "doc", Count: 1}, f.err
}

func (f *fakeReader) Describe(context.Context, string) (output.DescribeResponse, error) {
	return output.DescribeResponse{Codename: "docs", DocCount: 2}, f.err
}

func (f *fakeReader) Search(_ context.Context, tenants, query string, size, total int) (output.SearchResponse, error) {
	f.searchCalls++
	return output.SearchResponse{Tenant: tenants, Query: query, Results: []output.SearchResult{{URL: "https://example.com", Title: "Example"}}}, f.err
}

func (f *fakeReader) Fetch(context.Context, string, string, int) (output.FetchResponse, error) {
	content := "content"
	return output.FetchResponse{Tenant: "docs", URL: "https://example.com", Content: &content}, f.err
}

func TestHandlerHealthAndVersionedRoutes(t *testing.T) {
	h := NewHandler(&fakeReader{}, cache.New(1024, time.Minute))

	health := httptest.NewRecorder()
	h.ServeHTTP(health, httptest.NewRequest(http.MethodGet, "/healthz", nil))
	if health.Code != http.StatusOK || health.Header().Get("Content-Type") != "application/json" {
		t.Fatalf("health status=%d content-type=%q body=%s", health.Code, health.Header().Get("Content-Type"), health.Body.String())
	}

	list := httptest.NewRecorder()
	h.ServeHTTP(list, httptest.NewRequest(http.MethodGet, "/v1/tenants", nil))
	var response output.ListResponse
	if err := json.Unmarshal(list.Body.Bytes(), &response); err != nil || response.Count != 1 {
		t.Fatalf("list response=%#v err=%v body=%s", response, err, list.Body.String())
	}
}

func TestHandlerValidatesSearchBoundsBeforeService(t *testing.T) {
	fake := &fakeReader{}
	h := NewHandler(fake, cache.New(1024, time.Minute))
	response := httptest.NewRecorder()
	h.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/v1/search?tenants=docs&q=query&size=101", nil))

	if response.Code != http.StatusBadRequest || fake.searchCalls != 0 {
		t.Fatalf("status=%d calls=%d body=%s", response.Code, fake.searchCalls, response.Body.String())
	}
	assertErrorCode(t, response, "invalid_argument")
}

func TestHandlerCachesSuccessfulGETByExactRequest(t *testing.T) {
	fake := &fakeReader{}
	h := NewHandler(fake, cache.New(1024, time.Minute))
	request := "/v1/search?tenants=docs&q=query&size=5"

	first := httptest.NewRecorder()
	h.ServeHTTP(first, httptest.NewRequest(http.MethodGet, request, nil))
	second := httptest.NewRecorder()
	h.ServeHTTP(second, httptest.NewRequest(http.MethodGet, request, nil))

	if fake.searchCalls != 1 || first.Header().Get("X-Docs-Cache") != "MISS" || second.Header().Get("X-Docs-Cache") != "HIT" {
		t.Fatalf("calls=%d first=%q second=%q", fake.searchCalls, first.Header().Get("X-Docs-Cache"), second.Header().Get("X-Docs-Cache"))
	}
	if first.Body.String() != second.Body.String() {
		t.Fatal("cached response changed")
	}
}

func TestHandlerMapsServiceFailures(t *testing.T) {
	h := NewHandler(&fakeReader{err: service.NewError("tenant_not_found", "missing tenant")}, cache.New(0, time.Minute))
	response := httptest.NewRecorder()
	h.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/v1/tenants/missing", nil))
	if response.Code != http.StatusNotFound {
		t.Fatalf("status=%d body=%s", response.Code, response.Body.String())
	}
	assertErrorCode(t, response, "tenant_not_found")
}

func TestHandlerRejectsNonGETAndUnknownRoutes(t *testing.T) {
	h := NewHandler(&fakeReader{}, cache.New(0, time.Minute))
	post := httptest.NewRecorder()
	h.ServeHTTP(post, httptest.NewRequest(http.MethodPost, "/v1/search", nil))
	if post.Code != http.StatusMethodNotAllowed {
		t.Fatalf("POST status=%d", post.Code)
	}
	missing := httptest.NewRecorder()
	h.ServeHTTP(missing, httptest.NewRequest(http.MethodGet, "/v2/search", nil))
	if missing.Code != http.StatusNotFound {
		t.Fatalf("missing status=%d", missing.Code)
	}
}

func TestHandlerMapsInternalFailureWithoutLeakingCause(t *testing.T) {
	h := NewHandler(&fakeReader{err: errors.New("secret filesystem path")}, cache.New(0, time.Minute))
	response := httptest.NewRecorder()
	h.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/v1/tenants", nil))
	if response.Code != http.StatusInternalServerError {
		t.Fatalf("status=%d", response.Code)
	}
	assertErrorCode(t, response, "internal_error")
	if got := response.Body.String(); got == "" || contains(got, "secret filesystem path") {
		t.Fatalf("unsafe error body=%q", got)
	}
}

func assertErrorCode(t *testing.T, response *httptest.ResponseRecorder, want string) {
	t.Helper()
	var body struct {
		Error struct {
			Code string `json:"code"`
		} `json:"error"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil || body.Error.Code != want {
		t.Fatalf("error code=%q want=%q err=%v body=%s", body.Error.Code, want, err, response.Body.String())
	}
}

func contains(value, substring string) bool {
	for i := 0; i+len(substring) <= len(value); i++ {
		if value[i:i+len(substring)] == substring {
			return true
		}
	}
	return false
}
