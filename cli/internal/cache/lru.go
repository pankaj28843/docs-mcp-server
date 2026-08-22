// Package cache provides a small byte-bounded response cache.
package cache

import (
	"container/list"
	"sync"
	"time"
)

type entry struct {
	key       string
	value     []byte
	expiresAt time.Time
}

type LRU struct {
	mu       sync.Mutex
	maxBytes int64
	bytes    int64
	ttl      time.Duration
	now      func() time.Time
	items    map[string]*list.Element
	order    *list.List
}

func New(maxBytes int64, ttl time.Duration) *LRU {
	return newWithClock(maxBytes, ttl, time.Now)
}

func newWithClock(maxBytes int64, ttl time.Duration, now func() time.Time) *LRU {
	return &LRU{
		maxBytes: maxBytes,
		ttl:      ttl,
		now:      now,
		items:    make(map[string]*list.Element),
		order:    list.New(),
	}
}

func (c *LRU) Get(key string) ([]byte, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	element, ok := c.items[key]
	if !ok {
		return nil, false
	}
	item := element.Value.(*entry)
	if !item.expiresAt.After(c.now()) {
		c.remove(element)
		return nil, false
	}
	c.order.MoveToFront(element)
	return append([]byte(nil), item.value...), true
}

func (c *LRU) Add(key string, value []byte) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if element, ok := c.items[key]; ok {
		c.remove(element)
	}
	if c.maxBytes <= 0 || int64(len(value)) > c.maxBytes {
		return
	}
	item := &entry{
		key:       key,
		value:     append([]byte(nil), value...),
		expiresAt: c.now().Add(c.ttl),
	}
	c.items[key] = c.order.PushFront(item)
	c.bytes += int64(len(item.value))
	for c.bytes > c.maxBytes {
		c.remove(c.order.Back())
	}
}

func (c *LRU) Bytes() int64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.bytes
}

func (c *LRU) Len() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return len(c.items)
}

func (c *LRU) remove(element *list.Element) {
	if element == nil {
		return
	}
	item := element.Value.(*entry)
	delete(c.items, item.key)
	c.order.Remove(element)
	c.bytes -= int64(len(item.value))
}
