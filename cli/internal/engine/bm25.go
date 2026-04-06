package engine

import (
	"container/heap"
	"math"
)

const (
	DefaultK1 = 1.2
	DefaultB  = 0.75
)

// FieldBoosts maps field names to their boost weights.
// Matches Python BM25SearchEngine defaults.
var DefaultFieldBoosts = map[string]float64{
	"title":       3.0,
	"headings_h1": 2.5,
	"headings_h2": 2.0,
	"headings":    1.5,
	"body":        1.0,
	"url_path":    0.5,
}

// Posting represents a single term occurrence in a document field.
type Posting struct {
	DocID     string
	TF        int
	DocLength int
}

// RankedDoc is a scored search result.
type RankedDoc struct {
	DocID string
	Score float64
}

// BM25 calculates the BM25 term frequency normalization.
func BM25(tf, docLength int, avgDocLength, k1, b float64) float64 {
	tfFloat := float64(tf)
	dlFloat := float64(docLength)
	return (tfFloat * (k1 + 1)) / (tfFloat + k1*(1-b+b*(dlFloat/avgDocLength)))
}

// CalculateIDF computes inverse document frequency with floor to prevent negative scores.
func CalculateIDF(df, totalDocs int) float64 {
	dfFloat := float64(df)
	nFloat := float64(totalDocs)
	idf := math.Log((nFloat - dfFloat + 0.5) / (dfFloat + 0.5))
	if idf < 0 {
		idf = 0.01 // IDF floor matching Python implementation
	}
	return idf
}

// TopK returns the top k documents by score using a min-heap.
func TopK(scores map[string]float64, k int) []RankedDoc {
	if k <= 0 || len(scores) == 0 {
		return nil
	}

	if len(scores) <= k {
		result := make([]RankedDoc, 0, len(scores))
		for docID, score := range scores {
			result = append(result, RankedDoc{DocID: docID, Score: score})
		}
		// Sort descending
		sortRankedDocs(result)
		return result
	}

	h := &minHeap{}
	heap.Init(h)
	for docID, score := range scores {
		if h.Len() < k {
			heap.Push(h, RankedDoc{DocID: docID, Score: score})
		} else if score > (*h)[0].Score {
			(*h)[0] = RankedDoc{DocID: docID, Score: score}
			heap.Fix(h, 0)
		}
	}

	result := make([]RankedDoc, h.Len())
	for i := len(result) - 1; i >= 0; i-- {
		result[i] = heap.Pop(h).(RankedDoc)
	}
	return result
}

func sortRankedDocs(docs []RankedDoc) {
	// Simple insertion sort for small slices
	for i := 1; i < len(docs); i++ {
		for j := i; j > 0 && docs[j].Score > docs[j-1].Score; j-- {
			docs[j], docs[j-1] = docs[j-1], docs[j]
		}
	}
}

// minHeap implements heap.Interface for RankedDoc.
type minHeap []RankedDoc

func (h minHeap) Len() int            { return len(h) }
func (h minHeap) Less(i, j int) bool   { return h[i].Score < h[j].Score }
func (h minHeap) Swap(i, j int)        { h[i], h[j] = h[j], h[i] }
func (h *minHeap) Push(x interface{})  { *h = append(*h, x.(RankedDoc)) }
func (h *minHeap) Pop() interface{} {
	old := *h
	n := len(old)
	x := old[n-1]
	*h = old[:n-1]
	return x
}
