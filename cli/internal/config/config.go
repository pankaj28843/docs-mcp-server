// Package config loads the configuration shared by docsearch and docsearchd.
package config

import (
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

const (
	MaxCacheBytes          int64 = 500 << 20
	DefaultCacheMaxBytes   int64 = 64 << 20
	DefaultListen                = "127.0.0.1:42142"
	DefaultCacheTTLSeconds       = 30
)

// Config is the single configuration contract shared by daemon and CLI.
type Config struct {
	DataDir             string `json:"data_dir,omitempty"`
	DeploymentConfig    string `json:"deployment_config,omitempty"`
	ServerURL           string `json:"server_url,omitempty"`
	Mode                string `json:"mode,omitempty"`
	Listen              string `json:"listen"`
	CacheMaxBytes       int64  `json:"cache_max_bytes"`
	CacheTTLSeconds     int    `json:"cache_ttl_seconds"`
	SearchMaxConcurrent int    `json:"search_max_concurrent"`
}

func Defaults() Config {
	return Config{
		Mode:                "auto",
		Listen:              DefaultListen,
		CacheMaxBytes:       DefaultCacheMaxBytes,
		CacheTTLSeconds:     DefaultCacheTTLSeconds,
		SearchMaxConcurrent: 16,
	}
}

// Path returns an explicit path or the default XDG configuration path.
func Path(explicit string) (string, error) {
	if strings.TrimSpace(explicit) != "" {
		return filepath.Clean(explicit), nil
	}
	dir, err := os.UserConfigDir()
	if err != nil {
		return "", fmt.Errorf("resolve user config directory: %w", err)
	}
	return filepath.Join(dir, "docs-search", "config.json"), nil
}

// Load reads path over safe defaults. A missing file is a valid local-only
// configuration so existing CLI installations keep working.
func Load(path string) (Config, error) {
	cfg := Defaults()
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return cfg, nil
		}
		return Config{}, fmt.Errorf("read config %s: %w", path, err)
	}
	decoder := json.NewDecoder(strings.NewReader(string(data)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&cfg); err != nil {
		return Config{}, fmt.Errorf("decode config %s: %w", path, err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		if err == nil {
			return Config{}, fmt.Errorf("decode config %s: multiple JSON values", path)
		}
		return Config{}, fmt.Errorf("decode config %s: %w", path, err)
	}
	if err := cfg.Validate(); err != nil {
		return Config{}, fmt.Errorf("validate config %s: %w", path, err)
	}
	return cfg, nil
}

func (c Config) Validate() error {
	if c.CacheMaxBytes < 0 || c.CacheMaxBytes > MaxCacheBytes {
		return fmt.Errorf("cache_max_bytes must be between 0 and %d", MaxCacheBytes)
	}
	if c.CacheMaxBytes > 0 && c.CacheTTLSeconds <= 0 {
		return fmt.Errorf("cache_ttl_seconds must be greater than zero when caching is enabled")
	}
	if c.SearchMaxConcurrent < 1 {
		return fmt.Errorf("search_max_concurrent must be greater than zero")
	}
	if c.Listen == "" {
		return fmt.Errorf("listen must not be empty")
	}
	if _, _, err := net.SplitHostPort(c.Listen); err != nil {
		return fmt.Errorf("invalid listen address %q: %w", c.Listen, err)
	}
	if c.ServerURL != "" {
		u, err := url.Parse(c.ServerURL)
		if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
			return fmt.Errorf("server_url must be an absolute http or https URL")
		}
	}
	switch c.Mode {
	case "auto", "local", "remote":
	default:
		return fmt.Errorf("mode must be auto, local, or remote")
	}
	return nil
}
