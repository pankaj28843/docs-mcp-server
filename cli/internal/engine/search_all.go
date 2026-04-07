package engine

import (
	"sort"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/snippet"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/storage"
)

// TenantTarget identifies a tenant to search (avoids importing tenant package).
type TenantTarget struct {
	Codename  string
	SegmentDB string
}

// MultiResult is a search hit tagged with its source tenant.
type MultiResult struct {
	Tenant  string
	URL     string
	Title   string
	Snippet string
	Score   float64
}

// SearchAll searches multiple tenants in parallel using one goroutine per tenant.
// perTenantMax controls how many results to keep per tenant.
// totalMax caps the total merged results returned (0 = unlimited).
func SearchAll(targets []TenantTarget, query string, perTenantMax, totalMax int) ([]MultiResult, int) {
	if perTenantMax <= 0 {
		perTenantMax = 3
	}
	if perTenantMax > 100 {
		perTenantMax = 100
	}

	terms := UniqueTerms(AnalyzeToStrings(query))
	if len(terms) == 0 {
		return nil, 0
	}

	type tenantResult struct {
		tenant  string
		results []SearchResult
	}

	ch := make(chan tenantResult, len(targets))

	for _, t := range targets {
		go func(codename, dbPath string) {
			seg, err := storage.OpenSegment(dbPath)
			if err != nil {
				ch <- tenantResult{codename, nil}
				return
			}
			defer seg.Close()

			hits, err := SearchSegment(seg, query, perTenantMax)
			if err != nil {
				ch <- tenantResult{codename, nil}
				return
			}
			ch <- tenantResult{codename, hits}
		}(t.Codename, t.SegmentDB)
	}

	// Collect results from all goroutines.
	var all []MultiResult
	searched := 0
	for range targets {
		r := <-ch
		searched++
		for _, hit := range r.results {
			snip := snippet.Build(hit.Body, terms, 200)
			all = append(all, MultiResult{
				Tenant:  r.tenant,
				URL:     hit.URL,
				Title:   hit.Title,
				Snippet: snip,
				Score:   hit.Score,
			})
		}
	}

	// Sort by score descending.
	sort.Slice(all, func(i, j int) bool { return all[i].Score > all[j].Score })

	if totalMax > 0 && len(all) > totalMax {
		all = all[:totalMax]
	}

	return all, searched
}
