package main

import (
	"fmt"
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
		"source %s; index %s; freshness %s %s",
		sourceType,
		indexAge,
		provenance.Freshness.State,
		sourceAge,
	)
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
	return provenanceSummary(provenance, time.Now().UTC())
}
