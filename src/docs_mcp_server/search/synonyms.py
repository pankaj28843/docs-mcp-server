"""Synonym expansion for search queries.

This module provides synonym expansion as a smart default for search.
Common technical abbreviations are automatically expanded to improve
recall without requiring per-tenant configuration.

Example:
    - "async" expands to {"async", "asynchronous"}
    - "auth" expands to {"auth", "authentication", "authorization"}
    - "config" expands to {"config", "configuration", "configure"}
"""
# ruff: noqa: ERA001  # Comments are intentional documentation, not commented-out code

from __future__ import annotations

from collections.abc import Mapping, Sequence


# Default synonyms for technical documentation.
# These are common abbreviations and their full forms.
# The mapping is bidirectional for lookup.
#
# Based on keyword analysis of 72 tenants with 2150+ unique keywords.
# Top keywords: server, model, configuration, version, request, user,
# resource, service, state, query, environment, etc.
DEFAULT_SYNONYMS: dict[str, set[str]] = {
    # Async/synchronous
    "async": {"async", "asynchronous"},
    "asynchronous": {"async", "asynchronous"},
    "sync": {"sync", "synchronous"},
    "synchronous": {"sync", "synchronous"},
    # Authentication/authorization
    "auth": {"auth", "authentication", "authorization"},
    "authentication": {"auth", "authentication"},
    "authorization": {"auth", "authorization"},
    # Configuration (most common: 41K+ occurrences)
    "config": {"config", "configuration", "configure", "configs"},
    "configuration": {"config", "configuration", "configure", "configs"},
    "configure": {"config", "configuration", "configure", "configs"},
    "configs": {"config", "configuration", "configure", "configs"},
    # Database
    "db": {"db", "database", "databases"},
    "database": {"db", "database", "databases"},
    "databases": {"db", "database", "databases"},
    # Environment (12K+ occurrences)
    "env": {"env", "environment", "environments"},
    "environment": {"env", "environment", "environments"},
    "environments": {"env", "environment", "environments"},
    # Repository
    "repo": {"repo", "repository", "repositories"},
    "repository": {"repo", "repository", "repositories"},
    "repositories": {"repo", "repository", "repositories"},
    # Application (15K+ occurrences)
    "app": {"app", "application", "applications"},
    "application": {"app", "application", "applications"},
    "applications": {"app", "application", "applications"},
    # Request/response (35K+/16K+ occurrences)
    "req": {"req", "request", "requests"},
    "request": {"req", "request", "requests"},
    "requests": {"req", "request", "requests"},
    "res": {"res", "response", "responses"},
    "response": {"res", "response", "responses"},
    "responses": {"res", "response", "responses"},
    # Documentation
    "doc": {"doc", "docs", "documentation"},
    "docs": {"doc", "docs", "documentation"},
    "documentation": {"doc", "docs", "documentation"},
    # Parameter/argument
    "param": {"param", "parameter", "parameters", "params"},
    "parameter": {"param", "parameter", "parameters", "params"},
    "parameters": {"param", "parameter", "parameters", "params"},
    "params": {"param", "parameter", "parameters", "params"},
    "arg": {"arg", "argument", "arguments", "args"},
    "argument": {"arg", "argument", "arguments", "args"},
    "arguments": {"arg", "argument", "arguments", "args"},
    "args": {"arg", "argument", "arguments", "args"},
    # Function/method
    "func": {"func", "function", "functions"},
    "function": {"func", "function", "functions"},
    "functions": {"func", "function", "functions"},
    "method": {"method", "methods"},
    "methods": {"method", "methods"},
    # Message
    "msg": {"msg", "message", "messages"},
    "message": {"msg", "message", "messages"},
    "messages": {"msg", "message", "messages"},
    # Object
    "obj": {"obj", "object", "objects"},
    "object": {"obj", "object", "objects"},
    "objects": {"obj", "object", "objects"},
    # Error/exception (17K+/3K+ occurrences)
    "err": {"err", "error", "errors"},
    "error": {"err", "error", "errors"},
    "errors": {"err", "error", "errors"},
    "exc": {"exc", "exception", "exceptions"},
    "exception": {"exc", "exception", "exceptions"},
    "exceptions": {"exc", "exception", "exceptions"},
    # Server/service (50K+/24K+ occurrences)
    "srv": {"srv", "server", "servers"},
    "server": {"srv", "server", "servers"},
    "servers": {"srv", "server", "servers"},
    "svc": {"svc", "service", "services"},
    "service": {"svc", "service", "services"},
    "services": {"svc", "service", "services"},
    # Model (48K+ occurrences)
    "model": {"model", "models"},
    "models": {"model", "models"},
    # Resource (31K+ occurrences)
    "resource": {"resource", "resources"},
    "resources": {"resource", "resources"},
    # Query (14K+ occurrences)
    "query": {"query", "queries"},
    "queries": {"query", "queries"},
    # Task (14K+ occurrences)
    "task": {"task", "tasks"},
    "tasks": {"task", "tasks"},
    # Event (12K+ occurrences)
    "event": {"event", "events"},
    "events": {"event", "events"},
    # Component (11K+ occurrences)
    "component": {"component", "components"},
    "components": {"component", "components"},
    # Container (11K+ occurrences)
    "container": {"container", "containers"},
    "containers": {"container", "containers"},
    # Token (16K+ occurrences)
    "token": {"token", "tokens"},
    "tokens": {"token", "tokens"},
    # Create/creation (28K+ occurrences)
    "create": {"create", "creates", "creating", "created", "creation"},
    "creates": {"create", "creates", "creating", "created", "creation"},
    "creating": {"create", "creates", "creating", "created", "creation"},
    "created": {"create", "creates", "creating", "created", "creation"},
    "creation": {"create", "creates", "creating", "created", "creation"},
    # Build (10K+ occurrences)
    "build": {"build", "builds", "building", "built"},
    "builds": {"build", "builds", "building", "built"},
    "building": {"build", "builds", "building", "built"},
    "built": {"build", "builds", "building", "built"},
    # Deploy/deployment
    "deploy": {"deploy", "deploys", "deploying", "deployed", "deployment", "deployments"},
    "deploys": {"deploy", "deploys", "deploying", "deployed", "deployment", "deployments"},
    "deploying": {"deploy", "deploys", "deploying", "deployed", "deployment", "deployments"},
    "deployed": {"deploy", "deploys", "deploying", "deployed", "deployment", "deployments"},
    "deployment": {"deploy", "deploys", "deploying", "deployed", "deployment", "deployments"},
    "deployments": {"deploy", "deploys", "deploying", "deployed", "deployment", "deployments"},
    # Install/installation
    "install": {"install", "installs", "installing", "installed", "installation"},
    "installs": {"install", "installs", "installing", "installed", "installation"},
    "installing": {"install", "installs", "installing", "installed", "installation"},
    "installed": {"install", "installs", "installing", "installed", "installation"},
    "installation": {"install", "installs", "installing", "installed", "installation"},
    # Update (common verb)
    "update": {"update", "updates", "updating", "updated"},
    "updates": {"update", "updates", "updating", "updated"},
    "updating": {"update", "updates", "updating", "updated"},
    "updated": {"update", "updates", "updating", "updated"},
    # Delete/remove
    "delete": {"delete", "deletes", "deleting", "deleted", "deletion"},
    "deletes": {"delete", "deletes", "deleting", "deleted", "deletion"},
    "deleting": {"delete", "deletes", "deleting", "deleted", "deletion"},
    "deleted": {"delete", "deletes", "deleting", "deleted", "deletion"},
    "deletion": {"delete", "deletes", "deleting", "deleted", "deletion"},
    "remove": {"remove", "removes", "removing", "removed", "removal"},
    "removes": {"remove", "removes", "removing", "removed", "removal"},
    "removing": {"remove", "removes", "removing", "removed", "removal"},
    "removed": {"remove", "removes", "removing", "removed", "removal"},
    "removal": {"remove", "removes", "removing", "removed", "removal"},
    # Validate/validation
    "validate": {"validate", "validates", "validating", "validated", "validation"},
    "validates": {"validate", "validates", "validating", "validated", "validation"},
    "validating": {"validate", "validates", "validating", "validated", "validation"},
    "validated": {"validate", "validates", "validating", "validated", "validation"},
    "validation": {"validate", "validates", "validating", "validated", "validation"},
    # Test (16K+ occurrences)
    "test": {"test", "tests", "testing", "tested"},
    "tests": {"test", "tests", "testing", "tested"},
    "testing": {"test", "tests", "testing", "tested"},
    "tested": {"test", "tests", "testing", "tested"},
    # Execute/execution
    "exec": {"exec", "execute", "executes", "executing", "executed", "execution"},
    "execute": {"exec", "execute", "executes", "executing", "executed", "execution"},
    "executes": {"exec", "execute", "executes", "executing", "executed", "execution"},
    "executing": {"exec", "execute", "executes", "executing", "executed", "execution"},
    "executed": {"exec", "execute", "executes", "executing", "executed", "execution"},
    "execution": {"exec", "execute", "executes", "executing", "executed", "execution"},
    # Specify/specification
    "spec": {"spec", "specs", "specify", "specifies", "specified", "specification"},
    "specs": {"spec", "specs", "specify", "specifies", "specified", "specification"},
    "specify": {"spec", "specs", "specify", "specifies", "specified", "specification"},
    "specifies": {"spec", "specs", "specify", "specifies", "specified", "specification"},
    "specified": {"spec", "specs", "specify", "specifies", "specified", "specification"},
    "specification": {"spec", "specs", "specify", "specifies", "specified", "specification"},
    # Initialize/init
    "init": {"init", "initialize", "initializes", "initialized", "initialization"},
    "initialize": {"init", "initialize", "initializes", "initialized", "initialization"},
    "initializes": {"init", "initialize", "initializes", "initialized", "initialization"},
    "initialized": {"init", "initialize", "initializes", "initialized", "initialization"},
    "initialization": {"init", "initialize", "initializes", "initialized", "initialization"},
    # Serialize/serialization (common in DRF, FastAPI)
    "serialize": {"serialize", "serializes", "serializing", "serialized", "serialization", "serializer"},
    "serializes": {"serialize", "serializes", "serializing", "serialized", "serialization", "serializer"},
    "serializing": {"serialize", "serializes", "serializing", "serialized", "serialization", "serializer"},
    "serialized": {"serialize", "serializes", "serializing", "serialized", "serialization", "serializer"},
    "serialization": {"serialize", "serializes", "serializing", "serialized", "serialization", "serializer"},
    "serializer": {"serialize", "serializes", "serializing", "serialized", "serialization", "serializer"},
    # Cluster (15K+ occurrences - k8s, AWS)
    "cluster": {"cluster", "clusters"},
    "clusters": {"cluster", "clusters"},
    # Node
    "node": {"node", "nodes"},
    "nodes": {"node", "nodes"},
    # Endpoint
    "endpoint": {"endpoint", "endpoints"},
    "endpoints": {"endpoint", "endpoints"},
    # Route/routing
    "route": {"route", "routes", "routing", "router"},
    "routes": {"route", "routes", "routing", "router"},
    "routing": {"route", "routes", "routing", "router"},
    "router": {"route", "routes", "routing", "router"},
    # API (common abbreviation)
    "api": {"api", "apis"},
    "apis": {"api", "apis"},
    # URL
    "url": {"url", "urls"},
    "urls": {"url", "urls"},
    # Schema
    "schema": {"schema", "schemas"},
    "schemas": {"schema", "schemas"},
    # Template
    "template": {"template", "templates"},
    "templates": {"template", "templates"},
    # Session
    "session": {"session", "sessions"},
    "sessions": {"session", "sessions"},
    # Permission
    "perm": {"perm", "perms", "permission", "permissions"},
    "perms": {"perm", "perms", "permission", "permissions"},
    "permission": {"perm", "perms", "permission", "permissions"},
    "permissions": {"perm", "perms", "permission", "permissions"},
    # View (11K+ occurrences - Django, React)
    "view": {"view", "views"},
    "views": {"view", "views"},
    # Handler
    "handler": {"handler", "handlers"},
    "handlers": {"handler", "handlers"},
    # Middleware
    "middleware": {"middleware", "middlewares"},
    "middlewares": {"middleware", "middlewares"},
    # Provider (16K+ occurrences - Terraform, OAuth)
    "provider": {"provider", "providers"},
    "providers": {"provider", "providers"},
    # Agent (16K+ occurrences - AI/ML)
    "agent": {"agent", "agents"},
    "agents": {"agent", "agents"},
    # Policy (13K+ occurrences - AWS, security)
    "policy": {"policy", "policies"},
    "policies": {"policy", "policies"},
    # Callback
    "callback": {"callback", "callbacks"},
    "callbacks": {"callback", "callbacks"},
    # Pipeline
    "pipeline": {"pipeline", "pipelines"},
    "pipelines": {"pipeline", "pipelines"},
    # Workflow
    "workflow": {"workflow", "workflows"},
    "workflows": {"workflow", "workflows"},
    # Credential
    "cred": {"cred", "creds", "credential", "credentials"},
    "creds": {"cred", "creds", "credential", "credentials"},
    "credential": {"cred", "creds", "credential", "credentials"},
    "credentials": {"cred", "creds", "credential", "credentials"},
    # Secret
    "secret": {"secret", "secrets"},
    "secrets": {"secret", "secrets"},
    # Variable
    "var": {"var", "vars", "variable", "variables"},
    "vars": {"var", "vars", "variable", "variables"},
    "variable": {"var", "vars", "variable", "variables"},
    "variables": {"var", "vars", "variable", "variables"},
    # Attribute
    "attr": {"attr", "attrs", "attribute", "attributes"},
    "attrs": {"attr", "attrs", "attribute", "attributes"},
    "attribute": {"attr", "attrs", "attribute", "attributes"},
    "attributes": {"attr", "attrs", "attribute", "attributes"},
    # Instance
    "instance": {"instance", "instances"},
    "instances": {"instance", "instances"},
    # Class
    "cls": {"cls", "class", "classes"},
    "class": {"cls", "class", "classes"},
    "classes": {"cls", "class", "classes"},
    # Module (27K+ occurrences)
    "mod": {"mod", "module", "modules"},
    "module": {"mod", "module", "modules"},
    "modules": {"mod", "module", "modules"},
    # Package
    "pkg": {"pkg", "package", "packages"},
    "package": {"pkg", "package", "packages"},
    "packages": {"pkg", "package", "packages"},
    # Directory
    "dir": {"dir", "dirs", "directory", "directories"},
    "dirs": {"dir", "dirs", "directory", "directories"},
    "directory": {"dir", "dirs", "directory", "directories"},
    "directories": {"dir", "dirs", "directory", "directories"},
    # Framework
    "framework": {"framework", "frameworks"},
    "frameworks": {"framework", "frameworks"},
    # Library
    "lib": {"lib", "libs", "library", "libraries"},
    "libs": {"lib", "libs", "library", "libraries"},
    "library": {"lib", "libs", "library", "libraries"},
    "libraries": {"lib", "libs", "library", "libraries"},
    # Dependency
    "dep": {"dep", "deps", "dependency", "dependencies"},
    "deps": {"dep", "deps", "dependency", "dependencies"},
    "dependency": {"dep", "deps", "dependency", "dependencies"},
    "dependencies": {"dep", "deps", "dependency", "dependencies"},
    # Command (19K+ occurrences)
    "cmd": {"cmd", "command", "commands"},
    "command": {"cmd", "command", "commands"},
    "commands": {"cmd", "command", "commands"},
    # Version (37K+ occurrences)
    "ver": {"ver", "version", "versions"},
    "version": {"ver", "version", "versions"},
    "versions": {"ver", "version", "versions"},
    # Settings
    "setting": {"setting", "settings"},
    "settings": {"setting", "settings"},
    # Option
    "opt": {"opt", "option", "options"},
    "option": {"opt", "option", "options"},
    "options": {"opt", "option", "options"},
    # Field (26K+ occurrences)
    "field": {"field", "fields"},
    "fields": {"field", "fields"},
    # State (25K+ occurrences)
    "state": {"state", "states"},
    "states": {"state", "states"},
    # Context
    "ctx": {"ctx", "context", "contexts"},
    "context": {"ctx", "context", "contexts"},
    "contexts": {"ctx", "context", "contexts"},
    # Connection
    "conn": {"conn", "connection", "connections"},
    "connection": {"conn", "connection", "connections"},
    "connections": {"conn", "connection", "connections"},
}


class SynonymExpander:
    """Expands terms to include their synonyms.

    This is a smart default that improves search recall without
    requiring per-tenant configuration.
    """

    def __init__(self, synonyms: Mapping[str, set[str]] | None = None) -> None:
        """Initialize with synonym mappings.

        Args:
            synonyms: Custom synonym mappings. If None, uses DEFAULT_SYNONYMS.
        """
        self._synonyms = dict(synonyms) if synonyms is not None else DEFAULT_SYNONYMS

    def expand(self, term: str) -> set[str]:
        """Expand a single term to include synonyms.

        Args:
            term: The term to expand.

        Returns:
            Set containing the term and all its synonyms.
        """
        normalized = term.lower()
        if normalized in self._synonyms:
            result = self._synonyms[normalized].copy()
            result.add(normalized)  # Always include the original term
            return result
        return {normalized}


def expand_query_terms(
    terms: Sequence[str],
    synonyms: Mapping[str, set[str]] | None = None,
) -> set[str]:
    """Expand all query terms to include synonyms.

    Args:
        terms: List of query terms to expand.
        synonyms: Optional custom synonym mappings.

    Returns:
        Set of all terms including synonyms.
    """
    if not terms:
        return set()

    expander = SynonymExpander(synonyms)
    expanded: set[str] = set()

    for term in terms:
        expanded.update(expander.expand(term))

    return expanded
