package tenant

import (
	"sort"
	"strings"
)

// ScoredTenant is a tenant with a relevance score.
type ScoredTenant struct {
	*Tenant
	Score float64
}

// FindTenants returns tenants matching query, sorted by relevance.
func FindTenants(registry *Registry, query string, maxResults int) []ScoredTenant {
	query = strings.ToLower(strings.TrimSpace(query))
	if query == "" {
		return nil
	}
	queryTerms := strings.Fields(query)

	var scored []ScoredTenant
	for _, t := range registry.List() {
		score := scoreTenantMatch(t, query, queryTerms)
		if score > 0.1 {
			scored = append(scored, ScoredTenant{Tenant: t, Score: score})
		}
	}

	sort.Slice(scored, func(i, j int) bool {
		return scored[i].Score > scored[j].Score
	})

	if maxResults > 0 && len(scored) > maxResults {
		scored = scored[:maxResults]
	}
	return scored
}

func scoreTenantMatch(t *Tenant, query string, queryTerms []string) float64 {
	type field struct {
		text   string
		weight float64
	}

	fields := []field{
		{strings.ToLower(t.Codename), 3.0},
		{strings.ToLower(t.DisplayName), 2.5},
		{strings.ToLower(t.Description), 1.5},
	}
	for _, url := range t.URLPrefixes {
		fields = append(fields, field{strings.ToLower(url), 1.0})
	}

	var bestScore float64

	for _, f := range fields {
		// Exact substring match
		if strings.Contains(f.text, query) {
			score := 1.0 * f.weight
			if score > bestScore {
				bestScore = score
			}
			continue
		}

		// Whole word match
		for _, word := range strings.Fields(f.text) {
			if query == word {
				score := 0.95 * f.weight
				if score > bestScore {
					bestScore = score
				}
				break
			}
		}

		// Term-by-term matching
		var termScores []float64
		for _, term := range queryTerms {
			if strings.Contains(f.text, term) {
				termScores = append(termScores, 0.8)
			} else {
				// Fuzzy match
				bestFuzzy := 0.0
				words := strings.FieldsFunc(f.text, func(r rune) bool {
					return r == '-' || r == '_' || r == ' ' || r == '/'
				})
				for _, word := range words {
					if len(term) >= 3 && len(word) >= 3 {
						d := levenshtein(term, word, 2)
						if d <= 2 {
							fuzzy := 0.7 - float64(d)*0.2
							if fuzzy > bestFuzzy {
								bestFuzzy = fuzzy
							}
						}
					}
				}
				termScores = append(termScores, bestFuzzy)
			}
		}

		if len(termScores) > 0 {
			sum := 0.0
			for _, s := range termScores {
				sum += s
			}
			avg := sum / float64(len(termScores))
			score := avg * f.weight
			if score > bestScore {
				bestScore = score
			}
		}
	}

	if bestScore > 1.0 {
		bestScore = 1.0
	}
	return bestScore
}

// levenshtein computes edit distance with early termination.
func levenshtein(a, b string, maxDist int) int {
	if len(a) == 0 {
		return len(b)
	}
	if len(b) == 0 {
		return len(a)
	}
	if abs(len(a)-len(b)) > maxDist {
		return maxDist + 1
	}

	prev := make([]int, len(b)+1)
	curr := make([]int, len(b)+1)
	for j := range prev {
		prev[j] = j
	}

	for i := 1; i <= len(a); i++ {
		curr[0] = i
		minVal := curr[0]
		for j := 1; j <= len(b); j++ {
			cost := 1
			if a[i-1] == b[j-1] {
				cost = 0
			}
			curr[j] = min3(prev[j]+1, curr[j-1]+1, prev[j-1]+cost)
			if curr[j] < minVal {
				minVal = curr[j]
			}
		}
		if minVal > maxDist {
			return maxDist + 1
		}
		prev, curr = curr, prev
	}
	return prev[len(b)]
}

func abs(x int) int {
	if x < 0 {
		return -x
	}
	return x
}

func min3(a, b, c int) int {
	if a < b {
		if a < c {
			return a
		}
		return c
	}
	if b < c {
		return b
	}
	return c
}
