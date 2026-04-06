package engine

import (
	"regexp"
	"strings"
)

// Token represents an analyzed token with position info.
type Token struct {
	Text     string
	Position int
}

var tokenPattern = regexp.MustCompile(`\w+`)

// Analyze tokenizes and normalizes text using the standard pipeline:
// regex tokenize -> lowercase -> stop removal -> Porter stem.
// Matches Python's StandardAnalyzer behavior.
func Analyze(text string) []Token {
	matches := tokenPattern.FindAllStringIndex(text, -1)
	tokens := make([]Token, 0, len(matches))
	pos := 0
	for _, loc := range matches {
		word := strings.ToLower(text[loc[0]:loc[1]])
		if IsStopword(word) {
			continue
		}
		stemmed := Stem(word)
		if stemmed == "" {
			continue
		}
		tokens = append(tokens, Token{Text: stemmed, Position: pos})
		pos++
	}
	return tokens
}

// AnalyzeToStrings returns just the stemmed terms (no positions).
func AnalyzeToStrings(text string) []string {
	tokens := Analyze(text)
	result := make([]string, len(tokens))
	for i, t := range tokens {
		result[i] = t.Text
	}
	return result
}

// UniqueTerms returns deduplicated terms preserving order.
func UniqueTerms(terms []string) []string {
	seen := make(map[string]struct{}, len(terms))
	result := make([]string, 0, len(terms))
	for _, t := range terms {
		if _, ok := seen[t]; !ok {
			seen[t] = struct{}{}
			result = append(result, t)
		}
	}
	return result
}
