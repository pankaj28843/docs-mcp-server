package main

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/output"
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

			reader, err := cfg.reader(cmd.Context())
			if err != nil {
				return err
			}

			tenantCodename := args[0]
			uri := args[1]
			requestedMax := 0
			if maxCharsSet {
				requestedMax = maxChars
			}
			response, err := reader.Fetch(cmd.Context(), tenantCodename, uri, requestedMax)
			if err != nil {
				return backendFailure(err)
			}
			if response.Content == nil {
				return failure(exitDocument, "document", "empty_document", "daemon returned no document content", "inspect docsearchd logs and rebuild the tenant index")
			}

			var artifact *output.ArtifactInfo
			if outSet {
				artifact, err = writeFetchArtifact(outPath, []byte(*response.Content))
				if err != nil {
					return failureWithCause(exitStorage, "storage", "artifact_write_failed", fmt.Sprintf("failed to write fetch output to %s", filepath.Clean(outPath)), err, "choose an existing writable parent directory for --out")
				}
			}

			if w.Format == output.FormatJSON {
				response.Artifact = artifact
				if artifact != nil {
					response.Content = nil
				}
				return w.JSON(response)
			}

			if artifact != nil {
				if response.Provenance != nil {
					w.Text("Provenance: %s\n", compactProvenanceSummary(*response.Provenance))
				}
				w.Text("Wrote %d bytes to %s (sha256 %s)\n", artifact.Bytes, artifact.Path, artifact.SHA256)
				return nil
			}
			if response.Provenance != nil {
				w.Text("Provenance: %s\n\n", compactProvenanceSummary(*response.Provenance))
			}

			if response.Title != "" {
				w.Text("# %s\n\n", response.Title)
			}
			w.Text("%s\n", *response.Content)
			return nil
		},
	}
	cmd.Flags().IntVar(&maxChars, "max-chars", 0, "Return at most this many Unicode characters")
	cmd.Flags().StringVar(&outPath, "out", "", "Atomically write full content to this explicit path")
	return cmd
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
