package api

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/service"
)

func TestClientCallsVersionedAPI(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/search" || r.URL.Query().Get("tenants") != "go" || r.URL.Query().Get("q") != "context cancellation" {
			t.Fatalf("unexpected request %s", r.URL.String())
		}
		writeTestJSON(t, w, output.SearchResponse{Query: "context cancellation", Tenant: "go"})
	}))
	defer server.Close()

	client, err := NewClient(server.URL, server.Client())
	if err != nil {
		t.Fatal(err)
	}
	response, err := client.Search(context.Background(), "go", "context cancellation", 8, 0)
	if err != nil || response.Tenant != "go" {
		t.Fatalf("response=%#v err=%v", response, err)
	}
}

func TestClientReturnsStableServiceError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNotFound)
		writeTestJSON(t, w, map[string]any{"error": map[string]string{"code": "tenant_not_found", "message": "tenant missing"}})
	}))
	defer server.Close()

	client, err := NewClient(server.URL, server.Client())
	if err != nil {
		t.Fatal(err)
	}
	_, err = client.Describe(context.Background(), "missing")
	var domainErr *service.Error
	if !errors.As(err, &domainErr) || domainErr.Code != "tenant_not_found" || domainErr.Message != "tenant missing" {
		t.Fatalf("error=%v", err)
	}
}

func TestClientRejectsInvalidBaseURL(t *testing.T) {
	if _, err := NewClient("relative", http.DefaultClient); err == nil {
		t.Fatal("expected invalid base URL")
	}
}

func writeTestJSON(t *testing.T, w http.ResponseWriter, value any) {
	t.Helper()
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(value); err != nil {
		t.Fatal(err)
	}
}
