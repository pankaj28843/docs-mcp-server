package engine

// Standard English stopwords matching the Python implementation.
var defaultStopwords = map[string]struct{}{
	"a": {}, "an": {}, "and": {}, "are": {}, "as": {}, "at": {},
	"be": {}, "but": {}, "by": {}, "for": {}, "if": {}, "in": {},
	"into": {}, "is": {}, "it": {}, "no": {}, "not": {}, "of": {},
	"on": {}, "or": {}, "such": {}, "that": {}, "the": {}, "their": {},
	"then": {}, "there": {}, "these": {}, "they": {}, "this": {},
	"to": {}, "was": {}, "will": {}, "with": {},
}

func IsStopword(term string) bool {
	_, ok := defaultStopwords[term]
	return ok
}
