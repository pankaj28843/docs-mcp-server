package api

import (
	"context"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/cache"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/service"
)

func TestDiscoveryMetadataRoundTripsThroughDaemon(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "docs", "__search_segments")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	manifest := `{"latest_segment_id":"seg","doc_count":0,"provenance":{"indexed_source":{"canonical_url":"https://example.com/1/","version_kind":"versioned","version":"1","evidence_url":"https://example.com/1/"}}}`
	if err := os.WriteFile(filepath.Join(dir, "manifest.json"), []byte(manifest), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "seg.db"), nil, 0600); err != nil {
		t.Fatal(err)
	}
	svc, err := service.New(root, "", 1)
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(NewHandler(svc, cache.New(1<<20, time.Minute)))
	defer server.Close()
	client, err := NewClient(server.URL, server.Client())
	if err != nil {
		t.Fatal(err)
	}
	list, err := client.List(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	find, err := client.Find(context.Background(), "docs")
	if err != nil {
		t.Fatal(err)
	}
	desc, err := client.Describe(context.Background(), "docs")
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range []struct {
		status  string
		count   *int
		version string
	}{
		{list.Tenants[0].Provenance.IndexStatus, list.Tenants[0].Provenance.IndexedDocumentCount, list.Tenants[0].Provenance.IndexedSource.Version},
		{find.Tenants[0].Provenance.IndexStatus, find.Tenants[0].Provenance.IndexedDocumentCount, find.Tenants[0].Provenance.IndexedSource.Version},
		{desc.Provenance.IndexStatus, desc.Provenance.IndexedDocumentCount, desc.Provenance.IndexedSource.Version},
	} {
		if p.status != "empty" || p.count == nil || *p.count != 0 || p.version != "1" {
			t.Fatalf("unexpected provenance: %#v", p)
		}
	}
}
