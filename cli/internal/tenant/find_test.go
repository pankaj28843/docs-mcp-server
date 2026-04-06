package tenant

import "testing"

func TestLevenshtein(t *testing.T) {
	cases := []struct {
		a, b string
		max  int
		want int
	}{
		{"django", "django", 2, 0},
		{"djano", "django", 2, 1},
		{"react", "react", 2, 0},
		{"reac", "react", 2, 1},
		{"", "abc", 2, 3},
		{"abc", "", 2, 3},
	}
	for _, tc := range cases {
		got := levenshtein(tc.a, tc.b, tc.max)
		if got != tc.want {
			t.Errorf("levenshtein(%q, %q, %d) = %d, want %d", tc.a, tc.b, tc.max, got, tc.want)
		}
	}
}

func TestScoreTenantMatch(t *testing.T) {
	tenant := &Tenant{
		Codename:    "django",
		DisplayName: "Django",
		Description: "Official Django docs",
		URLPrefixes: []string{"https://docs.djangoproject.com"},
	}

	// Exact match on codename should score high
	score := scoreTenantMatch(tenant, "django", []string{"django"})
	if score < 0.5 {
		t.Errorf("exact codename match score too low: %f", score)
	}

	// Fuzzy match should still score
	score = scoreTenantMatch(tenant, "djano", []string{"djano"})
	if score < 0.1 {
		t.Errorf("fuzzy match score too low: %f", score)
	}

	// Unrelated query should score near zero
	score = scoreTenantMatch(tenant, "kubernetes", []string{"kubernetes"})
	if score > 0.1 {
		t.Errorf("unrelated query score too high: %f", score)
	}
}
