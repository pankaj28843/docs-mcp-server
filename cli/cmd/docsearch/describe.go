package main

import (
	"strings"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
	"github.com/spf13/cobra"
)

func describeCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "describe <codename>",
		Short: "Show detailed info about a specific tenant",
		Long: `Get detailed information about a specific documentation tenant.

Returns display name, description, document count, and URL prefixes.

Examples:
  docsearch describe django
  docsearch describe fastapi --json`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			cfg := configFromContext(cmd.Context())
			w := cfg.newWriter()
			defer w.Finish()

			reader, err := cfg.reader(cmd.Context())
			if err != nil {
				return err
			}
			response, err := reader.Describe(cmd.Context(), args[0])
			if err != nil {
				return backendFailure(err)
			}

			if w.Format == output.FormatJSON {
				return w.JSON(response)
			}

			w.Text("Codename:     %s\n", response.Codename)
			w.Text("Display Name: %s\n", response.DisplayName)
			w.Text("Description:  %s\n", response.Description)
			w.Text("Documents:    %d\n", response.DocCount)
			if len(response.URLPrefixes) > 0 {
				w.Text("URL Prefixes: %s\n", strings.Join(response.URLPrefixes, ", "))
			}
			w.Text("Provenance:   %s\n", compactProvenanceSummary(response.Provenance))
			return nil
		},
	}
}
