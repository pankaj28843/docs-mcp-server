// Package api exposes the read-only documentation service over versioned HTTP.
package api

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/cache"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/service"
)

type Reader interface {
	List(context.Context) (output.ListResponse, error)
	Find(context.Context, string) (output.FindResponse, error)
	Describe(context.Context, string) (output.DescribeResponse, error)
	Search(context.Context, string, string, int, int) (output.SearchResponse, error)
	Fetch(context.Context, string, string, int) (output.FetchResponse, error)
}

type Handler struct {
	reader Reader
	cache  *cache.LRU
}

func NewHandler(reader Reader, responseCache *cache.LRU) *Handler {
	return &Handler{reader: reader, cache: responseCache}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		w.Header().Set("Allow", http.MethodGet)
		h.writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "only GET is supported")
		return
	}
	switch {
	case r.URL.Path == "/healthz":
		h.writeJSON(w, http.StatusOK, map[string]any{
			"status":        "ok",
			"cache_bytes":   h.cache.Bytes(),
			"cache_entries": h.cache.Len(),
		})
	case r.URL.Path == "/v1/tenants":
		h.cached(w, r, func(ctx context.Context) (any, error) { return h.reader.List(ctx) })
	case r.URL.Path == "/v1/tenants/find":
		query := strings.TrimSpace(r.URL.Query().Get("q"))
		if query == "" {
			h.writeError(w, http.StatusBadRequest, "invalid_argument", "q is required")
			return
		}
		h.cached(w, r, func(ctx context.Context) (any, error) { return h.reader.Find(ctx, query) })
	case strings.HasPrefix(r.URL.Path, "/v1/tenants/"):
		codename := strings.TrimPrefix(r.URL.Path, "/v1/tenants/")
		if codename == "" || strings.Contains(codename, "/") {
			h.writeError(w, http.StatusNotFound, "not_found", "route not found")
			return
		}
		h.cached(w, r, func(ctx context.Context) (any, error) { return h.reader.Describe(ctx, codename) })
	case r.URL.Path == "/v1/search":
		h.search(w, r)
	case r.URL.Path == "/v1/fetch":
		h.fetch(w, r)
	default:
		h.writeError(w, http.StatusNotFound, "not_found", "route not found")
	}
}

func (h *Handler) search(w http.ResponseWriter, r *http.Request) {
	query := strings.TrimSpace(r.URL.Query().Get("q"))
	if query == "" {
		h.writeError(w, http.StatusBadRequest, "invalid_argument", "q is required")
		return
	}
	size, ok := queryInt(r, "size", 10, 1, 100)
	if !ok {
		h.writeError(w, http.StatusBadRequest, "invalid_argument", "size must be between 1 and 100")
		return
	}
	total, ok := queryInt(r, "total", 20, 0, 10000)
	if !ok {
		h.writeError(w, http.StatusBadRequest, "invalid_argument", "total must be between 0 and 10000")
		return
	}
	tenants := strings.TrimSpace(r.URL.Query().Get("tenants"))
	h.cached(w, r, func(ctx context.Context) (any, error) {
		return h.reader.Search(ctx, tenants, query, size, total)
	})
}

func (h *Handler) fetch(w http.ResponseWriter, r *http.Request) {
	tenant := strings.TrimSpace(r.URL.Query().Get("tenant"))
	uri := strings.TrimSpace(r.URL.Query().Get("url"))
	if tenant == "" || uri == "" {
		h.writeError(w, http.StatusBadRequest, "invalid_argument", "tenant and url are required")
		return
	}
	maxChars, ok := queryInt(r, "max_chars", 0, 0, 100_000_000)
	if !ok {
		h.writeError(w, http.StatusBadRequest, "invalid_argument", "max_chars must be between 0 and 100000000")
		return
	}
	h.cached(w, r, func(ctx context.Context) (any, error) {
		return h.reader.Fetch(ctx, tenant, uri, maxChars)
	})
}

func queryInt(r *http.Request, name string, fallback, minimum, maximum int) (int, bool) {
	raw := r.URL.Query().Get(name)
	if raw == "" {
		return fallback, true
	}
	value, err := strconv.Atoi(raw)
	return value, err == nil && value >= minimum && value <= maximum
}

func (h *Handler) cached(w http.ResponseWriter, r *http.Request, load func(context.Context) (any, error)) {
	key := r.URL.RequestURI()
	if body, ok := h.cache.Get(key); ok {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("X-Docs-Cache", "HIT")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(body)
		return
	}
	value, err := load(r.Context())
	if err != nil {
		h.writeServiceError(w, err)
		return
	}
	body, err := json.Marshal(value)
	if err != nil {
		h.writeError(w, http.StatusInternalServerError, "internal_error", "failed to encode response")
		return
	}
	body = append(body, '\n')
	h.cache.Add(key, body)
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("X-Docs-Cache", "MISS")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(body)
}

func (h *Handler) writeServiceError(w http.ResponseWriter, err error) {
	var domainErr *service.Error
	if !errors.As(err, &domainErr) {
		h.writeError(w, http.StatusInternalServerError, "internal_error", "internal server error")
		return
	}
	status := http.StatusInternalServerError
	switch domainErr.Code {
	case "invalid_argument":
		status = http.StatusBadRequest
	case "tenant_not_found", "document_not_found":
		status = http.StatusNotFound
	case "index_unavailable":
		status = http.StatusConflict
	case "request_cancelled":
		status = http.StatusRequestTimeout
	}
	h.writeError(w, status, domainErr.Code, domainErr.Message)
}

func (h *Handler) writeError(w http.ResponseWriter, status int, code, message string) {
	h.writeJSON(w, status, map[string]any{"error": map[string]string{"code": code, "message": message}})
}

func (h *Handler) writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
