package main

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/storage"
	"github.com/pankaj28843/docs-mcp-server/cli/internal/tenant"
	"github.com/spf13/cobra"
)

func fetchCmd() *cobra.Command {
	var maxChars int
	var outPath string

	cmd := &cobra.Command{
		Use:   "fetch <tenant> <url>",
		Short: "Fetch full page content by URL",
		Long: `Fetch the full content of a documentation page by URL.

Use this after 'docsearch search' to read the actual documentation content.
The URL should be from search results.

Examples:
  docsearch fetch django "https://docs.djangoproject.com/en/5.2/topics/db/queries/"
  docsearch fetch react "https://react.dev/reference/react/useEffect" --json
  docsearch fetch react URL --json --max-chars 12000
  docsearch fetch react URL --json --out tmp/react-page.md`,
		Args: cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			maxCharsSet := cmd.Flags().Changed("max-chars")
			outSet := cmd.Flags().Changed("out")
			if maxCharsSet && maxChars <= 0 {
				return usageFailure("--max-chars must be greater than zero")
			}
			if outSet && strings.TrimSpace(outPath) == "" {
				return usageFailure("--out requires an explicit destination path")
			}
			if maxCharsSet && outSet {
				return usageFailure("--max-chars and --out cannot be used together")
			}

			cfg := configFromContext(cmd.Context())
			w := cfg.newWriter()
			defer w.Finish()

			reg, err := cfg.newRegistry()
			if err != nil {
				return err
			}

			tenantCodename := args[0]
			uri := args[1]

			t := reg.Get(tenantCodename)
			if t == nil {
				errMsg := fmt.Sprintf("Tenant '%s' not found. Available: %s", tenantCodename, strings.Join(reg.Codenames(), ", "))
				return failure(exitTenant, "tenant", "tenant_not_found", errMsg, "run `docsearch list` to inspect available tenants")
			}

			content, title, err := fetchFromDisk(t, uri)
			if err != nil {
				errMsg := fmt.Sprintf("Document not found: %s", err)
				return failureWithCause(exitDocument, "document", "document_not_found", errMsg, err, "search the tenant again and fetch a URL from the current results")
			}

			boundedContent := content
			var counts *contentCounts
			if maxCharsSet {
				bounded, contentCounts, boundErr := boundUTF8(content, maxChars)
				if boundErr != nil {
					return failureWithCause(exitDocument, "document", "invalid_document_encoding", "document content is not valid UTF-8", boundErr, "rebuild the tenant content as UTF-8")
				}
				boundedContent = bounded
				counts = &contentCounts
			}

			var artifact *output.ArtifactInfo
			if outSet {
				artifact, err = writeFetchArtifact(outPath, []byte(content))
				if err != nil {
					return failureWithCause(exitStorage, "storage", "artifact_write_failed", fmt.Sprintf("failed to write fetch output to %s", filepath.Clean(outPath)), err, "choose an existing writable parent directory for --out")
				}
			}

			if w.Format == output.FormatJSON {
				response := output.FetchResponse{
					Tenant:     tenantCodename,
					URL:        uri,
					Title:      title,
					Content:    &boundedContent,
					Artifact:   artifact,
					Provenance: &t.Provenance,
				}
				if counts != nil {
					response.Truncated = &counts.truncated
					response.OriginalChars = &counts.originalChars
					response.ReturnedChars = &counts.returnedChars
					response.OriginalBytes = &counts.originalBytes
					response.ReturnedBytes = &counts.returnedBytes
				}
				if artifact != nil {
					response.Content = nil
				}
				return w.JSON(response)
			}

			if artifact != nil {
				w.Text("Provenance: %s\n", compactProvenanceSummary(t.Provenance))
				w.Text("Wrote %d bytes to %s (sha256 %s)\n", artifact.Bytes, artifact.Path, artifact.SHA256)
				return nil
			}
			w.Text("Provenance: %s\n\n", compactProvenanceSummary(t.Provenance))

			if title != "" {
				w.Text("# %s\n\n", title)
			}
			w.Text("%s\n", boundedContent)
			return nil
		},
	}
	cmd.Flags().IntVar(&maxChars, "max-chars", 0, "Return at most this many Unicode characters")
	cmd.Flags().StringVar(&outPath, "out", "", "Atomically write full content to this explicit path")
	return cmd
}

type contentCounts struct {
	truncated     bool
	originalChars int
	returnedChars int
	originalBytes int
	returnedBytes int
}

func boundUTF8(content string, maxChars int) (string, contentCounts, error) {
	if !utf8.ValidString(content) {
		return "", contentCounts{}, fmt.Errorf("invalid UTF-8")
	}
	originalChars := utf8.RuneCountInString(content)
	returnedChars := min(originalChars, maxChars)
	returnedBytes := len(content)
	if returnedChars < originalChars {
		runeIndex := 0
		for byteIndex := range content {
			if runeIndex == returnedChars {
				returnedBytes = byteIndex
				break
			}
			runeIndex++
		}
	}
	bounded := content[:returnedBytes]
	return bounded, contentCounts{
		truncated:     returnedChars < originalChars,
		originalChars: originalChars,
		returnedChars: returnedChars,
		originalBytes: len(content),
		returnedBytes: returnedBytes,
	}, nil
}

func writeFetchArtifact(destination string, content []byte) (*output.ArtifactInfo, error) {
	destination = filepath.Clean(destination)
	if err := atomicWriteFile(destination, content); err != nil {
		return nil, err
	}
	digest := sha256.Sum256(content)
	return &output.ArtifactInfo{
		Path:   destination,
		Bytes:  len(content),
		SHA256: hex.EncodeToString(digest[:]),
	}, nil
}

func atomicWriteFile(destination string, content []byte) (err error) {
	dir := filepath.Dir(destination)
	temporary, err := os.CreateTemp(dir, "."+filepath.Base(destination)+".tmp-*")
	if err != nil {
		return fmt.Errorf("create temporary output: %w", err)
	}
	temporaryPath := temporary.Name()
	defer func() {
		if err != nil {
			_ = os.Remove(temporaryPath)
		}
	}()

	if err = temporary.Chmod(0o644); err != nil {
		_ = temporary.Close()
		return fmt.Errorf("set output permissions: %w", err)
	}
	if _, err = temporary.Write(content); err != nil {
		_ = temporary.Close()
		return fmt.Errorf("write temporary output: %w", err)
	}
	if err = temporary.Sync(); err != nil {
		_ = temporary.Close()
		return fmt.Errorf("sync temporary output: %w", err)
	}
	if err = temporary.Close(); err != nil {
		return fmt.Errorf("close temporary output: %w", err)
	}
	if err = os.Rename(temporaryPath, destination); err != nil {
		return fmt.Errorf("replace output: %w", err)
	}
	return nil
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
