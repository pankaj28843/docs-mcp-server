package main

import (
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/engine"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/snippet"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/storage"
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

Search documentation from 100+ sources instantly. Reads pre-built
BM25 indexes from mcp-data/ with <10ms latency.

Workflow:
  docsearch list                                    List all tenants
  docsearch find django                             Find tenants by topic
  docsearch search django "middleware"              Search within a tenant
  docsearch fetch django "https://docs.../..."      Fetch full page content`,
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

func getRegistry() (*tenant.Registry, error) {
	return tenant.NewRegistry(resolveDataDir())
}

func getWriter() *output.Writer {
	return output.New(jsonOutput, timing)
}

func listCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List all available documentation tenants",
		Long: `List ALL available documentation sources (tenants).

Returns count and array of tenants with codename, description, and document count.

Examples:
  td list
  td list --json`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			w := getWriter()
			defer w.Finish()

			reg, err := getRegistry()
			if err != nil {
				return err
			}

			tenants := reg.List()

			if w.Format == output.FormatJSON {
				resp := output.ListResponse{Count: len(tenants)}
				for _, t := range tenants {
					resp.Tenants = append(resp.Tenants, output.TenantInfo{
						Codename:    t.Codename,
						Description: fmt.Sprintf("%s - %s", t.DisplayName, t.Description),
						DocCount:    t.DocCount,
					})
				}
				return w.JSON(resp)
			}

			w.Text("%d documentation sources:\n\n", len(tenants))
			for _, t := range tenants {
				w.Text("  %-35s %4d docs\n", t.Codename, t.DocCount)
			}
			return nil
		},
	}
}

func findCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "find <query>",
		Short: "Find tenants matching a topic (fuzzy search)",
		Long: `Find documentation tenants matching a topic using fuzzy search.

Searches across tenant codenames, display names, descriptions, and URLs.
Supports typo tolerance (e.g., 'djano' finds 'django').

Examples:
  td find django
  td find "machine learning"
  td find react --json`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			w := getWriter()
			defer w.Finish()

			reg, err := getRegistry()
			if err != nil {
				return err
			}

			results := tenant.FindTenants(reg, args[0], 10)

			if w.Format == output.FormatJSON {
				resp := output.FindResponse{Query: args[0], Count: len(results)}
				for _, r := range results {
					resp.Tenants = append(resp.Tenants, output.TenantInfo{
						Codename:    r.Codename,
						Description: fmt.Sprintf("%s - %s", r.DisplayName, r.Description),
						DocCount:    r.DocCount,
					})
				}
				return w.JSON(resp)
			}

			if len(results) == 0 {
				w.Text("No tenants found matching %q\n", args[0])
				return nil
			}
			w.Text("Found %d matching tenants:\n\n", len(results))
			for _, r := range results {
				w.Text("  %-35s %4d docs\n", r.Codename, r.DocCount)
			}
			return nil
		},
	}
}

func describeCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "describe <codename>",
		Short: "Show detailed info about a specific tenant",
		Long: `Get detailed information about a specific documentation tenant.

Returns display name, description, document count, and URL prefixes.

Examples:
  td describe django
  td describe fastapi --json`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			w := getWriter()
			defer w.Finish()

			reg, err := getRegistry()
			if err != nil {
				return err
			}

			t := reg.Get(args[0])
			if t == nil {
				if w.Format == output.FormatJSON {
					return w.JSON(map[string]interface{}{
						"error":            fmt.Sprintf("Tenant '%s' not found", args[0]),
						"available_tenants": strings.Join(reg.Codenames(), ", "),
					})
				}
				return fmt.Errorf("tenant '%s' not found. Available: %s", args[0], strings.Join(reg.Codenames(), ", "))
			}

			if w.Format == output.FormatJSON {
				return w.JSON(output.DescribeResponse{
					Codename:    t.Codename,
					DisplayName: t.DisplayName,
					Description: t.Description,
					DocCount:    t.DocCount,
					URLPrefixes: t.URLPrefixes,
				})
			}

			w.Text("Codename:     %s\n", t.Codename)
			w.Text("Display Name: %s\n", t.DisplayName)
			w.Text("Description:  %s\n", t.Description)
			w.Text("Documents:    %d\n", t.DocCount)
			if len(t.URLPrefixes) > 0 {
				w.Text("URL Prefixes: %s\n", strings.Join(t.URLPrefixes, ", "))
			}
			return nil
		},
	}
}

func searchCmd() *cobra.Command {
	var size int

	cmd := &cobra.Command{
		Use:   "search <tenant> <query>",
		Short: "Search documentation within a tenant (BM25)",
		Long: `Search documentation within a specific tenant using BM25 ranking.

Returns ranked results with URL, title, and highlighted snippet.

The tenant must be an exact codename from 'docsearch list' or 'docsearch find'.

Examples:
  docsearch search django "select_related prefetch_related"
  docsearch search react "useEffect cleanup"
  docsearch search fastapi "dependency injection" --size 5
  docsearch search django middleware --json`,
		Args: cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			w := getWriter()
			defer w.Finish()

			reg, err := getRegistry()
			if err != nil {
				return err
			}

			tenantCodename := args[0]
			query := args[1]

			t := reg.Get(tenantCodename)
			if t == nil {
				errMsg := fmt.Sprintf("Tenant '%s' not found. Available: %s", tenantCodename, strings.Join(reg.Codenames(), ", "))
				if w.Format == output.FormatJSON {
					return w.JSON(output.SearchResponse{Error: errMsg, Query: query})
				}
				return fmt.Errorf("%s", errMsg)
			}

			if t.SegmentDB == "" {
				errMsg := fmt.Sprintf("No search index available for '%s'", tenantCodename)
				if w.Format == output.FormatJSON {
					return w.JSON(output.SearchResponse{Error: errMsg, Query: query})
				}
				return fmt.Errorf("%s", errMsg)
			}

			// Open segment and search
			seg, err := storage.OpenSegment(t.SegmentDB)
			if err != nil {
				return fmt.Errorf("open index: %w", err)
			}
			defer seg.Close()

			searchResults, err := engine.SearchSegment(seg, query, size)
			if err != nil {
				return err
			}

			// Convert to output format with snippets
			terms := engine.AnalyzeToStrings(query)
			outResults := make([]output.SearchResult, 0, len(searchResults))
			for _, r := range searchResults {
				snippetText := snippet.Build(r.Body, terms, 200)
				outResults = append(outResults, output.SearchResult{
					URL:     r.URL,
					Title:   r.Title,
					Snippet: snippetText,
					Score:   r.Score,
				})
			}

			w.PrintSearchResults(outResults, query)
			return nil
		},
	}

	cmd.Flags().IntVar(&size, "size", 10, "Number of results to return (max: 100)")
	return cmd
}

func fetchCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "fetch <tenant> <url>",
		Short: "Fetch full page content by URL",
		Long: `Fetch the full content of a documentation page by URL.

Use this after 'docsearch search' to read the actual documentation content.
The URL should be from search results.

Examples:
  docsearch fetch django "https://docs.djangoproject.com/en/5.2/topics/db/queries/"
  docsearch fetch react "https://react.dev/reference/react/useEffect" --json`,
		Args: cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			w := getWriter()
			defer w.Finish()

			reg, err := getRegistry()
			if err != nil {
				return err
			}

			tenantCodename := args[0]
			uri := args[1]

			t := reg.Get(tenantCodename)
			if t == nil {
				errMsg := fmt.Sprintf("Tenant '%s' not found. Available: %s", tenantCodename, strings.Join(reg.Codenames(), ", "))
				if w.Format == output.FormatJSON {
					return w.JSON(output.FetchResponse{URL: uri, Error: errMsg})
				}
				return fmt.Errorf("%s", errMsg)
			}

			// Try to fetch from disk
			content, title, err := fetchFromDisk(t, uri)
			if err != nil {
				errMsg := fmt.Sprintf("Document not found: %s", err)
				if w.Format == output.FormatJSON {
					return w.JSON(output.FetchResponse{URL: uri, Error: errMsg})
				}
				return fmt.Errorf("%s", errMsg)
			}

			if w.Format == output.FormatJSON {
				return w.JSON(output.FetchResponse{
					URL:     uri,
					Title:   title,
					Content: content,
				})
			}

			if title != "" {
				w.Text("# %s\n\n", title)
			}
			w.Text("%s\n", content)
			return nil
		},
	}
}

func fetchFromDisk(t *tenant.Tenant, uri string) (content, title string, err error) {
	docsRoot := t.DataDir

	// Try path-based lookup: {docs_root}/{netloc}/{url_path}.md
	parsed, parseErr := url.Parse(uri)
	if parseErr == nil && parsed.Host != "" {
		urlPath := strings.TrimRight(parsed.Path, "/")
		mdPath := filepath.Join(docsRoot, parsed.Host, urlPath+".md")
		if data, readErr := os.ReadFile(mdPath); readErr == nil {
			content := string(data)
			title := extractTitle(content, mdPath)
			return content, title, nil
		}

		// Try without .md extension (path might already include it)
		mdPath2 := filepath.Join(docsRoot, parsed.Host, urlPath)
		if data, readErr := os.ReadFile(mdPath2); readErr == nil {
			content := string(data)
			title := extractTitle(content, mdPath2)
			return content, title, nil
		}
	}

	// Try looking up in segment database for path hint
	if t.SegmentDB != "" {
		seg, segErr := storage.OpenSegment(t.SegmentDB)
		if segErr == nil {
			defer seg.Close()
			doc, docErr := seg.GetDocumentByURL(uri)
			if docErr == nil && doc != nil {
				// Return body from index if available
				if doc.Body != "" {
					return doc.Body, doc.Title, nil
				}
				// Try path hint
				if doc.Path != "" {
					path := doc.Path
					if !filepath.IsAbs(path) {
						path = filepath.Join(docsRoot, path)
					}
					if data, readErr := os.ReadFile(path); readErr == nil {
						return string(data), doc.Title, nil
					}
				}
			}
		}
	}

	return "", "", fmt.Errorf("document not found in local cache for %s", uri)
}

func extractTitle(content, filePath string) string {
	for _, line := range strings.SplitN(content, "\n", 10) {
		if strings.HasPrefix(line, "# ") {
			return strings.TrimSpace(line[2:])
		}
	}
	return filepath.Base(filePath)
}
