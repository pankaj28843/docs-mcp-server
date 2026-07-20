package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
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
	Out        io.Writer
	Err        io.Writer
}

type contextKey struct{}

func configFromContext(ctx context.Context) *appConfig {
	return ctx.Value(contextKey{}).(*appConfig)
}

func (c *appConfig) newRegistry() (*tenant.Registry, error) {
	registry, err := tenant.NewRegistry(c.DataDir, c.ConfigPath)
	if err != nil {
		return nil, failureWithCause(
			exitStorage,
			"storage",
			"data_root_unavailable",
			fmt.Sprintf("documentation data root is unavailable: %s", c.DataDir),
			err,
			"set --data-dir or TECHDOCS_DATA_DIR to a readable mcp-data directory",
		)
	}
	return registry, nil
}

func (c *appConfig) newWriter() *output.Writer {
	return output.NewWriter(c.Out, c.Err, c.JSONOutput, c.Timing)
}

func main() {
	os.Exit(execute(os.Args[1:], os.Stdout, os.Stderr))
}

type cliApp struct {
	root       *cobra.Command
	jsonOutput *bool
	out        io.Writer
	err        io.Writer
}

func newCLI(out, errOut io.Writer) *cliApp {
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
  docsearch search-all "middleware" --json          Best first move: search every tenant in parallel
  docsearch search django,fastapi "middleware"       Search selected tenants together
  docsearch search django "middleware" --json        Deep search inside one tenant
  docsearch fetch django "https://docs.../..."       Fetch full page content
  docsearch find django                              Find tenants by topic
  docsearch list                                     List all tenants

Research pattern:
  Run several searches at once with different phrases, tenants, or scopes.
  Compare the top hits, then narrow with selected tenants and sharper queries.

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
				Out:        out,
				Err:        errOut,
			}
			cmd.SetContext(context.WithValue(cmd.Context(), contextKey{}, cfg))
			return nil
		},
	}
	root.SetOut(out)
	root.SetErr(errOut)
	root.SetFlagErrorFunc(func(_ *cobra.Command, err error) error {
		return usageFailure("%s", err)
	})

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

	return &cliApp{root: root, jsonOutput: &jsonOutput, out: out, err: errOut}
}

func execute(args []string, out, errOut io.Writer) int {
	app := newCLI(out, errOut)
	app.root.SetArgs(args)
	if err := app.root.Execute(); err != nil {
		classified := classifyFailure(err)
		if *app.jsonOutput {
			if encodeErr := json.NewEncoder(app.out).Encode(errorResponse{Error: classified.detail}); encodeErr != nil {
				fmt.Fprintf(app.err, "Error: write JSON failure: %s\n", encodeErr)
				return exitInternal
			}
		} else {
			fmt.Fprintf(app.err, "Error: %s\n", classified.detail.Message)
		}
		return classified.exitCode
	}
	return exitOK
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
