package main

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/tenant"
	"github.com/spf13/cobra"
)

var (
	version   = "dev"
	buildTime = "unknown"
	commit    = "unknown"
)

// appConfig holds resolved CLI configuration, eliminating package-level state.
// Created once in PersistentPreRunE and passed to commands via context.
type appConfig struct {
	DataDir    string
	ConfigPath string
	JSONOutput bool
	Timing     bool
}

type contextKey struct{}

func configFromContext(ctx context.Context) *appConfig {
	return ctx.Value(contextKey{}).(*appConfig)
}

func (c *appConfig) newRegistry() (*tenant.Registry, error) {
	return tenant.NewRegistry(c.DataDir, c.ConfigPath)
}

func (c *appConfig) newWriter() *output.Writer {
	return output.New(c.JSONOutput, c.Timing)
}

func main() {
	var rawDataDir string
	var jsonOutput bool
	var timing bool

	root := &cobra.Command{
		Use:   "docsearch",
		Short: "Fast documentation search across 100+ sources",
		Long: `docsearch - Documentation Search CLI

Search documentation from 100+ sources instantly using pre-built
BM25 indexes. Designed for agent and CLI workflows.

Workflow:
  docsearch search-all "middleware" --json          Search ALL tenants in parallel
  docsearch search django "middleware" --json        Search one tenant (deep)
  docsearch search django,fastapi "middleware"       Search multiple tenants
  docsearch fetch django "https://docs.../..."       Fetch full page content
  docsearch find django                              Find tenants by topic
  docsearch list                                     List all tenants

Environment:
  TECHDOCS_DATA_DIR              Path to mcp-data directory (or use --data-dir)
  TECHDOCS_DEPLOYMENT_CONFIG     Path to deployment.json for rich tenant metadata`,
		SilenceUsage:  true,
		SilenceErrors: true,
		PersistentPreRunE: func(cmd *cobra.Command, args []string) error {
			dataDir := resolveDataDir(rawDataDir)
			cfg := &appConfig{
				DataDir:    dataDir,
				ConfigPath: resolveConfigPath(dataDir),
				JSONOutput: jsonOutput,
				Timing:     timing,
			}
			cmd.SetContext(context.WithValue(cmd.Context(), contextKey{}, cfg))
			return nil
		},
	}

	root.PersistentFlags().StringVar(&rawDataDir, "data-dir", "", "Path to mcp-data directory (default: ./mcp-data or $TECHDOCS_DATA_DIR)")
	root.PersistentFlags().BoolVar(&jsonOutput, "json", false, "Output as JSON (machine-readable)")
	root.PersistentFlags().BoolVar(&timing, "timing", false, "Show execution time on stderr")
	root.Version = formatVersion()
	root.SetVersionTemplate("{{.Version}}\n")

	root.AddCommand(listCmd())
	root.AddCommand(findCmd())
	root.AddCommand(describeCmd())
	root.AddCommand(searchCmd())
	root.AddCommand(searchAllCmd())
	root.AddCommand(fetchCmd())

	if err := root.Execute(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %s\n", err)
		os.Exit(1)
	}
}

func resolveDataDir(flagValue string) string {
	if flagValue != "" {
		return flagValue
	}
	if env := os.Getenv("TECHDOCS_DATA_DIR"); env != "" {
		return env
	}
	// Walk up from cwd looking for mcp-data/
	dir, _ := os.Getwd()
	for {
		candidate := filepath.Join(dir, "mcp-data")
		if info, err := os.Stat(candidate); err == nil && info.IsDir() {
			return candidate
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return "mcp-data"
}

func formatVersion() string {
	if version == "dev" {
		return "dev (no build info)"
	}
	return fmt.Sprintf("%s (built %s, commit %s)", version, buildTime, commit)
}

func resolveConfigPath(dataDir string) string {
	if env := os.Getenv("TECHDOCS_DEPLOYMENT_CONFIG"); env != "" {
		return env
	}
	// Walk up from data dir looking for deployment.json.
	dir, _ := filepath.Abs(dataDir)
	for {
		candidate := filepath.Join(dir, "deployment.json")
		if _, err := os.Stat(candidate); err == nil {
			return candidate
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return ""
}
