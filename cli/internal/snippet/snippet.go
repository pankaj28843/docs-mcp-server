// Package snippet extracts context-aware text clips from document bodies,
// centering around query term matches with word-boundary-aware trimming.
package snippet

import "strings"

const (
	// maxBoundarySearch is the max chars to scan for a word boundary
	// when trimming snippet start/end to avoid mid-word cuts.
	maxBoundarySearch = 30
)

// Build extracts a relevant snippet from text around query terms.
func Build(text string, terms []string, maxChars int) string {
	if text == "" || len(terms) == 0 {
		if len(text) > maxChars {
			return text[:maxChars] + "..."
		}
		return text
	}

	lower := strings.ToLower(text)
	termSet := make(map[string]bool, len(terms))
	for _, t := range terms {
		termSet[strings.ToLower(t)] = true
	}

	// Find first term occurrence
	bestPos := -1
	for t := range termSet {
		pos := strings.Index(lower, t)
		if pos >= 0 && (bestPos < 0 || pos < bestPos) {
			bestPos = pos
		}
	}

	if bestPos < 0 {
		// No term found - return beginning
		if len(text) > maxChars {
			return text[:maxChars] + "..."
		}
		return text
	}

	// Center the snippet around the first match
	half := maxChars / 2
	start := bestPos - half
	if start < 0 {
		start = 0
	}

	end := start + maxChars
	if end > len(text) {
		end = len(text)
		start = end - maxChars
		if start < 0 {
			start = 0
		}
	}

	snippet := text[start:end]

	// Clean up: don't start/end mid-word
	if start > 0 {
		if idx := strings.IndexByte(snippet, ' '); idx >= 0 && idx < maxBoundarySearch {
			snippet = snippet[idx+1:]
		}
		snippet = "..." + snippet
	}
	if end < len(text) {
		if idx := strings.LastIndexByte(snippet, ' '); idx >= 0 && idx > len(snippet)-maxBoundarySearch {
			snippet = snippet[:idx]
		}
		snippet = snippet + "..."
	}

	return snippet
}
