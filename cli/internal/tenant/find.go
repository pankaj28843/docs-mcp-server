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

// ScoreTenantMatch returns 0.0-1.0 indicating how well a query matches a tenant's metadata.
// Uses whole-word matching to avoid substring confusion (e.g., "vite" vs "vitest").
func ScoreTenantMatch(t *Tenant, query string) float64 {
	query = strings.ToLower(strings.TrimSpace(query))
	if query == "" {
		return 0
	}
	return scoreTenantMatch(t, query, strings.Fields(query))
}

// tokenize splits a codename or display name into searchable tokens.
// "pydantic-ai" → ["pydantic", "ai"]
// "django rest framework" → ["django", "rest", "framework"]
func tokenize(s string) []string {
	return strings.FieldsFunc(strings.ToLower(s), func(r rune) bool {
		return r == '-' || r == '_' || r == ' ' || r == '/' || r == '.'
	})
}

func scoreTenantMatch(t *Tenant, query string, queryTerms []string) float64 {
	codename := strings.ToLower(t.Codename)
	codenameTokens := tokenize(t.Codename)
	displayTokens := tokenize(t.DisplayName)

	var bestScore float64

	// --- Priority 1: Exact codename match (query IS the codename) ---
	// "django" query, "django" codename → 1.0
	if query == codename {
		return 1.0
	}

	// --- Priority 2: Match codename against query terms ---
	// Strategy: count how many codename tokens appear as whole words in the query.
	// More matched tokens = more specific match = higher score.
	//
	// "react native navigation" + codename "react-native" → 2 tokens match → 1.0
	// "react native navigation" + codename "react"         → 1 token match  → 0.9
	// "react useState hook"     + codename "react-native"  → 1/2 tokens     → 0.45
	// "vitest config"           + codename "vite"           → 0 (not whole word) → 0.0
	//
	// Multi-word codenames that fully match are MORE specific than single-word
	// ones, so they get a small bonus (matched token count as tiebreaker).
	matchedTokens := 0
	for _, ct := range codenameTokens {
		for _, qt := range queryTerms {
			if qt == ct {
				matchedTokens++
				break
			}
		}
	}

	if matchedTokens > 0 {
		ratio := float64(matchedTokens) / float64(len(codenameTokens))
		if ratio >= 1.0 {
			// All codename tokens found in query — strong match.
			// Add tiny bonus per matched token so "react-native" (2 tokens)
			// outranks "react" (1 token) when both fully match.
			score := 1.0 + float64(matchedTokens)*0.01
			if score > bestScore {
				bestScore = score
			}
		} else if containsWholeWord(query, codename) {
			// Single-word codename appears as whole word in query.
			score := 1.0
			if score > bestScore {
				bestScore = score
			}
		} else {
			// Partial token match (e.g., 1/2 tokens of "pydantic-ai").
			score := ratio * 0.9
			if score > bestScore {
				bestScore = score
			}
		}
	} else if containsWholeWord(query, codename) {
		// Codename is a whole word but didn't match via tokenization
		// (single-token codename path).
		bestScore = 1.0
	}

	// --- Priority 4: Query terms match display name tokens ---
	// "auth.js docs" → display name "Auth.js Docs" tokens match
	if len(displayTokens) > 0 {
		matched := 0
		for _, dt := range displayTokens {
			for _, qt := range queryTerms {
				if qt == dt {
					matched++
					break
				}
			}
		}
		if matched > 0 {
			ratio := float64(matched) / float64(len(displayTokens))
			score := ratio * 0.85
			if score > bestScore {
				bestScore = score
			}
		}
	}

	// --- Priority 5: Query terms match description/URL text ---
	descText := strings.ToLower(t.Description)
	for _, url := range t.URLPrefixes {
		descText += " " + strings.ToLower(url)
	}
	if descText != "" {
		matched := 0
		for _, qt := range queryTerms {
			if strings.Contains(descText, qt) {
				matched++
			}
		}
		if matched > 0 {
			ratio := float64(matched) / float64(len(queryTerms))
			score := ratio * 0.5
			if score > bestScore {
				bestScore = score
			}
		}
	}

	// --- Priority 6: Fuzzy match on codename tokens (typo tolerance) ---
	if bestScore < 0.3 {
		for _, qt := range queryTerms {
			if len(qt) < 3 {
				continue
			}
			for _, ct := range codenameTokens {
				if len(ct) < 3 {
					continue
				}
				d := levenshtein(qt, ct, 2)
				if d > 0 && d <= 2 {
					fuzzy := 0.3 - float64(d)*0.1
					if fuzzy > bestScore {
						bestScore = fuzzy
					}
				}
			}
		}
	}

	return bestScore
}

// containsWholeWord checks if needle appears in haystack as a whole word
// (bounded by spaces, start/end of string, or hyphens).
func containsWholeWord(haystack, needle string) bool {
	idx := 0
	for {
		pos := strings.Index(haystack[idx:], needle)
		if pos < 0 {
			return false
		}
		pos += idx
		start := pos
		end := pos + len(needle)

		// Check left boundary
		leftOk := start == 0 || haystack[start-1] == ' ' || haystack[start-1] == '-' || haystack[start-1] == '_'
		// Check right boundary
		rightOk := end == len(haystack) || haystack[end] == ' ' || haystack[end] == '-' || haystack[end] == '_'

		if leftOk && rightOk {
			return true
		}
		idx = pos + 1
		if idx >= len(haystack) {
			return false
		}
	}
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
