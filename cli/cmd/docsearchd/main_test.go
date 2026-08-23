package main

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestRunStartsAndShutsDownFromSharedConfig(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve fixture path")
	}
	dataDir := filepath.Join(filepath.Dir(file), "..", "..", "..", "tests", "fixtures", "ci_mcp_data")
	configPath := filepath.Join(t.TempDir(), "config.json")
	raw := fmt.Sprintf(`{"data_dir":%q,"listen":"127.0.0.1:0"}`, dataDir)
	if err := os.WriteFile(configPath, []byte(raw), 0o600); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	var out bytes.Buffer
	if err := run(ctx, []string{"--config", configPath}, &out, &out); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "docsearchd listening on") {
		t.Fatalf("output=%q", out.String())
	}
}

func TestRunRequiresDataDirectory(t *testing.T) {
	missingConfig := filepath.Join(t.TempDir(), "missing.json")
	err := run(context.Background(), []string{"--config", missingConfig}, &bytes.Buffer{}, &bytes.Buffer{})
	if err == nil || !strings.Contains(err.Error(), "data_dir is required") {
		t.Fatalf("error=%v", err)
	}
}
