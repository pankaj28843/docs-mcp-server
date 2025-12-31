"""Unit tests for the YAML front-matter helpers."""

import pytest
import yaml

from docs_mcp_server.utils import front_matter


pytestmark = pytest.mark.unit


def test_parse_front_matter_returns_metadata_and_body() -> None:
    content = "-----\nstatus: success\ntitle: Hello\n-----\n# Body\nContent\n"

    metadata, body = front_matter.parse_front_matter(content)

    assert metadata == {"status": "success", "title": "Hello"}
    assert body.strip() == "# Body\nContent"


def test_parse_front_matter_invalid_yaml_returns_original_content() -> None:
    content = "-----\n:broken\n-----\n# So bad\n"

    metadata, body = front_matter.parse_front_matter(content)

    assert metadata == {}
    assert body == content


def test_parse_front_matter_non_mapping_yaml_returns_empty() -> None:
    content = "-----\n- 1\n- 2\n-----\nNo metadata\n"

    metadata, body = front_matter.parse_front_matter(content)

    assert metadata == {}
    assert body == content


def test_parse_front_matter_gracefully_handles_yaml_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure YAML parsing failures fall back to original markdown."""

    content = "-----\nkey: value\n-----\n# Body\n"

    def _raise_error(*args: object, **kwargs: object) -> None:
        raise yaml.YAMLError("boom")

    monkeypatch.setattr(front_matter.yaml, "safe_load", _raise_error)

    metadata, body = front_matter.parse_front_matter(content)

    assert metadata == {}
    assert body == content


def test_serialize_and_update_front_matter_preserve_sorted_keys() -> None:
    base = "# Hello\n"
    serialized = front_matter.serialize_front_matter({"b": 2, "a": 1}, base)

    # Keys are sorted for determinism
    assert serialized.splitlines()[1:3] == ["a: 1", "b: 2"]


def test_serialize_without_metadata_returns_original_body() -> None:
    body = "# Only markdown\n"
    assert front_matter.serialize_front_matter({}, body) == body
