package main

import (
	"fmt"

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
