package storage

import (
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"testing"

	_ "modernc.org/sqlite"
)

func TestSegmentDSNUsesReadOnlyImmutableURI(t *testing.T) {
	dsn := segmentDSN("/tmp/search index.db")
	for _, want := range []string{"file:///tmp/search%20index.db", "mode=ro", "immutable=1", "_pragma=query_only%28true%29"} {
		if !strings.Contains(dsn, want) {
			t.Errorf("segmentDSN() = %q, want to contain %q", dsn, want)
		}
	}
}

func TestOpenSegmentReadOnlyImmutable(t *testing.T) {
	path := t.TempDir() + "/index.db"
	writeSegmentFixture(t, path)

	seg, err := OpenSegment(path)
	if err != nil {
		t.Fatalf("OpenSegment(%q): %v", path, err)
	}
	defer seg.Close()

	assertReadOnlySegment(t, seg)
}

func TestOpenSegmentAcceptsRelativePath(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "index.db")
	writeSegmentFixture(t, path)

	originalWd, err := os.Getwd()
	if err != nil {
		t.Fatalf("get cwd: %v", err)
	}
	t.Cleanup(func() {
		if err := os.Chdir(originalWd); err != nil {
			t.Fatalf("restore cwd: %v", err)
		}
	})

	if err := os.Chdir(dir); err != nil {
		t.Fatalf("chdir fixture dir: %v", err)
	}

	seg, err := OpenSegment("index.db")
	if err != nil {
		t.Fatalf("OpenSegment(%q): %v", "index.db", err)
	}
	defer seg.Close()

	assertReadOnlySegment(t, seg)
}

func writeSegmentFixture(t *testing.T, path string) {
	t.Helper()

	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatalf("open fixture DB: %v", err)
	}
	_, err = db.Exec(`CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO metadata (key, value) VALUES ('doc_count', '1');`)
	if err != nil {
		t.Fatalf("create fixture DB: %v", err)
	}
	if err := db.Close(); err != nil {
		t.Fatalf("close fixture DB: %v", err)
	}
}

func assertReadOnlySegment(t *testing.T, seg *Segment) {
	t.Helper()

	var mode int
	if err := seg.db.QueryRow("PRAGMA query_only").Scan(&mode); err != nil {
		t.Fatalf("read query_only pragma: %v", err)
	}
	if mode != 1 {
		t.Errorf("PRAGMA query_only = %d, want 1", mode)
	}

	_, err := seg.db.Exec("CREATE TABLE should_fail (id INTEGER)")
	if err == nil {
		t.Fatal("CREATE TABLE on read-only segment succeeded, want error")
	}
}
