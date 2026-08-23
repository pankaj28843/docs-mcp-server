package api

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/service"
)

const maxResponseBytes = 128 << 20

// Client is a typed client for the versioned, read-only daemon API.
type Client struct {
	baseURL string
	http    *http.Client
}

func NewClient(baseURL string, httpClient *http.Client) (*Client, error) {
	parsed, err := url.Parse(strings.TrimSpace(baseURL))
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
		return nil, fmt.Errorf("server URL must be an absolute http or https URL")
	}
	if parsed.RawQuery != "" || parsed.Fragment != "" {
		return nil, fmt.Errorf("server URL must not contain a query or fragment")
	}
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	return &Client{baseURL: strings.TrimRight(parsed.String(), "/"), http: httpClient}, nil
}

func (c *Client) Health(ctx context.Context) error {
	var response struct {
		Status string `json:"status"`
	}
	if err := c.get(ctx, "/healthz", nil, &response); err != nil {
		return err
	}
	if response.Status != "ok" {
		return service.NewError("remote_unavailable", "documentation daemon is unhealthy")
	}
	return nil
}

func (c *Client) List(ctx context.Context) (output.ListResponse, error) {
	var response output.ListResponse
	err := c.get(ctx, "/v1/tenants", nil, &response)
	return response, err
}

func (c *Client) Find(ctx context.Context, query string) (output.FindResponse, error) {
	var response output.FindResponse
	err := c.get(ctx, "/v1/tenants/find", url.Values{"q": {query}}, &response)
	return response, err
}

func (c *Client) Describe(ctx context.Context, codename string) (output.DescribeResponse, error) {
	var response output.DescribeResponse
	err := c.get(ctx, "/v1/tenants/"+url.PathEscape(codename), nil, &response)
	return response, err
}

func (c *Client) Search(ctx context.Context, tenants, query string, size, total int) (output.SearchResponse, error) {
	values := url.Values{
		"q":     {query},
		"size":  {strconv.Itoa(size)},
		"total": {strconv.Itoa(total)},
	}
	if tenants != "" {
		values.Set("tenants", tenants)
	}
	var response output.SearchResponse
	err := c.get(ctx, "/v1/search", values, &response)
	return response, err
}

func (c *Client) Fetch(ctx context.Context, tenant, uri string, maxChars int) (output.FetchResponse, error) {
	values := url.Values{
		"tenant":    {tenant},
		"url":       {uri},
		"max_chars": {strconv.Itoa(maxChars)},
	}
	var response output.FetchResponse
	err := c.get(ctx, "/v1/fetch", values, &response)
	return response, err
}

func (c *Client) get(ctx context.Context, path string, query url.Values, destination any) error {
	requestURL := c.baseURL + path
	if len(query) > 0 {
		requestURL += "?" + query.Encode()
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, requestURL, nil)
	if err != nil {
		return service.WrapError("remote_unavailable", "failed to create daemon request", err)
	}
	request.Header.Set("Accept", "application/json")
	response, err := c.http.Do(request)
	if err != nil {
		return service.WrapError("remote_unavailable", "documentation daemon is unavailable", err)
	}
	defer response.Body.Close()
	body := io.LimitReader(response.Body, maxResponseBytes+1)
	if response.StatusCode < http.StatusOK || response.StatusCode >= http.StatusMultipleChoices {
		var envelope struct {
			Error struct {
				Code    string `json:"code"`
				Message string `json:"message"`
			} `json:"error"`
		}
		if err := json.NewDecoder(body).Decode(&envelope); err != nil || envelope.Error.Code == "" {
			return service.NewError("remote_error", fmt.Sprintf("documentation daemon returned HTTP %d", response.StatusCode))
		}
		return service.NewError(envelope.Error.Code, envelope.Error.Message)
	}
	if err := json.NewDecoder(body).Decode(destination); err != nil {
		return service.WrapError("remote_error", "failed to decode daemon response", err)
	}
	return nil
}
