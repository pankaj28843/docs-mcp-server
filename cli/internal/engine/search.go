// Package engine implements BM25F full-text search over pre-built document
// segments. It provides single-tenant and parallel multi-tenant search with
// per-tenant score normalization and tenant-name boosting.
package engine

import (
	"fmt"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/storage"
)

const (
	defaultMaxResults = 10
	maxResultsCap     = 100
)

// SearchResult holds a single search hit.
type SearchResult struct {
	URL   string
	Title string
	Body  string
	Score float64
}

// SearchSegment runs BM25F search against an open segment.
func SearchSegment(seg *storage.Segment, query string, maxResults int) ([]SearchResult, error) {
	if maxResults <= 0 {
		maxResults = defaultMaxResults
	}
	if maxResults > maxResultsCap {
		maxResults = maxResultsCap
	}

	terms := UniqueTerms(AnalyzeToStrings(query))
	if len(terms) == 0 {
		return nil, nil
	}

	stats, err := seg.GetCorpusStats()
	if err != nil {
		return nil, fmt.Errorf("corpus stats: %w", err)
	}
	if stats.TotalDocs == 0 {
		return nil, nil
	}

	fields := []string{"body", "title", "headings_h1", "headings_h2", "headings", "url_path"}
	docScores := make(map[string]float64)

	for _, field := range fields {
		boost := DefaultFieldBoosts[field]
		if boost == 0 {
			boost = 1.0
		}

		_, avgLen, err := seg.GetFieldLengthStats(field)
		if err != nil || avgLen <= 0 {
			if field == "body" {
				avgLen = stats.AvgDocLength
			} else {
				continue
			}
		}

		for _, term := range terms {
			postings, err := seg.GetPostings(field, term)
			if err != nil || len(postings) == 0 {
				continue
			}

			idf := CalculateIDF(len(postings), stats.TotalDocs)

			for _, p := range postings {
				docLen := p.DocLength
				if docLen <= 0 {
					docLen = int(avgLen)
				}
				weight := BM25(p.TF, docLen, avgLen, DefaultK1, DefaultB)
				if weight <= 0 {
					continue
				}
				docScores[p.DocID] += idf * weight * boost
			}
		}
	}

	ranked := TopK(docScores, maxResults)
	if len(ranked) == 0 {
		return nil, nil
	}

	docIDs := make([]string, len(ranked))
	for i, r := range ranked {
		docIDs[i] = r.DocID
	}
	docs, err := seg.GetDocumentsBatch(docIDs)
	if err != nil {
		return nil, fmt.Errorf("fetch documents: %w", err)
	}

	results := make([]SearchResult, 0, len(ranked))
	for _, r := range ranked {
		doc := docs[r.DocID]
		if doc == nil {
			continue
		}
		results = append(results, SearchResult{
			URL:   doc.URL,
			Title: doc.Title,
			Body:  doc.Body,
			Score: r.Score,
		})
	}
	return results, nil
}
