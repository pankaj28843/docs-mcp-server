package main

import (
	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
	"github.com/spf13/cobra"
)

func searchCmd() *cobra.Command {
	var size int

	cmd := &cobra.Command{
		Use:   "search <tenant> <query>",
		Short: "Search documentation within a tenant (BM25)",
		Long: `Search documentation within a specific tenant using BM25 ranking.

Returns ranked results with URL, title, and highlighted snippet.
Use comma-separated tenants to search multiple sources in parallel:

  docsearch search django,fastapi "middleware"

For broad questions, start with search-all. For focused questions, combine the
most relevant tenants in one search. When you need to explore many phrasings,
run several CLI searches in parallel and compare the strongest hits.

Examples:
  docsearch search django "select_related prefetch_related"
  docsearch search react "useEffect cleanup"
  docsearch search django,fastapi,celery "task queue" --json
  docsearch search anthropic-claude-docs,claude-code-docs "tool use" --size 8`,
		Args: cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			if size < 1 || size > 100 {
				return usageFailure("--size must be between 1 and 100")
			}
			cfg := configFromContext(cmd.Context())
			w := cfg.newWriter()
			defer w.Finish()

			reader, err := cfg.reader(cmd.Context())
			if err != nil {
				return err
			}
			response, err := reader.Search(cmd.Context(), args[0], args[1], size, 0)
			if err != nil {
				return backendFailure(err)
			}

			if w.Format == output.FormatJSON {
				return w.JSON(response)
			}
			if response.Provenance != nil {
				w.Text("Provenance: %s\n\n", compactProvenanceSummary(*response.Provenance))
			}
			if response.TenantsSearched > 1 {
				w.Text("Searched %d tenants for %q:\n\n", response.TenantsSearched, args[1])
			}
			w.PrintSearchResults(response.Results, args[1])
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

Best first move when you do not know which docs contain the answer. It searches
every tenant in parallel, merges hits by score, and keeps tenant labels on each
result so you can narrow follow-up searches.

If one phrase is too narrow, divide and conquer: run multiple search-all calls
at the same time with synonyms, API names, error text, and conceptual terms.

Examples:
  docsearch search-all "dependency injection"
  docsearch search-all "middleware" --json
  docsearch search-all "websocket" --size 5 --total 50`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if size < 1 || size > 100 {
				return usageFailure("--size must be between 1 and 100")
			}
			if total < 0 {
				return usageFailure("--total must be zero or greater")
			}
			cfg := configFromContext(cmd.Context())
			w := cfg.newWriter()
			defer w.Finish()

			reader, err := cfg.reader(cmd.Context())
			if err != nil {
				return err
			}
			response, err := reader.Search(cmd.Context(), "", args[0], size, total)
			if err != nil {
				return backendFailure(err)
			}
			if w.Format == output.FormatJSON {
				return w.JSON(response)
			}
			if response.TenantsSearched > 1 {
				w.Text("Searched %d tenants for %q:\n\n", response.TenantsSearched, args[0])
			}
			w.PrintSearchResults(response.Results, args[0])
			return nil
		},
	}

	cmd.Flags().IntVar(&size, "size", 5, "Results per tenant (max: 100)")
	cmd.Flags().IntVar(&total, "total", 20, "Max total results returned (0 = unlimited)")
	return cmd
}
