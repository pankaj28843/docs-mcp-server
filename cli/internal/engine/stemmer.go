package engine

import "strings"

// Suffix rules matching the Python _SUFFIX_RULES table.
// Each pair: (suffix, replacement). Applied first; stop on match.
var suffixRules = [][2]string{
	{"ization", "ize"},
	{"ational", "ate"},
	{"fulness", "ful"},
	{"ousness", "ous"},
	{"iveness", "ive"},
	{"tional", "tion"},
	{"biliti", "ble"},
	{"lessli", "less"},
	{"entli", "ent"},
	{"enci", "ence"},
	{"anci", "ance"},
	{"izer", "ize"},
	{"abli", "able"},
	{"alli", "al"},
	{"ator", "ate"},
	{"alism", "al"},
	{"aliti", "al"},
	{"ousli", "ous"},
	{"ration", "rate"},
	{"ation", "ate"},
	{"ness", ""},
	{"ment", ""},
	{"ance", "an"},
	{"ence", "en"},
	{"able", ""},
	{"ible", ""},
}

// Simple suffixes to strip (no replacement). Applied second if no complex match.
var simpleSuffixes = []string{"ingly", "edly", "ing", "ed", "ly", "es", "s"}

// Stem applies the project's minimal Porter-like stemmer.
// This matches Python's _build_porter_stemmer() exactly.
func Stem(word string) string {
	lower := strings.ToLower(word)

	// Try complex suffix rules first
	for _, rule := range suffixRules {
		suffix, replacement := rule[0], rule[1]
		if strings.HasSuffix(lower, suffix) && len(lower)-len(suffix) >= 2 {
			candidate := lower[:len(lower)-len(suffix)] + replacement
			if len(candidate) >= 2 {
				return candidate
			}
		}
	}

	// Try simple suffix stripping
	for _, suffix := range simpleSuffixes {
		if strings.HasSuffix(lower, suffix) && len(lower)-len(suffix) >= 2 {
			candidate := lower[:len(lower)-len(suffix)]
			if len(candidate) >= 2 {
				return candidate
			}
		}
	}

	return lower
}
