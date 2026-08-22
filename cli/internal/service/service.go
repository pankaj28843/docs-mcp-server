package service

import (
	"context"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/engine"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/snippet"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/storage"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/tenant"
)

type Service struct {
	dataDir          string
	deploymentConfig string
	maxConcurrent    int
}

func New(dataDir, deploymentConfig string, maxConcurrent int) (*Service, error) {
	if maxConcurrent < 1 {
		return nil, fmt.Errorf("max concurrent searches must be greater than zero")
	}
	if _, err := tenant.NewRegistry(dataDir, deploymentConfig); err != nil {
		return nil, fmt.Errorf("open documentation data: %w", err)
	}
	return &Service{dataDir: dataDir, deploymentConfig: deploymentConfig, maxConcurrent: maxConcurrent}, nil
}

func (s *Service) registry(ctx context.Context) (*tenant.Registry, error) {
	if err := ctx.Err(); err != nil {
		return nil, NewError("request_cancelled", "request cancelled")
	}
	reg, err := tenant.NewRegistry(s.dataDir, s.deploymentConfig)
	if err != nil {
		return nil, WrapError("storage_unavailable", "documentation data is unavailable", err)
	}
	return reg, nil
}

func (s *Service) List(ctx context.Context) (output.ListResponse, error) {
	reg, err := s.registry(ctx)
	if err != nil {
		return output.ListResponse{}, err
	}
	response := output.ListResponse{Count: reg.Count()}
	for _, item := range reg.List() {
		response.Tenants = append(response.Tenants, tenantInfo(item))
	}
	return response, nil
}

func (s *Service) Find(ctx context.Context, query string) (output.FindResponse, error) {
	reg, err := s.registry(ctx)
	if err != nil {
		return output.FindResponse{}, err
	}
	items := tenant.FindTenants(reg, query, 10)
	response := output.FindResponse{Query: query, Count: len(items)}
	for _, item := range items {
		response.Tenants = append(response.Tenants, tenantInfo(item.Tenant))
	}
	return response, nil
}

func (s *Service) Describe(ctx context.Context, codename string) (output.DescribeResponse, error) {
	reg, err := s.registry(ctx)
	if err != nil {
		return output.DescribeResponse{}, err
	}
	item := reg.Get(codename)
	if item == nil {
		return output.DescribeResponse{}, NewError("tenant_not_found", fmt.Sprintf("tenant %q not found", codename))
	}
	return output.DescribeResponse{
		Codename: item.Codename, DisplayName: item.DisplayName,
		Description: item.Description, DocCount: item.DocCount,
		URLPrefixes: item.URLPrefixes, Provenance: item.Provenance,
	}, nil
}

func (s *Service) Search(ctx context.Context, selected, query string, size, total int) (output.SearchResponse, error) {
	reg, err := s.registry(ctx)
	if err != nil {
		return output.SearchResponse{}, err
	}
	codenames := reg.Codenames()
	if selected != "" {
		codenames = strings.Split(selected, ",")
	}
	var targets []engine.TenantTarget
	for _, codename := range codenames {
		codename = strings.TrimSpace(codename)
		item := reg.Get(codename)
		if item == nil {
			return output.SearchResponse{}, NewError("tenant_not_found", fmt.Sprintf("tenant %q not found", codename))
		}
		if item.SegmentDB == "" {
			if len(codenames) == 1 {
				return output.SearchResponse{}, NewError("index_unavailable", fmt.Sprintf("tenant %q has no search index", codename))
			}
			continue
		}
		targets = append(targets, engine.TenantTarget{Codename: codename, SegmentDB: item.SegmentDB, Boost: tenant.ScoreTenantMatch(item, query)})
	}
	if len(targets) == 0 {
		return output.SearchResponse{}, NewError("index_unavailable", "no search indexes are available")
	}
	if len(targets) == 1 {
		return s.searchOne(ctx, reg.Get(targets[0].Codename), query, size)
	}
	results, searched, err := engine.SearchAllContext(ctx, targets, query, size, total, s.maxConcurrent)
	if err != nil {
		return output.SearchResponse{}, NewError("request_cancelled", "request cancelled")
	}
	response := output.SearchResponse{Query: query, TenantsSearched: searched}
	for _, result := range results {
		response.Results = append(response.Results, output.SearchResult{
			Tenant: result.Tenant, URL: result.URL, Title: result.Title,
			Snippet: result.Snippet, Score: result.Score,
		})
	}
	return response, nil
}

func (s *Service) searchOne(ctx context.Context, item *tenant.Tenant, query string, size int) (output.SearchResponse, error) {
	if err := ctx.Err(); err != nil {
		return output.SearchResponse{}, NewError("request_cancelled", "request cancelled")
	}
	segment, err := storage.OpenSegment(item.SegmentDB)
	if err != nil {
		return output.SearchResponse{}, WrapError("index_unavailable", "failed to open search index", err)
	}
	defer segment.Close()
	results, err := engine.SearchSegment(segment, query, size)
	if err != nil {
		return output.SearchResponse{}, WrapError("search_failed", "search failed", err)
	}
	terms := engine.AnalyzeToStrings(query)
	response := output.SearchResponse{Query: query, Tenant: item.Codename, Provenance: &item.Provenance}
	for _, result := range results {
		response.Results = append(response.Results, output.SearchResult{
			Tenant: item.Codename, URL: result.URL, Title: result.Title,
			Snippet: snippet.Build(result.Body, terms, 200), Score: result.Score,
		})
	}
	return response, nil
}

func (s *Service) Fetch(ctx context.Context, codename, uri string, maxChars int) (output.FetchResponse, error) {
	reg, err := s.registry(ctx)
	if err != nil {
		return output.FetchResponse{}, err
	}
	item := reg.Get(codename)
	if item == nil {
		return output.FetchResponse{}, NewError("tenant_not_found", fmt.Sprintf("tenant %q not found", codename))
	}
	content, title, err := fetchFromDisk(item, uri)
	if err != nil {
		return output.FetchResponse{}, WrapError("document_not_found", fmt.Sprintf("document not found: %s", uri), err)
	}
	response := output.FetchResponse{Tenant: codename, URL: uri, Title: title, Content: &content, Provenance: &item.Provenance}
	if maxChars > 0 {
		bounded, truncated, originalChars, err := boundUTF8(content, maxChars)
		if err != nil {
			return output.FetchResponse{}, WrapError("invalid_document_encoding", "document is not valid UTF-8", err)
		}
		returnedChars := utf8.RuneCountInString(bounded)
		originalBytes, returnedBytes := len(content), len(bounded)
		response.Content = &bounded
		response.Truncated = &truncated
		response.OriginalChars = &originalChars
		response.ReturnedChars = &returnedChars
		response.OriginalBytes = &originalBytes
		response.ReturnedBytes = &returnedBytes
	}
	return response, nil
}

func tenantInfo(item *tenant.Tenant) output.TenantInfo {
	return output.TenantInfo{
		Codename: item.Codename, Description: fmt.Sprintf("%s - %s", item.DisplayName, item.Description),
		DocCount: item.DocCount, Provenance: item.Provenance,
	}
}

func fetchFromDisk(item *tenant.Tenant, uri string) (string, string, error) {
	parsed, parseErr := url.Parse(uri)
	if parseErr == nil && parsed.Host != "" {
		for _, candidate := range diskCandidates(item, parsed) {
			if data, err := os.ReadFile(candidate); err == nil {
				content := string(data)
				return content, extractTitle(content, candidate), nil
			}
		}
	}
	if item.SegmentDB != "" {
		segment, err := storage.OpenSegment(item.SegmentDB)
		if err == nil {
			defer segment.Close()
			document, lookupErr := segment.GetDocumentByURL(uri)
			if lookupErr == nil && document != nil {
				if document.Body != "" {
					return document.Body, document.Title, nil
				}
				if document.Path != "" {
					path := document.Path
					if !filepath.IsAbs(path) {
						path = filepath.Join(item.DataDir, path)
					}
					if data, readErr := os.ReadFile(path); readErr == nil {
						return string(data), document.Title, nil
					}
				}
			}
		}
	}
	return "", "", fmt.Errorf("document not found")
}

func diskCandidates(item *tenant.Tenant, parsed *url.URL) []string {
	for _, segment := range strings.Split(parsed.Path, "/") {
		if segment == ".." {
			return nil
		}
	}
	host := parsed.Hostname()
	if host == "" {
		return nil
	}
	root := filepath.Join(item.DataDir, host)
	relative := strings.Trim(strings.TrimRight(parsed.Path, "/"), "/")
	base := filepath.Join(root, filepath.FromSlash(relative))
	candidates := []string{base + ".md", base}
	for _, candidate := range candidates {
		rel, err := filepath.Rel(root, candidate)
		if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return nil
		}
	}
	return candidates
}

func extractTitle(content, path string) string {
	for _, line := range strings.SplitN(content, "\n", 10) {
		if strings.HasPrefix(line, "# ") {
			return strings.TrimSpace(line[2:])
		}
	}
	return filepath.Base(path)
}

func boundUTF8(content string, maxChars int) (string, bool, int, error) {
	if !utf8.ValidString(content) {
		return "", false, 0, fmt.Errorf("invalid UTF-8")
	}
	runes := []rune(content)
	if len(runes) <= maxChars {
		return content, false, len(runes), nil
	}
	return string(runes[:maxChars]), true, len(runes), nil
}
