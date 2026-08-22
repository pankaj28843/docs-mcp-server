package main

import (
	"errors"
	"fmt"

	"github.com/pankaj28843/docs-mcp-server/cli/internal/service"
)

const (
	exitOK       = 0
	exitInternal = 1
	exitUsage    = 2
	exitStorage  = 3
	exitTenant   = 4
	exitIndex    = 5
	exitDocument = 6
)

type errorDetail struct {
	Code    string   `json:"code"`
	Class   string   `json:"class"`
	Message string   `json:"message"`
	Actions []string `json:"actions"`
}

func backendFailure(err error) error {
	var domainErr *service.Error
	if !errors.As(err, &domainErr) {
		return err
	}
	switch domainErr.Code {
	case "tenant_not_found":
		return failureWithCause(exitTenant, "tenant", domainErr.Code, domainErr.Message, err, "run `docsearch list` to inspect available tenants")
	case "index_unavailable":
		return failureWithCause(exitIndex, "index", domainErr.Code, domainErr.Message, err, "sync or import the tenant and rebuild its search index")
	case "document_not_found", "invalid_document_encoding":
		return failureWithCause(exitDocument, "document", domainErr.Code, domainErr.Message, err, "search the tenant again and fetch a URL from the current results")
	case "remote_unavailable", "remote_error":
		return failureWithCause(exitStorage, "remote", domainErr.Code, domainErr.Message, err, "verify docsearchd is running and server_url is reachable")
	default:
		return failureWithCause(exitInternal, "internal", domainErr.Code, domainErr.Message, err, "inspect docsearchd logs and retry")
	}
}

type errorResponse struct {
	Error errorDetail `json:"error"`
}

type commandError struct {
	detail   errorDetail
	exitCode int
	cause    error
}

func (e *commandError) Error() string {
	return e.detail.Message
}

func (e *commandError) Unwrap() error {
	return e.cause
}

func failure(exitCode int, class, code, message string, actions ...string) error {
	return &commandError{
		detail: errorDetail{
			Code:    code,
			Class:   class,
			Message: message,
			Actions: actions,
		},
		exitCode: exitCode,
	}
}

func failureWithCause(exitCode int, class, code, message string, cause error, actions ...string) error {
	err := failure(exitCode, class, code, message, actions...).(*commandError)
	err.cause = cause
	return err
}

func usageFailure(format string, args ...any) error {
	return failure(
		exitUsage,
		"usage",
		"invalid_argument",
		fmt.Sprintf(format, args...),
		"run the command with --help to inspect valid arguments and limits",
	)
}

func classifyFailure(err error) *commandError {
	var classified *commandError
	if errors.As(err, &classified) {
		return classified
	}
	return &commandError{
		detail: errorDetail{
			Code:    "internal_error",
			Class:   "internal",
			Message: err.Error(),
			Actions: []string{"retry with --timing or inspect the local data and index state"},
		},
		exitCode: exitInternal,
		cause:    err,
	}
}
