package main

import (
	"fmt"
	"strings"
	"time"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/tenant"
)

func provenanceSummary(provenance tenant.Provenance, now time.Time) string {
	sourceType := provenance.SourceType
	if sourceType == "" {
		sourceType = "unknown"
	}
	indexAge := timestampAge(provenance.IndexCreatedAt, now)
	sourceAge := timestampAge(provenance.Freshness.UpdatedAt, now)
	return fmt.Sprintf(
		"source %s; index %s (%s); version %s; freshness %s %s",
		sourceType,
		indexAge,
		indexStatus(provenance),
		indexedVersion(provenance),
		provenance.Freshness.State,
		sourceAge,
	)
}

func indexStatus(p tenant.Provenance) string {
	if p.IndexStatus == "" {
		return "unknown"
	}
	return p.IndexStatus
}

func indexedVersion(p tenant.Provenance) string {
	if p.IndexedSource == nil {
		return "unknown"
	}
	if p.IndexedSource.Version != "" {
		return p.IndexedSource.Version
	}
	return p.IndexedSource.VersionKind
}

func indexedCount(p tenant.Provenance) string {
	if p.IndexedDocumentCount == nil {
		return "unknown"
	}
	return fmt.Sprint(*p.IndexedDocumentCount)
}

func timestampAge(value string, now time.Time) string {
	parsed, err := time.Parse(time.RFC3339Nano, value)
	if err != nil {
		return "unknown"
	}
	age := now.Sub(parsed)
	if age < 0 {
		age = 0
	}
	switch {
	case age < time.Minute:
		return "now"
	case age < time.Hour:
		return fmt.Sprintf("%dm ago", int(age.Minutes()))
	case age < 24*time.Hour:
		return fmt.Sprintf("%dh ago", int(age.Hours()))
	default:
		return fmt.Sprintf("%dd ago", int(age.Hours()/24))
	}
}

func compactProvenanceSummary(provenance tenant.Provenance) string {
	summary := provenanceSummary(provenance, time.Now().UTC())
	if provenance.IndexedSource != nil {
		return summary + "; indexed source " + provenance.IndexedSource.CanonicalURL
	}
	if len(provenance.CanonicalURLPrefixes) > 0 {
		return summary + "; configured scope " + strings.Join(provenance.CanonicalURLPrefixes, ", ")
	}
	return summary + "; source URL unknown"
}
