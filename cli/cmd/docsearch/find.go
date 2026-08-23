package main

import (
	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
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

			reader, err := cfg.reader(cmd.Context())
			if err != nil {
				return err
			}
			response, err := reader.Find(cmd.Context(), args[0])
			if err != nil {
				return backendFailure(err)
			}

			if w.Format == output.FormatJSON {
				return w.JSON(response)
			}

			if response.Count == 0 {
				w.Text("No tenants found matching %q\n", args[0])
				return nil
			}
			w.Text("Found %d matching tenants:\n\n", response.Count)
			for _, r := range response.Tenants {
				w.Text("  %-35s %4d docs\n", r.Codename, r.DocCount)
			}
			return nil
		},
	}
}
