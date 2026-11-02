package main

import (
	"encoding/json"
	"os"
	"strings"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/tenant"
	"github.com/spf13/cobra"
)

type technology struct {
	Name            string   `json:"name"`
	Version         string   `json:"version"`
	VersionEvidence string   `json:"version_evidence"`
	Tenants         []string `json:"tenants"`
	Comparison      string   `json:"comparison"`
}
type mapping struct {
	Technology  technology         `json:"technology"`
	Tenant      string             `json:"tenant"`
	Status      string             `json:"status"`
	IndexStatus string             `json:"index_status"`
	Provenance  *tenant.Provenance `json:"provenance,omitempty"`
}

func mapCmd() *cobra.Command {
	return &cobra.Command{
		Use: "map <project.json>", Short: "Compare a curated project technology list with tenant evidence",
		Long: `Compare explicit technology-to-tenant associations with indexed evidence.
The JSON file contains a technologies array with name, version, version_evidence,
tenants and comparison (exact or unknown). Associations and comparison rules are
provided by the project audit; fuzzy matches are never treated as proof.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			data, err := os.ReadFile(args[0])
			if err != nil {
				return usageFailure("read project mapping: %s", err)
			}
			var input struct {
				Technologies []technology `json:"technologies"`
			}
			if err := json.Unmarshal(data, &input); err != nil || input.Technologies == nil {
				return usageFailure("project mapping must contain a technologies array")
			}
			for _, tech := range input.Technologies {
				if strings.TrimSpace(tech.Name) == "" || (tech.Comparison != "" && tech.Comparison != "exact" && tech.Comparison != "unknown") {
					return usageFailure("each technology needs a name and comparison exact or unknown")
				}
			}
			cfg := configFromContext(cmd.Context())
			w := cfg.newWriter()
			defer w.Finish()
			reader, err := cfg.reader(cmd.Context())
			if err != nil {
				return err
			}
			list, err := reader.List(cmd.Context())
			if err != nil {
				return backendFailure(err)
			}
			byName := make(map[string]output.TenantInfo, len(list.Tenants))
			for _, item := range list.Tenants {
				byName[item.Codename] = item
			}
			results := make([]mapping, 0)
			for _, tech := range input.Technologies {
				if len(tech.Tenants) == 0 {
					results = append(results, mapping{Technology: tech, Status: "missing", IndexStatus: "unknown"})
					continue
				}
				for _, name := range tech.Tenants {
					item, ok := byName[name]
					result := mapping{Technology: tech, Tenant: name, Status: "missing", IndexStatus: "unknown"}
					if ok {
						result.Status = "unknown"
						result.IndexStatus = indexStatus(item.Provenance)
						result.Provenance = &item.Provenance
						source := item.Provenance.IndexedSource
						if tech.Comparison == "exact" && tech.Version != "" && tech.VersionEvidence != "" && source != nil && source.VersionKind == "versioned" && source.Version != "" {
							result.Status = "mismatch"
							if tech.Version == source.Version {
								result.Status = "match"
							}
						}
					}
					results = append(results, result)
				}
			}
			if w.Format == output.FormatJSON {
				return w.JSON(struct {
					Mappings []mapping `json:"mappings"`
				}{results})
			}
			for _, result := range results {
				w.Text("%s -> %s: version %s; index %s\n", result.Technology.Name, result.Tenant, result.Status, result.IndexStatus)
			}
			return nil
		},
	}
}
