package cache

import (
	"testing"
	"time"
)

func TestLRUEvictsLeastRecentlyUsedByBytes(t *testing.T) {
	c := New(6, time.Minute)
	c.Add("a", []byte("aaa"))
	c.Add("b", []byte("bb"))
	if _, ok := c.Get("a"); !ok {
		t.Fatal("expected a cache hit")
	}
	c.Add("c", []byte("cc"))

	if _, ok := c.Get("b"); ok {
		t.Fatal("least recently used b was not evicted")
	}
	if c.Bytes() != 5 || c.Len() != 2 {
		t.Fatalf("bytes=%d len=%d, want 5/2", c.Bytes(), c.Len())
	}
}

func TestLRUReplacementUpdatesByteAccounting(t *testing.T) {
	c := New(10, time.Minute)
	c.Add("a", []byte("12345"))
	c.Add("a", []byte("12"))
	if c.Bytes() != 2 || c.Len() != 1 {
		t.Fatalf("bytes=%d len=%d, want 2/1", c.Bytes(), c.Len())
	}
}

func TestLRUDoesNotStoreOversizeValue(t *testing.T) {
	c := New(3, time.Minute)
	c.Add("a", []byte("1234"))
	if c.Bytes() != 0 || c.Len() != 0 {
		t.Fatalf("oversize value stored: bytes=%d len=%d", c.Bytes(), c.Len())
	}
}

func TestLRUReturnsCopies(t *testing.T) {
	c := New(10, time.Minute)
	input := []byte("abc")
	c.Add("a", input)
	input[0] = 'x'
	got, ok := c.Get("a")
	if !ok || string(got) != "abc" {
		t.Fatalf("cached value = %q ok=%v", got, ok)
	}
	got[0] = 'y'
	again, _ := c.Get("a")
	if string(again) != "abc" {
		t.Fatalf("caller mutated cache: %q", again)
	}
}

func TestLRUExpiresEntries(t *testing.T) {
	now := time.Unix(100, 0)
	c := newWithClock(10, time.Second, func() time.Time { return now })
	c.Add("a", []byte("abc"))
	now = now.Add(11 * time.Second)
	if _, ok := c.Get("a"); ok {
		t.Fatal("expired entry returned")
	}
	if c.Bytes() != 0 || c.Len() != 0 {
		t.Fatalf("expired entry still accounted: bytes=%d len=%d", c.Bytes(), c.Len())
	}
}
