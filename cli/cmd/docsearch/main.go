package main

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/tenant"
	"github.com/spf13/cobra"
)

var (
	dataDir    string
	jsonOutput bool
	timing     bool
	version    = "dev"
)

func main() {
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
	}

	root.PersistentFlags().StringVar(&dataDir, "data-dir", "", "Path to mcp-data directory (default: ./mcp-data or $TECHDOCS_DATA_DIR)")
	root.PersistentFlags().BoolVar(&jsonOutput, "json", false, "Output as JSON (machine-readable)")
	root.PersistentFlags().BoolVar(&timing, "timing", false, "Show execution time on stderr")
	root.Version = version

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

func resolveDataDir() string {
	if dataDir != "" {
		return dataDir
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

func resolveConfigPath() string {
	if env := os.Getenv("TECHDOCS_DEPLOYMENT_CONFIG"); env != "" {
		return env
	}
	// Walk up from data dir looking for deployment.json.
	dir, _ := filepath.Abs(resolveDataDir())
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

func getRegistry() (*tenant.Registry, error) {
	return tenant.NewRegistry(resolveDataDir(), resolveConfigPath())
}

func getWriter() *output.Writer {
	return output.New(jsonOutput, timing)
}
