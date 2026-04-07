// Package output handles formatted CLI output in both JSON and human-readable
// text modes. It provides response types matching the MCP server format and
// timing instrumentation for performance measurement.
package output

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
	"time"
)

// Format controls output style.
type Format int

const (
	FormatText Format = iota
	FormatJSON
)

// Writer handles formatted output.
type Writer struct {
	Out    io.Writer
	Err    io.Writer
	Format Format
	Timing bool
	start  time.Time
}

// New creates a Writer with the given options.
func New(jsonOutput, timing bool) *Writer {
	w := &Writer{
		Out:    os.Stdout,
		Err:    os.Stderr,
		Timing: timing,
		start:  time.Now(),
	}
	if jsonOutput {
		w.Format = FormatJSON
	}
	return w
}

// JSON writes v as JSON to stdout.
func (w *Writer) JSON(v any) error {
	enc := json.NewEncoder(w.Out)
	enc.SetIndent("", "  ")
	return enc.Encode(v)
}

// Text writes formatted text to stdout.
func (w *Writer) Text(format string, args ...any) {
	fmt.Fprintf(w.Out, format, args...)
}

// Error writes to stderr.
func (w *Writer) Error(format string, args ...any) {
	fmt.Fprintf(w.Err, format, args...)
}

// Finish prints timing info if enabled.
func (w *Writer) Finish() {
	if w.Timing {
		elapsed := time.Since(w.start)
		fmt.Fprintf(w.Err, "%.1fms\n", float64(elapsed.Microseconds())/1000)
	}
}

// SearchResult is the JSON-serializable search result.
type SearchResult struct {
	Tenant  string  `json:"tenant,omitempty"`
	URL     string  `json:"url"`
	Title   string  `json:"title"`
	Snippet string  `json:"snippet"`
	Score   float64 `json:"score,omitempty"`
}

// SearchResponse matches MCP server response format.
type SearchResponse struct {
	Results         []SearchResult `json:"results"`
	Query           string         `json:"query,omitempty"`
	Tenant          string         `json:"tenant,omitempty"`
	TenantsSearched int            `json:"tenants_searched,omitempty"`
	Error           string         `json:"error,omitempty"`
}

// FetchResponse matches MCP server response format.
type FetchResponse struct {
	URL     string `json:"url"`
	Title   string `json:"title"`
	Content string `json:"content"`
	Error   string `json:"error,omitempty"`
}

// TenantInfo for JSON output.
type TenantInfo struct {
	Codename    string `json:"codename"`
	Description string `json:"description"`
	DocCount    int    `json:"doc_count,omitempty"`
}

// ListResponse for list command.
type ListResponse struct {
	Count   int          `json:"count"`
	Tenants []TenantInfo `json:"tenants"`
}

// FindResponse for find command.
type FindResponse struct {
	Query   string       `json:"query"`
	Count   int          `json:"count"`
	Tenants []TenantInfo `json:"tenants"`
}

// DescribeResponse for describe command.
type DescribeResponse struct {
	Codename    string   `json:"codename"`
	DisplayName string   `json:"display_name"`
	Description string   `json:"description"`
	DocCount    int      `json:"doc_count"`
	URLPrefixes []string `json:"url_prefixes,omitempty"`
}

// PrintSearchResults outputs search results in the configured format.
func (w *Writer) PrintSearchResults(results []SearchResult, query string) {
	if w.Format == FormatJSON {
		w.JSON(SearchResponse{Results: results, Query: query})
		return
	}
	if len(results) == 0 {
		w.Text("No results found for %q\n", query)
		return
	}
	for i, r := range results {
		if i > 0 {
			w.Text("\n")
		}
		if r.Tenant != "" {
			w.Text("[%s] %s\n", r.Tenant, r.Title)
		} else {
			w.Text("%s\n", r.Title)
		}
		w.Text("  %s\n", r.URL)
		if r.Snippet != "" {
			wrapped := wordWrap(r.Snippet, 76)
			for _, line := range wrapped {
				w.Text("  %s\n", line)
			}
		}
	}
}

func wordWrap(text string, width int) []string {
	if len(text) <= width {
		return []string{text}
	}
	var lines []string
	words := strings.Fields(text)
	current := ""
	for _, word := range words {
		if current == "" {
			current = word
		} else if len(current)+1+len(word) <= width {
			current += " " + word
		} else {
			lines = append(lines, current)
			current = word
		}
	}
	if current != "" {
		lines = append(lines, current)
	}
	return lines
}
