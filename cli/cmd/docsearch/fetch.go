package main

import (
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/storage"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/tenant"
	"github.com/spf13/cobra"
)

func fetchCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "fetch <tenant> <url>",
		Short: "Fetch full page content by URL",
		Long: `Fetch the full content of a documentation page by URL.

Use this after 'docsearch search' to read the actual documentation content.
The URL should be from search results.

Examples:
  docsearch fetch django "https://docs.djangoproject.com/en/5.2/topics/db/queries/"
  docsearch fetch react "https://react.dev/reference/react/useEffect" --json`,
		Args: cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			w := getWriter()
			defer w.Finish()

			reg, err := getRegistry()
			if err != nil {
				return err
			}

			tenantCodename := args[0]
			uri := args[1]

			t := reg.Get(tenantCodename)
			if t == nil {
				errMsg := fmt.Sprintf("Tenant '%s' not found. Available: %s", tenantCodename, strings.Join(reg.Codenames(), ", "))
				if w.Format == output.FormatJSON {
					return w.JSON(output.FetchResponse{URL: uri, Error: errMsg})
				}
				return fmt.Errorf("%s", errMsg)
			}

			content, title, err := fetchFromDisk(t, uri)
			if err != nil {
				errMsg := fmt.Sprintf("Document not found: %s", err)
				if w.Format == output.FormatJSON {
					return w.JSON(output.FetchResponse{URL: uri, Error: errMsg})
				}
				return fmt.Errorf("%s", errMsg)
			}

			if w.Format == output.FormatJSON {
				return w.JSON(output.FetchResponse{
					URL:     uri,
					Title:   title,
					Content: content,
				})
			}

			if title != "" {
				w.Text("# %s\n\n", title)
			}
			w.Text("%s\n", content)
			return nil
		},
	}
}

// fetchFromDisk resolves a document URL to local content.
// Tries file path lookup first, then falls back to the segment database.
func fetchFromDisk(t *tenant.Tenant, uri string) (content, title string, err error) {
	docsRoot := t.DataDir

	// Try path-based lookup: {docs_root}/{netloc}/{url_path}.md
	parsed, parseErr := url.Parse(uri)
	if parseErr == nil && parsed.Host != "" {
		urlPath := strings.TrimRight(parsed.Path, "/")
		mdPath := filepath.Join(docsRoot, parsed.Host, urlPath+".md")
		if data, readErr := os.ReadFile(mdPath); readErr == nil {
			content := string(data)
			title := extractTitle(content, mdPath)
			return content, title, nil
		}

		// Try without .md extension (path might already include it)
		mdPath2 := filepath.Join(docsRoot, parsed.Host, urlPath)
		if data, readErr := os.ReadFile(mdPath2); readErr == nil {
			content := string(data)
			title := extractTitle(content, mdPath2)
			return content, title, nil
		}
	}

	// Try looking up in segment database for path hint
	if t.SegmentDB != "" {
		seg, segErr := storage.OpenSegment(t.SegmentDB)
		if segErr == nil {
			defer seg.Close()
			doc, docErr := seg.GetDocumentByURL(uri)
			if docErr == nil && doc != nil {
				if doc.Body != "" {
					return doc.Body, doc.Title, nil
				}
				if doc.Path != "" {
					path := doc.Path
					if !filepath.IsAbs(path) {
						path = filepath.Join(docsRoot, path)
					}
					if data, readErr := os.ReadFile(path); readErr == nil {
						return string(data), doc.Title, nil
					}
				}
			}
		}
	}

	return "", "", fmt.Errorf("document not found in local cache for %s", uri)
}

func extractTitle(content, filePath string) string {
	for _, line := range strings.SplitN(content, "\n", 10) {
		if strings.HasPrefix(line, "# ") {
			return strings.TrimSpace(line[2:])
		}
	}
	return filepath.Base(filePath)
}
