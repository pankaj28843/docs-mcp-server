package main

import (
	"fmt"
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

			reg, err := cfg.newRegistry()
			if err != nil {
				return err
			}

			t := reg.Get(args[0])
			if t == nil {
				if w.Format == output.FormatJSON {
					return w.JSON(map[string]any{
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
