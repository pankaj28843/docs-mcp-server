package tenant

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestIndexStatusAndBoundSource(t *testing.T) {
	root := t.TempDir()
	cases := []struct {
		name, manifest, status string
		db                     bool
		count                  *int
	}{
		{"missing", "", "unknown", false, nil},
		{"malformed", "{", "unknown", false, nil},
		{"no-count", `{"latest_segment_id":"seg"}`, "unknown", true, nil},
		{"negative", `{"latest_segment_id":"seg","doc_count":-1}`, "unknown", true, nil},
		{"unavailable", `{"latest_segment_id":"seg","doc_count":3}`, "unavailable", false, intPtr(3)},
		{"empty", `{"latest_segment_id":"seg","doc_count":0}`, "empty", true, intPtr(0)},
		{"searchable", `{"latest_segment_id":"seg","doc_count":3,"provenance":{"indexed_source":{"canonical_url":"https://example.com/6.1/","version_kind":"versioned","version":"6.1","evidence_url":"https://example.com/6.1/"}}}`, "searchable", true, intPtr(3)},
	}
	for _, tc := range cases {
		dir := filepath.Join(root, tc.name, "__search_segments")
		if err := os.MkdirAll(dir, 0700); err != nil {
			t.Fatal(err)
		}
		if tc.manifest != "" {
			if err := os.WriteFile(filepath.Join(dir, "manifest.json"), []byte(tc.manifest), 0600); err != nil {
				t.Fatal(err)
			}
		}
		if tc.db {
			if err := os.WriteFile(filepath.Join(dir, "seg.db"), nil, 0600); err != nil {
				t.Fatal(err)
			}
		}
	}
	reg, err := NewRegistry(root)
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			p := reg.Get(tc.name).Provenance
			if p.IndexStatus != tc.status {
				t.Fatalf("status = %s, want %s", p.IndexStatus, tc.status)
			}
			if (p.IndexedDocumentCount == nil) != (tc.count == nil) || tc.count != nil && *p.IndexedDocumentCount != *tc.count {
				t.Fatalf("count = %v, want %v", p.IndexedDocumentCount, tc.count)
			}
		})
	}
	source := reg.Get("searchable").Provenance.IndexedSource
	if source == nil || source.Version != "6.1" {
		t.Fatalf("indexed source = %#v", source)
	}
}
func intPtr(i int) *int { return &i }

func TestIndexedSourcePreservesEvidenceURL(t *testing.T) {
	for _, tc := range []struct {
		name, evidence string
		valid          bool
	}{
		{"version query and fragment", "https://example.com/docs?version=5.2#csrf", true},
		{"credentials", "https://user:secret@example.com/docs?version=5.2", false},
		{"invalid port", "https://example.com:99999/docs", false},
		{"whitespace", "https://example.com/docs?version=5.2 bad", false},
		{"non-http", "file:///private/docs", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			root := t.TempDir()
			dir := filepath.Join(root, "docs", "__search_segments")
			if err := os.MkdirAll(dir, 0700); err != nil {
				t.Fatal(err)
			}
			manifest, err := json.Marshal(map[string]any{"latest_segment_id": "seg", "doc_count": 1, "provenance": map[string]any{"indexed_source": IndexedSource{CanonicalURL: "https://example.com/docs", VersionKind: "versioned", Version: "5.2", EvidenceURL: tc.evidence}}})
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(dir, "manifest.json"), manifest, 0600); err != nil {
				t.Fatal(err)
			}
			reg, err := NewRegistry(root)
			if err != nil {
				t.Fatal(err)
			}
			source := reg.Get("docs").Provenance.IndexedSource
			if !tc.valid {
				if source != nil {
					t.Fatalf("invalid evidence accepted: %#v", source)
				}
				return
			}
			if source == nil || source.EvidenceURL != tc.evidence {
				t.Fatalf("evidence = %#v, want %q", source, tc.evidence)
			}
		})
	}
}
