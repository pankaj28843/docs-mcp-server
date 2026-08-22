// Package service provides the read-only documentation operations shared by
// the CLI and daemon transports.
package service

// Error is a stable domain failure suitable for transport mapping.
type Error struct {
	Code    string
	Message string
	Cause   error
}

func NewError(code, message string) *Error {
	return &Error{Code: code, Message: message}
}

func WrapError(code, message string, cause error) *Error {
	return &Error{Code: code, Message: message, Cause: cause}
}

func (e *Error) Error() string {
	return e.Message
}

func (e *Error) Unwrap() error {
	return e.Cause
}
