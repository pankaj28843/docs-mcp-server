package engine

import "testing"

func TestStem(t *testing.T) {
	// These must match the Python _build_porter_stemmer output exactly
	cases := []struct{ input, want string }{
		{"middleware", "middleware"},
		{"queries", "queri"},
		{"models", "model"},
		{"running", "runn"},
		{"optimization", "optimize"},
		{"function", "function"},
		{"configured", "configur"},
		{"documentation", "documentate"},
		{"select_related", "select_relat"},
		{"dependencies", "dependenci"},
		{"injection", "injection"},
		{"authentication", "authenticate"},
		{"serializers", "serializer"},
		{"deployment", "deploy"},
		{"management", "manage"},
		{"performance", "performan"},
		{"instances", "instanc"},
		{"installed", "install"},
		{"enabled", "enabl"},
		{"settings", "setting"},
		{"", ""},
		{"a", "a"},
		{"go", "go"},
	}
	for _, tc := range cases {
		got := Stem(tc.input)
		if got != tc.want {
			t.Errorf("Stem(%q) = %q, want %q", tc.input, got, tc.want)
		}
	}
}

func TestAnalyze(t *testing.T) {
	tokens := AnalyzeToStrings("The Django middleware handles requests")
	// "the" is a stopword, should be removed
	// Remaining: django, middleware, handle, request
	if len(tokens) == 0 {
		t.Fatal("expected non-empty tokens")
	}
	found := false
	for _, tok := range tokens {
		if tok == "the" {
			t.Error("stopword 'the' should be removed")
		}
		if tok == "middleware" {
			found = true
		}
	}
	if !found {
		t.Errorf("expected 'middleware' in tokens, got %v", tokens)
	}
}

func BenchmarkStem(b *testing.B) {
	words := []string{"middleware", "optimization", "authentication", "configured", "dependencies"}
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		for _, w := range words {
			Stem(w)
		}
	}
}

func BenchmarkAnalyze(b *testing.B) {
	text := "The Django middleware handles HTTP requests and responses for authentication"
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		Analyze(text)
	}
}
