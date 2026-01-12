"""Conftest for unit tests - automatically mark all tests as unit tests."""

import pytest


def pytest_collection_modifyitems(config, items):
    """Automatically mark all tests in the unit directory as unit tests."""
    for item in items:
        # Add unit marker to all tests in the unit directory
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
