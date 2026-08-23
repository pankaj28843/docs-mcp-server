package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestPathUsesXDGConfigHome(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", filepath.Join(t.TempDir(), "config"))
	t.Setenv("HOME", filepath.Join(t.TempDir(), "home"))

	got, err := Path("")
	if err != nil {
		t.Fatal(err)
	}
	want := filepath.Join(os.Getenv("XDG_CONFIG_HOME"), "docs-search", "config.json")
	if got != want {
		t.Fatalf("Path() = %q, want %q", got, want)
	}
}

func TestLoadMissingReturnsSafeDefaults(t *testing.T) {
	path := filepath.Join(t.TempDir(), "missing.json")
	cfg, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Listen != DefaultListen || cfg.CacheMaxBytes != DefaultCacheMaxBytes {
		t.Fatalf("defaults = %#v", cfg)
	}
	if cfg.CacheMaxBytes > MaxCacheBytes {
		t.Fatalf("default cache %d exceeds hard limit %d", cfg.CacheMaxBytes, MaxCacheBytes)
	}
}

func TestLoadRejectsCacheAboveHardLimit(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.json")
	raw := `{"cache_max_bytes":524288001}`
	if err := os.WriteFile(path, []byte(raw), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(path); err == nil {
		t.Fatal("Load accepted cache above 500 MiB")
	}
}

func TestLoadMergesFileOverDefaults(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.json")
	raw := `{"data_dir":"/srv/docs/mcp-data","server_url":"http://10.20.30.10:42142","listen":"0.0.0.0:42142","cache_max_bytes":1048576}`
	if err := os.WriteFile(path, []byte(raw), 0o600); err != nil {
		t.Fatal(err)
	}
	cfg, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.DataDir != "/srv/docs/mcp-data" || cfg.Listen != "0.0.0.0:42142" || cfg.CacheMaxBytes != 1048576 {
		t.Fatalf("loaded config = %#v", cfg)
	}
}

func TestValidateRejectsInvalidServerURL(t *testing.T) {
	cfg := Defaults()
	cfg.ServerURL = "not a URL"
	if err := cfg.Validate(); err == nil {
		t.Fatal("Validate accepted invalid server URL")
	}
}

func TestLoadRejectsTrailingJSON(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.json")
	if err := os.WriteFile(path, []byte(`{} {}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(path); err == nil {
		t.Fatal("Load accepted more than one JSON value")
	}
}
