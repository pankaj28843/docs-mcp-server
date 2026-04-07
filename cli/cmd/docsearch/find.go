package main

import (
	"fmt"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/tenant"
	"github.com/spf13/cobra"
)

func findCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "find <query>",
		Short: "Find tenants matching a topic (fuzzy search)",
		Long: `Find documentation tenants matching a topic using fuzzy search.

Searches across tenant codenames, display names, descriptions, and URLs.
Supports typo tolerance (e.g., 'djano' finds 'django').

Examples:
  docsearch find django
  docsearch find "machine learning"
  docsearch find react --json`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg := configFromContext(cmd.Context())
			w := cfg.newWriter()
			defer w.Finish()

			reg, err := cfg.newRegistry()
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
