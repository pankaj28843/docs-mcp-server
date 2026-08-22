package main

import (
	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
	"github.com/spf13/cobra"
)

func listCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List all available documentation tenants",
		Long: `List ALL available documentation sources (tenants).

Returns count and array of tenants with codename, description, and document count.

Examples:
  docsearch list
  docsearch list --json`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg := configFromContext(cmd.Context())
			w := cfg.newWriter()
			defer w.Finish()

			reader, err := cfg.reader(cmd.Context())
			if err != nil {
				return err
			}
			response, err := reader.List(cmd.Context())
			if err != nil {
				return backendFailure(err)
			}

			if w.Format == output.FormatJSON {
				return w.JSON(response)
			}

			w.Text("%d documentation sources:\n\n", response.Count)
			for _, t := range response.Tenants {
				w.Text("  %-35s %4d docs  %s\n", t.Codename, t.DocCount, compactProvenanceSummary(t.Provenance))
			}
			return nil
		},
	}
}
