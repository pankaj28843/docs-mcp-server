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

func TestContainsWholeWord(t *testing.T) {
	cases := []struct {
		haystack, needle string
		want             bool
	}{
		{"django middleware", "django", true},
		{"vitest config", "vite", false},     // "vite" is substring of "vitest", not whole word
		{"vite plugin config", "vite", true}, // "vite" is first word
		{"use vite for build", "vite", true}, // "vite" in middle
		{"react native navigation", "react", true},
		{"react native navigation", "native", true},
		{"react native navigation", "react-native", false}, // hyphenated not in query
		{"", "django", false},
		{"django", "django", true},
		{"vite", "vite", true},
		{"pre-vite-config", "vite", true}, // bounded by hyphens
	}
	for _, tc := range cases {
		got := containsWholeWord(tc.haystack, tc.needle)
		if got != tc.want {
			t.Errorf("containsWholeWord(%q, %q) = %v, want %v", tc.haystack, tc.needle, got, tc.want)
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

	// Exact match on codename should score 1.0+
	score := ScoreTenantMatch(tenant, "django")
	if score < 1.0 {
		t.Errorf("exact codename match score = %f, want >= 1.0", score)
	}

	// Fuzzy match should still score
	score = ScoreTenantMatch(tenant, "djano")
	if score < 0.1 {
		t.Errorf("fuzzy match score = %f, want > 0.1", score)
	}

	// Unrelated query should score zero
	score = ScoreTenantMatch(tenant, "kubernetes")
	if score > 0.1 {
		t.Errorf("unrelated query score = %f, want < 0.1", score)
	}
}

func TestScoreTenantMatchWholeWord(t *testing.T) {
	vite := &Tenant{Codename: "vite", DisplayName: "Vite Docs"}
	vitest := &Tenant{Codename: "vitest", DisplayName: "Vitest Docs"}

	viteScore := ScoreTenantMatch(vite, "vite plugin config")
	vitestScore := ScoreTenantMatch(vitest, "vite plugin config")

	if viteScore <= vitestScore {
		t.Errorf("vite (%f) should score higher than vitest (%f) for 'vite plugin config'",
			viteScore, vitestScore)
	}
	if viteScore < 1.0 {
		t.Errorf("vite should get whole-word boost >= 1.0, got %f", viteScore)
	}
}

func TestScoreTenantMatchMultiToken(t *testing.T) {
	react := &Tenant{Codename: "react", DisplayName: "React Docs"}
	reactNative := &Tenant{Codename: "react-native", DisplayName: "React Native Docs"}

	// "react native navigation" should favor react-native (2 tokens match) over react (1 token)
	rnScore := ScoreTenantMatch(reactNative, "react native navigation")
	rScore := ScoreTenantMatch(react, "react native navigation")

	if rnScore <= rScore {
		t.Errorf("react-native (%f) should score higher than react (%f) for 'react native navigation'",
			rnScore, rScore)
	}

	// "react useState hook" should favor react (whole word) over react-native (partial)
	rScore = ScoreTenantMatch(react, "react useState hook")
	rnScore = ScoreTenantMatch(reactNative, "react useState hook")

	if rScore <= rnScore {
		t.Errorf("react (%f) should score higher than react-native (%f) for 'react useState hook'",
			rScore, rnScore)
	}
}

func TestScoreTenantMatchPydanticFamily(t *testing.T) {
	pydantic := &Tenant{Codename: "pydantic", DisplayName: "Pydantic Docs"}
	pydanticAI := &Tenant{Codename: "pydantic-ai", DisplayName: "Pydantic AI Docs"}

	// "pydantic model validator" should favor pydantic over pydantic-ai
	pScore := ScoreTenantMatch(pydantic, "pydantic model validator")
	paScore := ScoreTenantMatch(pydanticAI, "pydantic model validator")
	if pScore <= paScore {
		t.Errorf("pydantic (%f) should beat pydantic-ai (%f) for 'pydantic model validator'",
			pScore, paScore)
	}

	// "pydantic ai agent" should favor pydantic-ai (both tokens match)
	paScore = ScoreTenantMatch(pydanticAI, "pydantic ai agent")
	pScore = ScoreTenantMatch(pydantic, "pydantic ai agent")
	if paScore <= pScore {
		t.Errorf("pydantic-ai (%f) should beat pydantic (%f) for 'pydantic ai agent'",
			paScore, pScore)
	}
}

func TestScoreTenantMatchNoMatch(t *testing.T) {
	sentry := &Tenant{
		Codename:    "sentry",
		DisplayName: "Sentry Docs",
		Description: "Documentation from https://docs.sentry.io",
		URLPrefixes: []string{"https://docs.sentry.io"},
	}

	// Sentry should get 0 for framework-specific queries
	for _, query := range []string{"django middleware", "fastapi dependency", "vite plugin"} {
		score := ScoreTenantMatch(sentry, query)
		if score > 0.1 {
			t.Errorf("sentry score for %q = %f, want < 0.1", query, score)
		}
	}
}

func TestTokenize(t *testing.T) {
	cases := []struct {
		input string
		want  []string
	}{
		{"pydantic-ai", []string{"pydantic", "ai"}},
		{"react-native", []string{"react", "native"}},
		{"django", []string{"django"}},
		{"Django REST Framework", []string{"django", "rest", "framework"}},
		{"auth.js", []string{"auth", "js"}},
	}
	for _, tc := range cases {
		got := tokenize(tc.input)
		if len(got) != len(tc.want) {
			t.Errorf("tokenize(%q) = %v, want %v", tc.input, got, tc.want)
			continue
		}
		for i := range got {
			if got[i] != tc.want[i] {
				t.Errorf("tokenize(%q)[%d] = %q, want %q", tc.input, i, got[i], tc.want[i])
			}
		}
	}
}
