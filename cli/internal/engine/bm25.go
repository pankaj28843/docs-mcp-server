package engine

import (
	"container/heap"
	"math"
)

const (
	DefaultK1 = 1.5
	DefaultB  = 0.75
	idfFloor  = 1e-6
	// Cap dl/avgdl to prevent excessive penalties for long documents.
	maxLengthRatio = 4.0
)

// DefaultFieldBoosts matches Python schema.py create_default_schema() boosts.
var DefaultFieldBoosts = map[string]float64{
	"title":       2.5,
	"headings_h1": 2.5,
	"headings_h2": 2.0,
	"headings":    1.5,
	"body":        1.0,
	"url_path":    1.5,
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
// Matches Python stats.py:bm25() with capped length ratio.
func BM25(tf, docLength int, avgDocLength, k1, b float64) float64 {
	if tf <= 0 {
		return 0.0
	}
	tfFloat := float64(tf)
	rawRatio := float64(docLength) / math.Max(avgDocLength, 1e-9)
	normalizedLength := math.Min(rawRatio, maxLengthRatio)
	denominator := tfFloat + k1*(1-b+b*normalizedLength)
	return (tfFloat * (k1 + 1)) / denominator
}

// CalculateIDF matches Python stats.py:calculate_idf() exactly.
// Uses log(ratio + floor) + 1.0 with small-sample smoothing.
func CalculateIDF(df, totalDocs int) float64 {
	if totalDocs <= 0 {
		return 0.0
	}
	dfClamped := df
	if dfClamped < 0 {
		dfClamped = 0
	}
	if dfClamped > totalDocs {
		dfClamped = totalDocs
	}
	numerator := float64(totalDocs) - float64(dfClamped) + 0.5
	denominator := float64(dfClamped) + 0.5
	ratio := numerator / denominator
	if ratio < idfFloor {
		ratio = idfFloor
	}
	rawIDF := math.Log(ratio+idfFloor) + 1.0
	if rawIDF < idfFloor {
		return idfFloor
	}
	return rawIDF
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
	for i := 1; i < len(docs); i++ {
		for j := i; j > 0 && docs[j].Score > docs[j-1].Score; j-- {
			docs[j], docs[j-1] = docs[j-1], docs[j]
		}
	}
}

type minHeap []RankedDoc

func (h minHeap) Len() int            { return len(h) }
func (h minHeap) Less(i, j int) bool   { return h[i].Score < h[j].Score }
func (h minHeap) Swap(i, j int)        { h[i], h[j] = h[j], h[i] }
func (h *minHeap) Push(x any)  { *h = append(*h, x.(RankedDoc)) }
func (h *minHeap) Pop() any {
	old := *h
	n := len(old)
	x := old[n-1]
	*h = old[:n-1]
	return x
}
