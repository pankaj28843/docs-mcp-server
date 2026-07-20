package main

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	_ "modernc.org/sqlite"
)

func TestJSONFailuresAreMachineDetectable(t *testing.T) {
	dataDir := makeCLIDataDir(t)

	tests := []struct {
		name     string
		args     []string
		wantCode int
		wantKind string
		wantErr  string
	}{
		{
			name:     "search unknown tenant",
			args:     []string{"search", "missing", "query", "--json"},
			wantCode: exitTenant,
			wantKind: "tenant",
			wantErr:  "tenant_not_found",
		},
		{
			name:     "fetch unknown tenant",
			args:     []string{"fetch", "missing", "https://example.com/page", "--json"},
			wantCode: exitTenant,
			wantKind: "tenant",
			wantErr:  "tenant_not_found",
		},
		{
			name:     "describe unknown tenant",
			args:     []string{"describe", "missing", "--json"},
			wantCode: exitTenant,
			wantKind: "tenant",
			wantErr:  "tenant_not_found",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			code, stdout, stderr := runCLI(t, dataDir, tt.args...)
			if code != tt.wantCode {
				t.Fatalf("exit code = %d, want %d; stdout=%q stderr=%q", code, tt.wantCode, stdout, stderr)
			}
			if stderr != "" {
				t.Fatalf("stderr = %q, want empty JSON stderr", stderr)
			}

			failure := decodeFailure(t, stdout)
			if failure.Error.Class != tt.wantKind || failure.Error.Code != tt.wantErr {
				t.Fatalf("failure = %#v, want class=%q code=%q", failure, tt.wantKind, tt.wantErr)
			}
			if failure.Error.Message == "" || len(failure.Error.Actions) == 0 {
				t.Fatalf("failure lacks message/actions: %#v", failure)
			}
		})
	}
}

func TestSearchRejectsInvalidLimitsBeforeOpeningStorage(t *testing.T) {
	missingDataDir := filepath.Join(t.TempDir(), "missing")

	tests := []struct {
		name string
		args []string
	}{
		{name: "zero size", args: []string{"search", "tenant", "query", "--size", "0", "--json"}},
		{name: "negative size", args: []string{"search", "tenant", "query", "--size", "-1", "--json"}},
		{name: "oversized", args: []string{"search", "tenant", "query", "--size", "101", "--json"}},
		{name: "search all zero size", args: []string{"search-all", "query", "--size", "0", "--json"}},
		{name: "negative total", args: []string{"search-all", "query", "--total", "-1", "--json"}},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			code, stdout, stderr := runCLI(t, missingDataDir, tt.args...)
			if code != exitUsage {
				t.Fatalf("exit code = %d, want %d; stdout=%q stderr=%q", code, exitUsage, stdout, stderr)
			}
			if stderr != "" {
				t.Fatalf("stderr = %q, want empty JSON stderr", stderr)
			}
			failure := decodeFailure(t, stdout)
			if failure.Error.Class != "usage" || failure.Error.Code != "invalid_argument" {
				t.Fatalf("failure = %#v, want usage/invalid_argument", failure)
			}
		})
	}
}

func TestMissingStorageAndIndexHaveDistinctFailures(t *testing.T) {
	missingDataDir := filepath.Join(t.TempDir(), "missing")
	notDirectory := filepath.Join(t.TempDir(), "not-a-directory")
	if err := os.WriteFile(notDirectory, []byte("not a data root"), 0o600); err != nil {
		t.Fatalf("write non-directory data root: %v", err)
	}
	for name, dataRoot := range map[string]string{"missing": missingDataDir, "unreadable": notDirectory} {
		t.Run(name+" data root", func(t *testing.T) {
			code, stdout, stderr := runCLI(t, dataRoot, "list", "--json")
			if code != exitStorage || stderr != "" {
				t.Fatalf("storage: code=%d stdout=%q stderr=%q", code, stdout, stderr)
			}
			if got := decodeFailure(t, stdout).Error; got.Class != "storage" || got.Code != "data_root_unavailable" {
				t.Fatalf("storage failure = %#v", got)
			}
		})
	}

	dataDir := makeCLIDataDir(t)
	writeDeployment(t, dataDir, `[{"codename":"empty","docs_name":"Empty","source_type":"online"}]`)
	code, stdout, stderr := runCLI(t, dataDir, "search", "empty", "query", "--json")
	if code != exitIndex || stderr != "" {
		t.Fatalf("missing index: code=%d stdout=%q stderr=%q", code, stdout, stderr)
	}
	if got := decodeFailure(t, stdout).Error; got.Class != "index" || got.Code != "index_unavailable" {
		t.Fatalf("missing index failure = %#v", got)
	}
}

func TestMissingDocumentHasDocumentFailure(t *testing.T) {
	dataDir := writeFetchTenant(t, "content")
	code, stdout, stderr := runCLI(t, dataDir, "fetch", "docs", "https://example.com/missing", "--json")
	if code != exitDocument || stderr != "" {
		t.Fatalf("missing document: code=%d stdout=%q stderr=%q", code, stdout, stderr)
	}
	if got := decodeFailure(t, stdout).Error; got.Class != "document" || got.Code != "document_not_found" {
		t.Fatalf("missing document failure = %#v", got)
	}
}

func TestSuccessfulEmptySearchIsNotAnError(t *testing.T) {
	dataDir := makeCLIDataDir(t)
	writeEmptySegment(t, dataDir, "empty")
	writeDeployment(t, dataDir, `[{"codename":"empty","docs_name":"Empty","source_type":"online"}]`)

	code, stdout, stderr := runCLI(t, dataDir, "search", "empty", "nothing", "--json")
	if code != exitOK || stderr != "" {
		t.Fatalf("empty search: code=%d stdout=%q stderr=%q", code, stdout, stderr)
	}
	var response struct {
		Tenant  string `json:"tenant"`
		Results []any  `json:"results"`
	}
	if err := json.Unmarshal([]byte(stdout), &response); err != nil {
		t.Fatalf("decode success: %v; output=%q", err, stdout)
	}
	if response.Tenant != "empty" || len(response.Results) != 0 {
		t.Fatalf("response = %#v, want tenant and empty results", response)
	}
}

func TestTextAndJSONFailuresUseSameExitClass(t *testing.T) {
	dataDir := makeCLIDataDir(t)
	jsonCode, _, jsonStderr := runCLI(t, dataDir, "describe", "missing", "--json")
	textCode, textStdout, textStderr := runCLI(t, dataDir, "describe", "missing")

	if jsonCode != exitTenant || textCode != jsonCode {
		t.Fatalf("JSON/text exit codes = %d/%d, want %d", jsonCode, textCode, exitTenant)
	}
	if jsonStderr != "" || textStdout != "" || textStderr == "" {
		t.Fatalf("unexpected streams: json stderr=%q text stdout=%q stderr=%q", jsonStderr, textStdout, textStderr)
	}
}

func runCLI(t *testing.T, dataDir string, args ...string) (int, string, string) {
	t.Helper()
	t.Setenv("TECHDOCS_DEPLOYMENT_CONFIG", "")
	t.Setenv("TECHDOCS_DATA_DIR", "")
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	allArgs := append([]string{"--data-dir", dataDir}, args...)
	code := execute(allArgs, &stdout, &stderr)
	return code, stdout.String(), stderr.String()
}

func decodeFailure(t *testing.T, raw string) errorResponse {
	t.Helper()
	var response errorResponse
	decoder := json.NewDecoder(bytes.NewBufferString(raw))
	if err := decoder.Decode(&response); err != nil {
		t.Fatalf("decode failure JSON: %v; output=%q", err, raw)
	}
	var extra any
	if err := decoder.Decode(&extra); err == nil {
		t.Fatalf("output contains more than one JSON value: %q", raw)
	}
	return response
}

func makeCLIDataDir(t *testing.T) string {
	t.Helper()
	dataDir := filepath.Join(t.TempDir(), "mcp-data")
	if err := os.MkdirAll(dataDir, 0o700); err != nil {
		t.Fatalf("mkdir data dir: %v", err)
	}
	return dataDir
}

func writeDeployment(t *testing.T, dataDir, tenantsJSON string) {
	t.Helper()
	configPath := filepath.Join(filepath.Dir(dataDir), "deployment.json")
	if err := os.WriteFile(configPath, []byte(`{"tenants":`+tenantsJSON+`}`), 0o600); err != nil {
		t.Fatalf("write deployment config: %v", err)
	}
}

func writeEmptySegment(t *testing.T, dataDir, codename string) {
	t.Helper()
	segmentsDir := filepath.Join(dataDir, codename, "__search_segments")
	if err := os.MkdirAll(segmentsDir, 0o700); err != nil {
		t.Fatalf("mkdir segments: %v", err)
	}
	const segmentID = "empty-segment"
	manifest := `{"latest_segment_id":"` + segmentID + `","created_at":"2026-07-18T00:00:00Z","doc_count":0}`
	if err := os.WriteFile(filepath.Join(segmentsDir, "manifest.json"), []byte(manifest), 0o600); err != nil {
		t.Fatalf("write manifest: %v", err)
	}

	db, err := sql.Open("sqlite", filepath.Join(segmentsDir, segmentID+".db"))
	if err != nil {
		t.Fatalf("open fixture database: %v", err)
	}
	if _, err := db.Exec(`CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO metadata (key, value) VALUES ('doc_count', '0'), ('body_total_terms', '0');`); err != nil {
		db.Close()
		t.Fatalf("create fixture database: %v", err)
	}
	if err := db.Close(); err != nil {
		t.Fatalf("close fixture database: %v", err)
	}
}
