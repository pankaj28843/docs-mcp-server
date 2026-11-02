package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestMapUsesExplicitIndexEvidence(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "django", "__search_segments")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	manifest := `{"latest_segment_id":"seg","doc_count":1,"provenance":{"indexed_source":{"canonical_url":"https://example.com/6.1/","version_kind":"versioned","version":"6.1","evidence_url":"https://example.com/6.1/"}}}`
	if err := os.WriteFile(filepath.Join(dir, "manifest.json"), []byte(manifest), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "seg.db"), nil, 0600); err != nil {
		t.Fatal(err)
	}
	input := `{"technologies":[{"name":"Django","version":"5.2","version_evidence":"lockfile","comparison":"exact","tenants":["django"]},{"name":"Django","version":"6.1","version_evidence":"lockfile","comparison":"exact","tenants":["django"]},{"name":"Unknown","version":"6.1","comparison":"exact","tenants":["django"]},{"name":"Angular","tenants":[]}]}`
	path := filepath.Join(t.TempDir(), "project.json")
	if err := os.WriteFile(path, []byte(input), 0600); err != nil {
		t.Fatal(err)
	}
	var out, errOut bytes.Buffer
	if code := execute([]string{"map", path, "--mode", "local", "--data-dir", root, "--json"}, &out, &errOut); code != 0 {
		t.Fatalf("exit %d: %s", code, errOut.String())
	}
	var response struct {
		Mappings []mapping `json:"mappings"`
	}
	if err := json.Unmarshal(out.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	want := []string{"mismatch", "match", "unknown", "missing"}
	for i, status := range want {
		if response.Mappings[i].Status != status {
			t.Fatalf("mapping %d = %#v", i, response.Mappings[i])
		}
	}
}
