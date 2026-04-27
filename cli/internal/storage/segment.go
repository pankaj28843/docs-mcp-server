// Package storage provides read-only access to SQLite search segment
// databases. It handles connection pooling, pragma optimization, and
// batch document retrieval for the BM25 search engine.
package storage

import (
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"modernc.org/sqlite"
	sqlite3 "modernc.org/sqlite/lib"
)

// Segment provides read-only access to a SQLite search segment.
type Segment struct {
	db       *sql.DB
	dbPath   string
	DocCount int
}

// CorpusStats holds aggregate index statistics.
type CorpusStats struct {
	TotalDocs    int
	AvgDocLength float64
}

// DocumentFields holds stored document data.
type DocumentFields struct {
	DocID      string
	URL        string
	Title      string
	Body       string
	Excerpt    string
	URLPath    string
	Path       string
	Headings   string
	HeadingsH1 string
	HeadingsH2 string
}

// OpenSegment opens a segment database for reading.
func OpenSegment(dbPath string) (*Segment, error) {
	db, err := sql.Open("sqlite", segmentDSN(dbPath))
	if err != nil {
		return nil, fmt.Errorf("open segment %s: %w", dbPath, err)
	}
	// Single connection is fine for read-only CLI
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)

	seg := &Segment{db: db, dbPath: dbPath}
	if err := seg.loadDocCount(); err != nil {
		db.Close()
		return nil, explainBusy(err)
	}
	return seg, nil
}

func explainBusy(err error) error {
	var sqliteErr *sqlite.Error
	if errors.As(err, &sqliteErr) && sqliteErr.Code()&0xff == sqlite3.SQLITE_BUSY {
		return fmt.Errorf("%w; read-only searches should open indexes with mode=ro&immutable=1 to avoid taking SQLite locks; if you are on this CLI version, the writer likely has an exclusive lock", err)
	}
	return err
}

func segmentDSN(dbPath string) string {
	q := url.Values{}
	q.Set("mode", "ro")
	q.Set("immutable", "1")
	q.Add("_pragma", "mmap_size(268435456)")
	q.Add("_pragma", "cache_size(-16384)")
	q.Add("_pragma", "query_only(true)")
	q.Add("_pragma", "temp_store(memory)")

	u := url.URL{Scheme: "file", Path: dbPath, RawQuery: q.Encode()}
	return u.String()
}

func (s *Segment) loadDocCount() error {
	var val sql.NullString
	err := s.db.QueryRow("SELECT value FROM metadata WHERE key = 'doc_count'").Scan(&val)
	if err != nil {
		return fmt.Errorf("read doc_count: %w", err)
	}
	if val.Valid {
		fmt.Sscanf(val.String, "%d", &s.DocCount)
	}
	return nil
}

// GetCorpusStats returns total docs and average body length.
func (s *Segment) GetCorpusStats() (CorpusStats, error) {
	rows, err := s.db.Query("SELECT key, value FROM metadata WHERE key IN ('doc_count', 'body_total_terms')")
	if err != nil {
		return CorpusStats{}, err
	}
	defer rows.Close()

	meta := make(map[string]string)
	for rows.Next() {
		var k, v string
		if err := rows.Scan(&k, &v); err != nil {
			return CorpusStats{}, err
		}
		meta[k] = v
	}

	var totalDocs, totalTerms int
	fmt.Sscanf(meta["doc_count"], "%d", &totalDocs)
	fmt.Sscanf(meta["body_total_terms"], "%d", &totalTerms)

	if totalDocs <= 0 {
		return CorpusStats{TotalDocs: 0, AvgDocLength: 1000}, nil
	}
	return CorpusStats{
		TotalDocs:    totalDocs,
		AvgDocLength: float64(totalTerms) / float64(totalDocs),
	}, nil
}

// GetFieldLengthStats returns (count, sum_of_lengths) for a field.
func (s *Segment) GetFieldLengthStats(field string) (int, float64, error) {
	lengthCol, ok := fieldLengthColumn[field]
	if !ok {
		return 0, 0, nil
	}
	var count int
	var total sql.NullFloat64
	err := s.db.QueryRow(fmt.Sprintf("SELECT COUNT(*), SUM(%s) FROM documents", lengthCol)).Scan(&count, &total)
	if err != nil {
		return 0, 0, err
	}
	avg := 1.0
	if count > 0 && total.Valid {
		avg = total.Float64 / float64(count)
	}
	return count, avg, nil
}

var fieldLengthColumn = map[string]string{
	"url_path":    "url_path_length",
	"title":       "title_length",
	"headings_h1": "headings_h1_length",
	"headings_h2": "headings_h2_length",
	"headings":    "headings_length",
	"body":        "body_length",
}

// Postings represents a term's posting list from the index.
type Postings struct {
	DocID     string
	TF        int
	DocLength int
}

// GetPostings retrieves postings for a field/term pair.
func (s *Segment) GetPostings(field, term string) ([]Postings, error) {
	rows, err := s.db.Query(
		"SELECT doc_id, tf, doc_length FROM postings WHERE field = ? AND term = ?",
		field, term,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var result []Postings
	for rows.Next() {
		var p Postings
		if err := rows.Scan(&p.DocID, &p.TF, &p.DocLength); err != nil {
			return nil, err
		}
		result = append(result, p)
	}
	return result, rows.Err()
}

// GetDocument retrieves a document by ID.
func (s *Segment) GetDocument(docID string) (*DocumentFields, error) {
	var doc DocumentFields
	var url, title, body, excerpt, urlPath, path, headings, h1, h2 sql.NullString
	err := s.db.QueryRow(
		"SELECT url, title, body, excerpt, url_path, path, headings, headings_h1, headings_h2 FROM documents WHERE doc_id = ?",
		docID,
	).Scan(&url, &title, &body, &excerpt, &urlPath, &path, &headings, &h1, &h2)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, err
	}
	doc.DocID = docID
	doc.URL = nullStr(url)
	doc.Title = nullStr(title)
	doc.Body = nullStr(body)
	doc.Excerpt = nullStr(excerpt)
	doc.URLPath = nullStr(urlPath)
	doc.Path = nullStr(path)
	doc.Headings = nullStr(headings)
	doc.HeadingsH1 = nullStr(h1)
	doc.HeadingsH2 = nullStr(h2)
	return &doc, nil
}

// GetDocumentByURL retrieves a document by its URL.
func (s *Segment) GetDocumentByURL(url string) (*DocumentFields, error) {
	var doc DocumentFields
	var dbURL, title, body, excerpt, urlPath, path sql.NullString
	err := s.db.QueryRow(
		"SELECT doc_id, url, title, body, excerpt, url_path, path FROM documents WHERE url = ?",
		url,
	).Scan(&doc.DocID, &dbURL, &title, &body, &excerpt, &urlPath, &path)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, err
	}
	doc.URL = nullStr(dbURL)
	doc.Title = nullStr(title)
	doc.Body = nullStr(body)
	doc.Excerpt = nullStr(excerpt)
	doc.URLPath = nullStr(urlPath)
	doc.Path = nullStr(path)
	return &doc, nil
}

// GetDocumentsBatch retrieves multiple documents by ID.
func (s *Segment) GetDocumentsBatch(docIDs []string) (map[string]*DocumentFields, error) {
	if len(docIDs) == 0 {
		return nil, nil
	}
	placeholders := make([]string, len(docIDs))
	args := make([]interface{}, len(docIDs))
	for i, id := range docIDs {
		placeholders[i] = "?"
		args[i] = id
	}
	query := fmt.Sprintf(
		"SELECT doc_id, url, title, body, excerpt, url_path, path, headings, headings_h1, headings_h2 FROM documents WHERE doc_id IN (%s)",
		strings.Join(placeholders, ","),
	)
	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := make(map[string]*DocumentFields, len(docIDs))
	for rows.Next() {
		var doc DocumentFields
		var url, title, body, excerpt, urlPath, path, headings, h1, h2 sql.NullString
		if err := rows.Scan(&doc.DocID, &url, &title, &body, &excerpt, &urlPath, &path, &headings, &h1, &h2); err != nil {
			return nil, err
		}
		doc.URL = nullStr(url)
		doc.Title = nullStr(title)
		doc.Body = nullStr(body)
		doc.Excerpt = nullStr(excerpt)
		doc.URLPath = nullStr(urlPath)
		doc.Path = nullStr(path)
		doc.Headings = nullStr(headings)
		doc.HeadingsH1 = nullStr(h1)
		doc.HeadingsH2 = nullStr(h2)
		result[doc.DocID] = &doc
	}
	return result, rows.Err()
}

// Close releases the database connection.
func (s *Segment) Close() error {
	if s.db != nil {
		return s.db.Close()
	}
	return nil
}

func nullStr(ns sql.NullString) string {
	if ns.Valid {
		return ns.String
	}
	return ""
}

// FindLatestDB finds the latest .db file in a search_segments directory.
func FindLatestDB(segmentsDir string) (string, error) {
	// Try manifest first
	manifestPath := filepath.Join(segmentsDir, "manifest.json")
	if data, err := os.ReadFile(manifestPath); err == nil {
		var manifest struct {
			LatestSegmentID string `json:"latest_segment_id"`
		}
		if json.Unmarshal(data, &manifest) == nil && manifest.LatestSegmentID != "" {
			dbPath := filepath.Join(segmentsDir, manifest.LatestSegmentID+".db")
			if _, err := os.Stat(dbPath); err == nil {
				return dbPath, nil
			}
		}
	}

	// Fallback: find newest .db file by mtime
	entries, err := os.ReadDir(segmentsDir)
	if err != nil {
		return "", fmt.Errorf("read segments dir: %w", err)
	}

	var newest string
	var newestTime int64
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".db") {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		if info.ModTime().UnixNano() > newestTime {
			newestTime = info.ModTime().UnixNano()
			newest = filepath.Join(segmentsDir, e.Name())
		}
	}
	if newest == "" {
		return "", fmt.Errorf("no .db files in %s", segmentsDir)
	}
	return newest, nil
}
