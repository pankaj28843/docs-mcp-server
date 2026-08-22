package engine

import (
	"context"
	"runtime"
	"sort"
	"sync"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/snippet"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/storage"
)

// TenantTarget identifies a tenant to search.
// Boost is a 0.0-1.0 tenant relevance score (e.g., how well the tenant name
// matches the query). Results from boosted tenants are ranked higher.
type TenantTarget struct {
	Codename  string
	SegmentDB string
	Boost     float64
}

// MultiResult is a search hit tagged with its source tenant.
type MultiResult struct {
	Tenant  string
	URL     string
	Title   string
	Snippet string
	Score   float64
}

// SearchAll searches multiple tenants through a bounded worker pool.
// perTenantMax controls how many results to keep per tenant.
// totalMax caps the total merged results returned (0 = unlimited).
//
// Scoring uses per-tenant normalization to eliminate corpus-size bias:
//
//  1. Each tenant's BM25 scores are normalized by dividing by the tenant's
//     max score, producing values in (0, 1]. This makes a "best match" in
//     a small tenant equal to a "best match" in a large tenant.
//
//  2. A dampened raw BM25 component (score/(score+damping)) provides
//     cross-tenant differentiation for generic queries while compressing
//     the advantage that large corpora get from higher raw BM25.
//
//  3. The tenant relevance boost is added as an additive bonus, so a
//     matched tenant's results always outrank unmatched tenants.
func SearchAll(targets []TenantTarget, query string, perTenantMax, totalMax int) ([]MultiResult, int) {
	maxConcurrent := min(len(targets), max(1, runtime.GOMAXPROCS(0)*4))
	results, searched, _ := SearchAllContext(context.Background(), targets, query, perTenantMax, totalMax, maxConcurrent)
	return results, searched
}

// SearchAllContext searches targets with cancellation and bounded concurrency.
func SearchAllContext(ctx context.Context, targets []TenantTarget, query string, perTenantMax, totalMax, maxConcurrent int) ([]MultiResult, int, error) {
	if perTenantMax <= 0 {
		perTenantMax = 5
	}
	if perTenantMax > maxResultsCap {
		perTenantMax = maxResultsCap
	}

	terms := UniqueTerms(AnalyzeToStrings(query))
	if len(terms) == 0 {
		return nil, 0, nil
	}
	if maxConcurrent < 1 {
		maxConcurrent = 1
	}
	maxConcurrent = min(maxConcurrent, len(targets))

	type tenantResult struct {
		tenant  string
		boost   float64
		results []SearchResult
	}

	ch := make(chan tenantResult, maxConcurrent)
	jobs := make(chan TenantTarget)
	var workers sync.WaitGroup
	for range maxConcurrent {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for t := range jobs {
				if ctx.Err() != nil {
					return
				}
				codename, dbPath, boost := t.Codename, t.SegmentDB, t.Boost
				seg, err := storage.OpenSegment(dbPath)
				if err != nil {
					ch <- tenantResult{codename, boost, nil}
					continue
				}
				hits, err := SearchSegment(seg, query, perTenantMax)
				_ = seg.Close()
				if err != nil {
					ch <- tenantResult{codename, boost, nil}
					continue
				}
				ch <- tenantResult{codename, boost, hits}
			}
		}()
	}
	go func() {
		defer close(jobs)
		for _, target := range targets {
			select {
			case jobs <- target:
			case <-ctx.Done():
				return
			}
		}
	}()
	go func() {
		workers.Wait()
		close(ch)
	}()

	// Collect results from all goroutines, grouped by tenant.
	type pendingResult struct {
		tenant string
		boost  float64
		hit    SearchResult
		snip   string
	}
	var pending []pendingResult
	searched := 0

	for r := range ch {
		searched++
		if len(r.results) == 0 {
			continue
		}
		// Find max BM25 score within this tenant for normalization.
		maxScore := r.results[0].Score
		for _, hit := range r.results[1:] {
			if hit.Score > maxScore {
				maxScore = hit.Score
			}
		}
		if maxScore <= 0 {
			continue
		}
		for _, hit := range r.results {
			snip := snippet.Build(hit.Body, terms, 200)
			// Normalize BM25 within this tenant: best result → 1.0
			normalizedBM25 := hit.Score / maxScore
			// Dampened raw: compress large-corpus advantage via saturation
			rawComponent := hit.Score / (hit.Score + rawDamping)
			// Final = boost bonus + blended BM25
			finalScore := r.boost*tenantBoostWeight + normalizedBM25*normWeight + rawComponent*rawWeight
			pending = append(pending, pendingResult{
				tenant: r.tenant,
				boost:  r.boost,
				hit:    SearchResult{URL: hit.URL, Title: hit.Title, Body: hit.Body, Score: finalScore},
				snip:   snip,
			})
		}
	}

	// Build final results, sorted by normalized+boosted score.
	all := make([]MultiResult, 0, len(pending))
	for _, p := range pending {
		all = append(all, MultiResult{
			Tenant:  p.tenant,
			URL:     p.hit.URL,
			Title:   p.hit.Title,
			Snippet: p.snip,
			Score:   p.hit.Score,
		})
	}

	sort.Slice(all, func(i, j int) bool { return all[i].Score > all[j].Score })

	if totalMax > 0 && len(all) > totalMax {
		all = all[:totalMax]
	}

	return all, searched, ctx.Err()
}

const (
	// tenantBoostWeight: additive bonus for tenant name matches.
	// A perfect match (boost=1.0) adds 1.0 to the score, which dominates
	// the normalized BM25 component (max ~0.5) — matched tenant always wins.
	tenantBoostWeight = 1.0

	// normWeight: weight for per-tenant normalized BM25 (0-1 range).
	// Preserves within-tenant ordering.
	normWeight = 0.3

	// rawWeight: weight for dampened raw BM25 component.
	// Provides cross-tenant differentiation for generic queries
	// while dampening corpus-size advantage via saturation.
	rawWeight = 0.2

	// rawDamping: saturation point for raw BM25 scores.
	// score/(score+damping) maps raw BM25 to (0, 1).
	// At damping=100: BM25=100→0.5, BM25=200→0.67, BM25=50→0.33
	rawDamping = 100.0
)
