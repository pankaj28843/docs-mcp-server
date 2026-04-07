package engine

import (
	"testing"
)

func TestSearchAllParallel(t *testing.T) {
	// Search across all CI fixture tenants in parallel.
	targets := []TenantTarget{
		{Codename: "webapi-ci", SegmentDB: fixtureSegmentPath(t, "webapi-ci")},
		{Codename: "gitdocs-ci", SegmentDB: fixtureSegmentPath(t, "gitdocs-ci")},
		{Codename: "localdocs-ci", SegmentDB: fixtureSegmentPath(t, "localdocs-ci")},
	}

	results, searched := SearchAll(targets, "routing", 5, 0)
	if searched != 3 {
		t.Errorf("searched = %d, want 3", searched)
	}
	if len(results) == 0 {
		t.Fatal("expected results from parallel search")
	}
	// Every result should have a tenant tag.
	for _, r := range results {
		if r.Tenant == "" {
			t.Errorf("result missing tenant: %s", r.URL)
		}
	}
}

func TestSearchAllSortedByScore(t *testing.T) {
	targets := []TenantTarget{
		{Codename: "webapi-ci", SegmentDB: fixtureSegmentPath(t, "webapi-ci")},
		{Codename: "gitdocs-ci", SegmentDB: fixtureSegmentPath(t, "gitdocs-ci")},
	}

	results, _ := SearchAll(targets, "configuration", 5, 0)
	for i := 1; i < len(results); i++ {
		if results[i].Score > results[i-1].Score {
			t.Errorf("results not sorted: [%d].Score=%f > [%d].Score=%f",
				i, results[i].Score, i-1, results[i-1].Score)
		}
	}
}

func TestSearchAllTotalLimit(t *testing.T) {
	targets := []TenantTarget{
		{Codename: "webapi-ci", SegmentDB: fixtureSegmentPath(t, "webapi-ci")},
		{Codename: "gitdocs-ci", SegmentDB: fixtureSegmentPath(t, "gitdocs-ci")},
	}

	results, _ := SearchAll(targets, "configuration", 5, 3)
	if len(results) > 3 {
		t.Errorf("total limit not respected: got %d results, want <= 3", len(results))
	}
}

func TestSearchAllEmptyQuery(t *testing.T) {
	targets := []TenantTarget{
		{Codename: "webapi-ci", SegmentDB: fixtureSegmentPath(t, "webapi-ci")},
	}
	results, searched := SearchAll(targets, "", 5, 0)
	if len(results) != 0 || searched != 0 {
		t.Errorf("empty query should return no results, got %d results, %d searched", len(results), searched)
	}
}

func TestSearchAllBoostRanking(t *testing.T) {
	// Tenant with boost=1.0 should rank above tenant with boost=0.0,
	// even if they have similar raw BM25 scores.
	targets := []TenantTarget{
		{Codename: "webapi-ci", SegmentDB: fixtureSegmentPath(t, "webapi-ci"), Boost: 0.0},
		{Codename: "gitdocs-ci", SegmentDB: fixtureSegmentPath(t, "gitdocs-ci"), Boost: 1.0},
	}

	results, _ := SearchAll(targets, "configuration", 3, 0)
	if len(results) == 0 {
		t.Fatal("expected results")
	}
	// The boosted tenant should appear first.
	if results[0].Tenant != "gitdocs-ci" {
		t.Errorf("boosted tenant should rank first, got %s", results[0].Tenant)
	}
}

func TestSearchAllBadSegmentPath(t *testing.T) {
	targets := []TenantTarget{
		{Codename: "nonexistent", SegmentDB: "/nonexistent/path.db"},
		{Codename: "webapi-ci", SegmentDB: fixtureSegmentPath(t, "webapi-ci")},
	}

	results, searched := SearchAll(targets, "routing", 5, 0)
	if searched != 2 {
		t.Errorf("should search both targets, got %d", searched)
	}
	if len(results) == 0 {
		t.Fatal("should return results from valid tenant")
	}
	// All results should be from the valid tenant.
	for _, r := range results {
		if r.Tenant != "webapi-ci" {
			t.Errorf("unexpected tenant %s in results", r.Tenant)
		}
	}
}

func TestSearchAllNormalization(t *testing.T) {
	// With normalization, scores should be in a reasonable range
	// (not raw BM25 which can be 100+).
	targets := []TenantTarget{
		{Codename: "webapi-ci", SegmentDB: fixtureSegmentPath(t, "webapi-ci"), Boost: 1.0},
	}

	results, _ := SearchAll(targets, "routing", 5, 0)
	if len(results) == 0 {
		t.Fatal("expected results")
	}
	// With boost=1.0 and normalization, max score should be around 1.0 + 0.3 + 0.2 = 1.5
	// (boost=1.0 + norm=0.3*1.0 + raw_damped=0.2*~0.5)
	for _, r := range results {
		if r.Score > 2.0 {
			t.Errorf("score %f too high — normalization may not be working", r.Score)
		}
		if r.Score <= 0 {
			t.Errorf("score %f should be positive", r.Score)
		}
	}
}
