package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"unicode/utf8"
)

func TestFetchDefaultKeepsFullInlineContent(t *testing.T) {
	content := "# Unicode\n\nAé🙂Z"
	dataDir := writeFetchTenant(t, content)

	code, stdout, stderr := runCLI(t, dataDir, "fetch", "docs", "https://example.com/page", "--json")
	if code != exitOK || stderr != "" {
		t.Fatalf("fetch: code=%d stdout=%q stderr=%q", code, stdout, stderr)
	}
	var response struct {
		Content  string `json:"content"`
		Artifact any    `json:"artifact"`
	}
	if err := json.Unmarshal([]byte(stdout), &response); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if response.Content != content || response.Artifact != nil {
		t.Fatalf("response = %#v, want full inline content", response)
	}
}

func TestFetchMaxCharsReturnsValidBoundedUTF8(t *testing.T) {
	content := "Aé🙂Z"
	dataDir := writeFetchTenant(t, content)

	code, stdout, stderr := runCLI(t, dataDir, "fetch", "docs", "https://example.com/page", "--json", "--max-chars", "3")
	if code != exitOK || stderr != "" {
		t.Fatalf("fetch: code=%d stdout=%q stderr=%q", code, stdout, stderr)
	}
	var response struct {
		Content       string `json:"content"`
		Truncated     bool   `json:"truncated"`
		OriginalChars int    `json:"original_chars"`
		ReturnedChars int    `json:"returned_chars"`
		OriginalBytes int    `json:"original_bytes"`
		ReturnedBytes int    `json:"returned_bytes"`
	}
	if err := json.Unmarshal([]byte(stdout), &response); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if response.Content != "Aé🙂" || !utf8.ValidString(response.Content) || !response.Truncated {
		t.Fatalf("bounded content = %#v", response)
	}
	if response.OriginalChars != 4 || response.ReturnedChars != 3 {
		t.Fatalf("character counts = %d/%d, want 4/3", response.OriginalChars, response.ReturnedChars)
	}
	if response.OriginalBytes != len(content) || response.ReturnedBytes != len("Aé🙂") {
		t.Fatalf("byte counts = %d/%d", response.OriginalBytes, response.ReturnedBytes)
	}
}

func TestFetchMaxCharsBeyondContentIsTruthful(t *testing.T) {
	content := "short"
	dataDir := writeFetchTenant(t, content)

	code, stdout, stderr := runCLI(t, dataDir, "fetch", "docs", "https://example.com/page", "--json", "--max-chars", "50")
	if code != exitOK || stderr != "" {
		t.Fatalf("fetch: code=%d stdout=%q stderr=%q", code, stdout, stderr)
	}
	var response struct {
		Content       string `json:"content"`
		Truncated     bool   `json:"truncated"`
		OriginalChars int    `json:"original_chars"`
		ReturnedChars int    `json:"returned_chars"`
	}
	if err := json.Unmarshal([]byte(stdout), &response); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if response.Content != content || response.Truncated || response.OriginalChars != 5 || response.ReturnedChars != 5 {
		t.Fatalf("response = %#v, want non-truncated full content", response)
	}
}

func TestFetchRejectsInvalidOutputPolicy(t *testing.T) {
	dataDir := writeFetchTenant(t, "content")
	destination := filepath.Join(t.TempDir(), "page.md")

	tests := [][]string{
		{"fetch", "docs", "https://example.com/page", "--json", "--max-chars", "0"},
		{"fetch", "docs", "https://example.com/page", "--json", "--max-chars", "-1"},
		{"fetch", "docs", "https://example.com/page", "--json", "--max-chars", "1", "--out", destination},
		{"fetch", "docs", "https://example.com/page", "--json", "--out", ""},
	}

	for _, args := range tests {
		code, stdout, stderr := runCLI(t, dataDir, args...)
		if code != exitUsage || stderr != "" {
			t.Fatalf("args=%q code=%d stdout=%q stderr=%q", args, code, stdout, stderr)
		}
		if failure := decodeFailure(t, stdout); failure.Error.Class != "usage" {
			t.Fatalf("args=%q failure=%#v", args, failure)
		}
	}
}

func TestFetchOutWritesCompleteAtomicArtifact(t *testing.T) {
	content := "# Full document\n\nAé🙂Z\n"
	dataDir := writeFetchTenant(t, content)
	destination := filepath.Join(t.TempDir(), "artifacts", "page.md")
	if err := os.Mkdir(filepath.Dir(destination), 0o700); err != nil {
		t.Fatalf("mkdir artifact dir: %v", err)
	}

	code, stdout, stderr := runCLI(t, dataDir, "fetch", "docs", "https://example.com/page", "--json", "--out", destination)
	if code != exitOK || stderr != "" {
		t.Fatalf("fetch: code=%d stdout=%q stderr=%q", code, stdout, stderr)
	}
	written, err := os.ReadFile(destination)
	if err != nil {
		t.Fatalf("read artifact: %v", err)
	}
	if string(written) != content {
		t.Fatalf("artifact content = %q, want %q", written, content)
	}

	var response struct {
		Content  string `json:"content"`
		Artifact struct {
			Path   string `json:"path"`
			Bytes  int    `json:"bytes"`
			SHA256 string `json:"sha256"`
		} `json:"artifact"`
	}
	if err := json.Unmarshal([]byte(stdout), &response); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	digest := sha256.Sum256([]byte(content))
	if response.Content != "" || response.Artifact.Path != destination || response.Artifact.Bytes != len(content) || response.Artifact.SHA256 != hex.EncodeToString(digest[:]) {
		t.Fatalf("response = %#v", response)
	}
	entries, err := os.ReadDir(filepath.Dir(destination))
	if err != nil {
		t.Fatalf("read artifact dir: %v", err)
	}
	if len(entries) != 1 || entries[0].Name() != filepath.Base(destination) {
		t.Fatalf("artifact directory contains temporary files: %#v", entries)
	}
}

func TestFetchOutFailureUsesJSONErrorWithoutPartialArtifact(t *testing.T) {
	dataDir := writeFetchTenant(t, "content")
	destination := filepath.Join(t.TempDir(), "missing", "page.md")

	code, stdout, stderr := runCLI(t, dataDir, "fetch", "docs", "https://example.com/page", "--json", "--out", destination)
	if code != exitStorage || stderr != "" {
		t.Fatalf("fetch: code=%d stdout=%q stderr=%q", code, stdout, stderr)
	}
	if _, err := os.Stat(destination); !os.IsNotExist(err) {
		t.Fatalf("partial artifact exists or stat failed unexpectedly: %v", err)
	}
	failure := decodeFailure(t, stdout)
	if failure.Error.Class != "storage" || failure.Error.Code != "artifact_write_failed" {
		t.Fatalf("failure = %#v", failure)
	}
}

func TestAtomicWriteReplacesDestinationAndCleansTemporaryFile(t *testing.T) {
	dir := t.TempDir()
	destination := filepath.Join(dir, "page.md")
	if err := os.WriteFile(destination, []byte("old"), 0o600); err != nil {
		t.Fatalf("write old destination: %v", err)
	}

	if err := atomicWriteFile(destination, []byte("new")); err != nil {
		t.Fatalf("atomic write: %v", err)
	}
	data, err := os.ReadFile(destination)
	if err != nil || string(data) != "new" {
		t.Fatalf("destination data=%q err=%v", data, err)
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("read destination dir: %v", err)
	}
	for _, entry := range entries {
		if strings.Contains(entry.Name(), ".tmp-") {
			t.Fatalf("temporary file leaked: %s", entry.Name())
		}
	}
}

func writeFetchTenant(t *testing.T, content string) string {
	t.Helper()
	dataDir := makeCLIDataDir(t)
	tenantDir := filepath.Join(dataDir, "docs")
	if err := os.MkdirAll(filepath.Join(tenantDir, "__search_segments"), 0o700); err != nil {
		t.Fatalf("mkdir segments: %v", err)
	}
	pagePath := filepath.Join(tenantDir, "example.com", "page.md")
	if err := os.MkdirAll(filepath.Dir(pagePath), 0o700); err != nil {
		t.Fatalf("mkdir page dir: %v", err)
	}
	if err := os.WriteFile(pagePath, []byte(content), 0o600); err != nil {
		t.Fatalf("write page: %v", err)
	}
	writeDeployment(t, dataDir, `[{"codename":"docs","docs_name":"Docs","source_type":"online","docs_entry_url":"https://example.com"}]`)
	return dataDir
}
