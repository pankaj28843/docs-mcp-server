"""Checks for stable Go release selection."""

import pytest

from docs_mcp_server.snapshots.go_release_notes import latest_release_url


@pytest.mark.unit
def test_selects_highest_stable_release() -> None:
    select = latest_release_url
    assert (
        select(
            [
                {"version": "go1.27.1", "stable": True},
                {"version": "go1.28rc1", "stable": False},
                {"version": "go1.26.12", "stable": True},
            ]
        )
        == "https://go.dev/doc/go1.27"
    )
    with pytest.raises(ValueError, match="no stable"):
        select([{"version": "go1.28rc1", "stable": False}])
