package main

import (
	"errors"
	"fmt"
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
