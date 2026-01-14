"""Additional unit tests for SyncProgress transitions."""

from __future__ import annotations

import pytest

from docs_mcp_server.domain.sync_progress import InvalidPhaseTransitionError, SyncPhase, SyncProgress


@pytest.mark.unit
def test_resume_raises_when_phase_not_resumable():
    progress = SyncProgress.create_new("tenant")
    progress.phase = SyncPhase.COMPLETED

    with pytest.raises(InvalidPhaseTransitionError, match="Cannot resume"):
        progress.resume()


@pytest.mark.unit
def test_transition_to_same_phase_is_noop():
    progress = SyncProgress.create_new("tenant")
    progress.phase = SyncPhase.DISCOVERING

    progress._transition_to(SyncPhase.DISCOVERING)

    assert progress.phase == SyncPhase.DISCOVERING
