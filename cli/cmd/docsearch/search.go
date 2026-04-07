package main

import (
	"fmt"
	"strings"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/engine"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/snippet"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/storage"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/tenant"
	"github.com/spf13/cobra"
)

func searchCmd() *cobra.Command {
	var size int

	cmd := &cobra.Command{
		Use:   "search <tenant> <query>",
		Short: "Search documentation within a tenant (BM25)",
		Long: `Search documentation within a specific tenant using BM25 ranking.

Returns ranked results with URL, title, and highlighted snippet.
Supports comma-separated tenants for multi-source search:

  docsearch search django,fastapi "middleware"

Examples:
  docsearch search django "select_related prefetch_related"
  docsearch search react "useEffect cleanup"
  docsearch search fastapi "dependency injection" --size 5
  docsearch search django,fastapi,celery "task queue" --json`,
		Args: cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			w := getWriter()
			defer w.Finish()

			reg, err := getRegistry()
			if err != nil {
				return err
			}

			query := args[1]
			codenames := strings.Split(args[0], ",")

			// Multi-tenant: fan out in parallel via SearchAll
			if len(codenames) > 1 {
				return runMultiSearch(w, reg, codenames, query, size, 0)
			}

			// Single tenant: direct segment search (fastest path)
			tenantCodename := codenames[0]
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

			seg, err := storage.OpenSegment(t.SegmentDB)
			if err != nil {
				return fmt.Errorf("open index: %w", err)
			}
			defer seg.Close()

			searchResults, err := engine.SearchSegment(seg, query, size)
			if err != nil {
				return err
			}

			terms := engine.AnalyzeToStrings(query)
			outResults := make([]output.SearchResult, 0, len(searchResults))
			for _, r := range searchResults {
				snippetText := snippet.Build(r.Body, terms, 200)
				outResults = append(outResults, output.SearchResult{
					Tenant:  tenantCodename,
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

func searchAllCmd() *cobra.Command {
	var size int
	var total int

	cmd := &cobra.Command{
		Use:   "search-all <query>",
		Short: "Search ALL tenants in parallel (goroutine per tenant)",
		Long: `Search across ALL documentation tenants simultaneously.

Launches one goroutine per tenant for parallel BM25 search.
Results are merged and sorted by score. Handles 100+ tenants easily.

Examples:
  docsearch search-all "dependency injection"
  docsearch search-all "middleware" --json
  docsearch search-all "websocket" --size 5 --total 50`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			w := getWriter()
			defer w.Finish()

			reg, err := getRegistry()
			if err != nil {
				return err
			}

			codenames := reg.Codenames()
			if len(codenames) == 0 {
				errMsg := "No tenants with search indexes found"
				if w.Format == output.FormatJSON {
					return w.JSON(output.SearchResponse{Error: errMsg, Query: args[0]})
				}
				return fmt.Errorf("%s", errMsg)
			}

			return runMultiSearch(w, reg, codenames, args[0], size, total)
		},
	}

	cmd.Flags().IntVar(&size, "size", 5, "Results per tenant (max: 100)")
	cmd.Flags().IntVar(&total, "total", 20, "Max total results returned (0 = unlimited)")
	return cmd
}

// runMultiSearch is the shared path for comma-separated search and search-all.
// It resolves codenames to targets and delegates to engine.SearchAll.
func runMultiSearch(w *output.Writer, reg *tenant.Registry, codenames []string, query string, perTenantMax, totalMax int) error {
	var targets []engine.TenantTarget
	var missing []string
	for _, c := range codenames {
		c = strings.TrimSpace(c)
		t := reg.Get(c)
		if t == nil {
			missing = append(missing, c)
			continue
		}
		if t.SegmentDB != "" {
			targets = append(targets, engine.TenantTarget{
				Codename:  c,
				SegmentDB: t.SegmentDB,
				Boost:     tenant.ScoreTenantMatch(t, query),
			})
		}
	}
	if len(targets) == 0 {
		errMsg := fmt.Sprintf("No valid tenants found. Missing: %s. Available: %s", strings.Join(missing, ", "), strings.Join(reg.Codenames(), ", "))
		if w.Format == output.FormatJSON {
			return w.JSON(output.SearchResponse{Error: errMsg, Query: query})
		}
		return fmt.Errorf("%s", errMsg)
	}

	results, searched := engine.SearchAll(targets, query, perTenantMax, totalMax)
	outResults := make([]output.SearchResult, 0, len(results))
	for _, r := range results {
		outResults = append(outResults, output.SearchResult{
			Tenant:  r.Tenant,
			URL:     r.URL,
			Title:   r.Title,
			Snippet: r.Snippet,
			Score:   r.Score,
		})
	}

	if w.Format == output.FormatJSON {
		return w.JSON(output.SearchResponse{
			Results:         outResults,
			Query:           query,
			TenantsSearched: searched,
		})
	}

	if searched > 1 {
		w.Text("Searched %d tenants for %q:\n\n", searched, query)
	}
	w.PrintSearchResults(outResults, query)
	return nil
}
