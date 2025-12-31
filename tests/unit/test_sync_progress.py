"""Unit tests for SyncProgress domain model.

Tests the resilient sync progress tracking that enables:
- Checkpoint-based resume after interruption (DDIA pattern)
- Domain events for sync lifecycle (Cosmic Python pattern)
- Idempotent URL processing
- Progress persistence across container restarts

Following TDD: these tests are written FIRST, implementation follows.
"""

from datetime import datetime, timedelta, timezone
import json
from uuid import UUID

import pytest


# Import will fail until we implement the domain model
# This is intentional for TDD
@pytest.fixture
def sync_progress_module():
    """Import the sync progress module."""
    from docs_mcp_server.domain import sync_progress

    return sync_progress


@pytest.mark.unit
class TestSyncPhase:
    """Tests for SyncPhase enum."""

    def test_phase_values_exist(self, sync_progress_module):
        """All expected phases are defined."""
        sync_phase = sync_progress_module.SyncPhase

        assert sync_phase.INITIALIZING.value == "initializing"
        assert sync_phase.DISCOVERING.value == "discovering"
        assert sync_phase.FETCHING.value == "fetching"
        assert sync_phase.COMPLETED.value == "completed"
        assert sync_phase.FAILED.value == "failed"
        assert sync_phase.INTERRUPTED.value == "interrupted"

    def test_is_terminal_phase(self, sync_progress_module):
        """Terminal phases correctly identified."""
        sync_phase = sync_progress_module.SyncPhase

        assert sync_phase.COMPLETED.is_terminal is True
        assert sync_phase.FAILED.is_terminal is True
        assert sync_phase.INTERRUPTED.is_terminal is False  # Can resume
        assert sync_phase.FETCHING.is_terminal is False
        assert sync_phase.DISCOVERING.is_terminal is False

    def test_can_resume_from_phase(self, sync_progress_module):
        """Only certain phases allow resumption."""
        sync_phase = sync_progress_module.SyncPhase

        assert sync_phase.INTERRUPTED.can_resume is True
        assert sync_phase.FETCHING.can_resume is True  # Can resume mid-fetch
        assert sync_phase.DISCOVERING.can_resume is True
        assert sync_phase.COMPLETED.can_resume is False
        assert sync_phase.FAILED.can_resume is False  # Need fresh start


@pytest.mark.unit
class TestSyncStats:
    """Tests for SyncStats value object."""

    def test_create_empty_stats(self, sync_progress_module):
        """Stats initialize to zero."""
        sync_stats = sync_progress_module.SyncStats

        stats = sync_stats()
        assert stats.urls_discovered == 0
        assert stats.urls_pending == 0
        assert stats.urls_processed == 0
        assert stats.urls_failed == 0
        assert stats.urls_skipped == 0

    def test_stats_to_dict(self, sync_progress_module):
        """Stats serialize to dictionary."""
        sync_stats = sync_progress_module.SyncStats

        stats = sync_stats(
            urls_discovered=100,
            urls_pending=50,
            urls_processed=45,
            urls_failed=5,
            urls_skipped=10,
        )
        result = stats.to_dict()

        assert result["urls_discovered"] == 100
        assert result["urls_pending"] == 50
        assert result["urls_processed"] == 45
        assert result["urls_failed"] == 5
        assert result["urls_skipped"] == 10

    def test_stats_from_dict(self, sync_progress_module):
        """Stats deserialize from dictionary."""
        sync_stats = sync_progress_module.SyncStats

        data = {
            "urls_discovered": 200,
            "urls_pending": 100,
            "urls_processed": 90,
            "urls_failed": 10,
            "urls_skipped": 20,
        }
        stats = sync_stats.from_dict(data)

        assert stats.urls_discovered == 200
        assert stats.urls_processed == 90


@pytest.mark.unit
class TestFailureInfo:
    """Tests for FailureInfo value object."""

    def test_create_failure_info(self, sync_progress_module):
        """FailureInfo captures error details."""
        failure_info = sync_progress_module.FailureInfo

        now = datetime.now(timezone.utc)
        info = failure_info(
            url="https://example.com/broken",
            error_type="HTTPError",
            error_message="404 Not Found",
            failed_at=now,
            retry_count=3,
        )

        assert info.url == "https://example.com/broken"
        assert info.error_type == "HTTPError"
        assert info.error_message == "404 Not Found"
        assert info.failed_at == now
        assert info.retry_count == 3

    def test_failure_info_roundtrip(self, sync_progress_module):
        """FailureInfo serialization roundtrip."""
        failure_info = sync_progress_module.FailureInfo

        now = datetime.now(timezone.utc)
        original = failure_info(
            url="https://example.com/error",
            error_type="TimeoutError",
            error_message="Connection timed out",
            failed_at=now,
            retry_count=2,
        )

        data = original.to_dict()
        restored = failure_info.from_dict(data)

        assert restored.url == original.url
        assert restored.error_type == original.error_type
        assert restored.retry_count == original.retry_count


@pytest.mark.unit
class TestSyncProgressCreation:
    """Tests for SyncProgress aggregate creation."""

    def test_create_new_sync_progress(self, sync_progress_module):
        """New SyncProgress initializes correctly."""
        sync_progress = sync_progress_module.SyncProgress
        sync_phase = sync_progress_module.SyncPhase

        progress = sync_progress.create_new(tenant_codename="django")

        assert progress.tenant_codename == "django"
        assert progress.phase == sync_phase.INITIALIZING
        assert isinstance(progress.sync_id, UUID)
        assert progress.started_at is not None
        assert progress.completed_at is None
        assert len(progress.discovered_urls) == 0
        assert len(progress.pending_urls) == 0
        assert len(progress.processed_urls) == 0

    def test_create_generates_unique_ids(self, sync_progress_module):
        """Each new SyncProgress has unique sync_id."""
        sync_progress = sync_progress_module.SyncProgress

        progress1 = sync_progress.create_new(tenant_codename="django")
        progress2 = sync_progress.create_new(tenant_codename="django")

        assert progress1.sync_id != progress2.sync_id

    def test_create_with_existing_id(self, sync_progress_module):
        """Can create SyncProgress with specific sync_id for restoration."""
        sync_progress = sync_progress_module.SyncProgress
        from uuid import uuid4

        existing_id = uuid4()
        progress = sync_progress.create_new(
            tenant_codename="fastapi",
            sync_id=existing_id,
        )

        assert progress.sync_id == existing_id


@pytest.mark.unit
class TestSyncProgressPhaseTransitions:
    """Tests for SyncProgress phase state machine."""

    def test_start_discovery(self, sync_progress_module):
        """Transition from initializing to discovering."""
        sync_progress = sync_progress_module.SyncProgress
        sync_phase = sync_progress_module.SyncPhase

        progress = sync_progress.create_new(tenant_codename="django")
        progress.start_discovery()

        assert progress.phase == sync_phase.DISCOVERING

    def test_cannot_start_discovery_from_completed(self, sync_progress_module):
        """Cannot start discovery after completion."""
        sync_progress = sync_progress_module.SyncProgress

        progress = sync_progress.create_new(tenant_codename="django")
        progress.start_discovery()
        progress.start_fetching()
        progress.mark_completed()

        with pytest.raises(sync_progress_module.InvalidPhaseTransitionError):
            progress.start_discovery()

    def test_start_fetching(self, sync_progress_module):
        """Transition from discovering to fetching."""
        sync_progress = sync_progress_module.SyncProgress
        sync_phase = sync_progress_module.SyncPhase

        progress = sync_progress.create_new(tenant_codename="django")
        progress.start_discovery()
        progress.start_fetching()

        assert progress.phase == sync_phase.FETCHING

    def test_mark_completed(self, sync_progress_module):
        """Transition to completed state."""
        sync_progress = sync_progress_module.SyncProgress
        sync_phase = sync_progress_module.SyncPhase

        progress = sync_progress.create_new(tenant_codename="django")
        progress.start_discovery()
        progress.start_fetching()
        progress.mark_completed()

        assert progress.phase == sync_phase.COMPLETED
        assert progress.completed_at is not None

    def test_mark_failed(self, sync_progress_module):
        """Transition to failed state with error."""
        sync_progress = sync_progress_module.SyncProgress
        sync_phase = sync_progress_module.SyncPhase

        progress = sync_progress.create_new(tenant_codename="django")
        progress.start_discovery()
        progress.mark_failed(error="Network timeout during discovery")

        assert progress.phase == sync_phase.FAILED
        assert progress.failure_reason == "Network timeout during discovery"


@pytest.mark.unit
class TestSyncProgressUrlTracking:
    """Tests for URL tracking within SyncProgress."""

    def test_add_discovered_urls(self, sync_progress_module):
        """Add URLs during discovery phase."""
        sync_progress = sync_progress_module.SyncProgress

        progress = sync_progress.create_new(tenant_codename="django")
        progress.start_discovery()

        urls = {
            "https://docs.djangoproject.com/page1/",
            "https://docs.djangoproject.com/page2/",
            "https://docs.djangoproject.com/page3/",
        }
        progress.add_discovered_urls(urls)

        assert progress.discovered_urls == urls
        assert progress.pending_urls == urls
        assert progress.stats.urls_discovered == 3
        assert progress.stats.urls_pending == 3

    def test_add_discovered_urls_idempotent(self, sync_progress_module):
        """Adding same URLs multiple times is idempotent."""
        sync_progress = sync_progress_module.SyncProgress

        progress = sync_progress.create_new(tenant_codename="django")
        progress.start_discovery()

        urls = {"https://example.com/page1/", "https://example.com/page2/"}
        progress.add_discovered_urls(urls)
        progress.add_discovered_urls(urls)  # Duplicate add
        progress.add_discovered_urls({"https://example.com/page1/"})  # Partial overlap

        assert len(progress.discovered_urls) == 2
        assert progress.stats.urls_discovered == 2

    def test_mark_url_processed(self, sync_progress_module):
        """Mark URL as successfully processed."""
        sync_progress = sync_progress_module.SyncProgress

        progress = sync_progress.create_new(tenant_codename="django")
        progress.start_discovery()
        progress.add_discovered_urls({"https://example.com/page1/", "https://example.com/page2/"})
        progress.start_fetching()

        progress.mark_url_processed("https://example.com/page1/")

        assert "https://example.com/page1/" in progress.processed_urls
        assert "https://example.com/page1/" not in progress.pending_urls
        assert progress.stats.urls_processed == 1
        assert progress.stats.urls_pending == 1

    def test_mark_url_failed(self, sync_progress_module):
        """Mark URL as failed with error info."""
        sync_progress = sync_progress_module.SyncProgress

        progress = sync_progress.create_new(tenant_codename="django")
        progress.start_discovery()
        progress.add_discovered_urls({"https://example.com/broken/"})
        progress.start_fetching()

        progress.mark_url_failed(
            url="https://example.com/broken/",
            error_type="HTTPError",
            error_message="500 Internal Server Error",
        )

        assert "https://example.com/broken/" in progress.failed_urls
        assert "https://example.com/broken/" not in progress.pending_urls
        assert progress.stats.urls_failed == 1

        failure = progress.failed_urls["https://example.com/broken/"]
        assert failure.error_type == "HTTPError"
        assert failure.retry_count == 1

    def test_mark_url_failed_increments_retry_count(self, sync_progress_module):
        """Repeated failures increment retry count."""
        sync_progress = sync_progress_module.SyncProgress

        progress = sync_progress.create_new(tenant_codename="django")
        progress.start_discovery()
        progress.add_discovered_urls({"https://example.com/flaky/"})
        progress.start_fetching()

        # First failure
        progress.mark_url_failed(
            url="https://example.com/flaky/",
            error_type="TimeoutError",
            error_message="Timeout",
        )
        assert progress.failed_urls["https://example.com/flaky/"].retry_count == 1

        # Simulate re-queue for retry by manually adding back to pending
        progress.pending_urls.add("https://example.com/flaky/")
        assert "https://example.com/flaky/" in progress.pending_urls

        # Second failure
        progress.mark_url_failed(
            url="https://example.com/flaky/",
            error_type="TimeoutError",
            error_message="Timeout again",
        )
        assert progress.failed_urls["https://example.com/flaky/"].retry_count == 2

    def test_mark_url_skipped(self, sync_progress_module):
        """Mark URL as skipped (recently fetched, cache hit)."""
        sync_progress = sync_progress_module.SyncProgress

        progress = sync_progress.create_new(tenant_codename="django")
        progress.start_discovery()
        progress.add_discovered_urls({"https://example.com/cached/"})
        progress.start_fetching()

        progress.mark_url_skipped("https://example.com/cached/", reason="cache_hit")

        assert "https://example.com/cached/" not in progress.pending_urls
        assert progress.stats.urls_skipped == 1

    def test_enqueue_urls_adds_pending(self, sync_progress_module):
        """enqueue_urls adds URLs without double-counting processed ones."""
        sync_progress = sync_progress_module.SyncProgress

        progress = sync_progress.create_new(tenant_codename="django")
        progress.start_discovery()
        progress.add_discovered_urls({"https://example.com/page1/"})
        progress.start_fetching()
        progress.mark_url_processed("https://example.com/page1/")

        progress.enqueue_urls(
            {
                "https://example.com/page1/",  # Already processed -> ignored
                "https://example.com/page2/",
                "https://example.com/page3/",
            }
        )

        assert "https://example.com/page2/" in progress.pending_urls
        assert "https://example.com/page3/" in progress.pending_urls
        assert "https://example.com/page1/" not in progress.pending_urls
        assert progress.stats.urls_pending == 2


@pytest.mark.unit
class TestSyncProgressCheckpointing:
    """Tests for checkpoint-based resume (DDIA catch-up recovery pattern)."""

    def test_checkpoint_saves_current_state(self, sync_progress_module):
        """Checkpoint captures current progress state."""
        sync_progress = sync_progress_module.SyncProgress

        progress = sync_progress.create_new(tenant_codename="django")
        progress.start_discovery()
        progress.add_discovered_urls(
            {
                "https://example.com/page1/",
                "https://example.com/page2/",
                "https://example.com/page3/",
            }
        )
        progress.start_fetching()
        progress.mark_url_processed("https://example.com/page1/")

        checkpoint = progress.create_checkpoint()

        assert checkpoint["sync_id"] == str(progress.sync_id)
        assert checkpoint["tenant_codename"] == "django"
        assert checkpoint["phase"] == "fetching"
        assert len(checkpoint["pending_urls"]) == 2
        assert len(checkpoint["processed_urls"]) == 1
        assert checkpoint["last_checkpoint_at"] is not None

    def test_restore_from_checkpoint(self, sync_progress_module):
        """Restore SyncProgress from checkpoint data."""
        sync_progress = sync_progress_module.SyncProgress
        sync_phase = sync_progress_module.SyncPhase
        from uuid import uuid4

        checkpoint_data = {
            "sync_id": str(uuid4()),
            "tenant_codename": "fastapi",
            "phase": "fetching",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "last_checkpoint_at": datetime.now(timezone.utc).isoformat(),
            "discovered_urls": [
                "https://fastapi.tiangolo.com/page1/",
                "https://fastapi.tiangolo.com/page2/",
                "https://fastapi.tiangolo.com/page3/",
            ],
            "pending_urls": ["https://fastapi.tiangolo.com/page3/"],
            "processed_urls": [
                "https://fastapi.tiangolo.com/page1/",
                "https://fastapi.tiangolo.com/page2/",
            ],
            "failed_urls": {},
            "stats": {
                "urls_discovered": 3,
                "urls_pending": 1,
                "urls_processed": 2,
                "urls_failed": 0,
                "urls_skipped": 0,
            },
        }

        progress = sync_progress.restore_from_checkpoint(checkpoint_data)

        assert progress.tenant_codename == "fastapi"
        assert progress.phase == sync_phase.FETCHING
        assert len(progress.pending_urls) == 1
        assert len(progress.processed_urls) == 2
        assert progress.stats.urls_processed == 2


@pytest.mark.unit
class TestSyncProgressSerialization:
    """Tests for full serialization/deserialization."""

    def test_to_dict_full(self, sync_progress_module):
        """Full serialization to dictionary."""
        sync_progress = sync_progress_module.SyncProgress

        progress = sync_progress.create_new(tenant_codename="django")
        progress.start_discovery()
        progress.add_discovered_urls({"https://example.com/page1/"})
        progress.start_fetching()
        progress.mark_url_processed("https://example.com/page1/")
        progress.mark_completed()

        data = progress.to_dict()

        assert "sync_id" in data
        assert "tenant_codename" in data
        assert "phase" in data
        assert "started_at" in data
        assert "completed_at" in data
        assert "discovered_urls" in data
        assert "pending_urls" in data
        assert "processed_urls" in data
        assert "failed_urls" in data
        assert "stats" in data

    def test_roundtrip_serialization(self, sync_progress_module):
        """Full roundtrip: create -> serialize -> deserialize -> compare."""
        sync_progress = sync_progress_module.SyncProgress

        original = sync_progress.create_new(tenant_codename="drf")
        original.start_discovery()
        original.add_discovered_urls(
            {
                "https://example.com/page1/",
                "https://example.com/page2/",
            }
        )
        original.start_fetching()
        original.mark_url_processed("https://example.com/page1/")
        original.mark_url_failed(
            url="https://example.com/page2/",
            error_type="HTTPError",
            error_message="404",
        )

        # Serialize
        data = original.to_dict()
        json_str = json.dumps(data)  # Verify JSON serializable

        # Deserialize
        restored_data = json.loads(json_str)
        restored = sync_progress.from_dict(restored_data)

        assert restored.sync_id == original.sync_id
        assert restored.tenant_codename == original.tenant_codename
        assert restored.phase == original.phase
        assert restored.discovered_urls == original.discovered_urls
        assert restored.pending_urls == original.pending_urls
        assert restored.processed_urls == original.processed_urls
        assert len(restored.failed_urls) == len(original.failed_urls)


@pytest.mark.unit
class TestSyncProgressDomainEvents:
    """Tests for domain events emitted by SyncProgress (Cosmic Python pattern)."""

    def test_events_recorded_on_creation(self, sync_progress_module):
        """SyncStarted event recorded on creation."""
        sync_progress = sync_progress_module.SyncProgress
        sync_started = sync_progress_module.SyncStarted

        progress = sync_progress.create_new(tenant_codename="django")

        assert len(progress.events) == 1
        assert isinstance(progress.events[0], sync_started)
        assert progress.events[0].tenant_codename == "django"

    def test_events_recorded_on_phase_change(self, sync_progress_module):
        """Phase change events recorded."""
        sync_progress = sync_progress_module.SyncProgress
        phase_changed = sync_progress_module.PhaseChanged

        progress = sync_progress.create_new(tenant_codename="django")
        progress.start_discovery()

        phase_events = [e for e in progress.events if isinstance(e, phase_changed)]
        assert len(phase_events) == 1
        assert phase_events[0].new_phase == "discovering"

    def test_events_recorded_on_completion(self, sync_progress_module):
        """SyncCompleted event recorded on completion."""
        sync_progress = sync_progress_module.SyncProgress
        sync_completed = sync_progress_module.SyncCompleted

        progress = sync_progress.create_new(tenant_codename="django")
        progress.start_discovery()
        progress.start_fetching()
        progress.mark_completed()

        completed_events = [e for e in progress.events if isinstance(e, sync_completed)]
        assert len(completed_events) == 1
        assert completed_events[0].tenant_codename == "django"


@pytest.mark.unit
class TestSyncProgressHelpers:
    """Tests for helper methods."""

    def test_can_resume_property(self, sync_progress_module):
        """can_resume reflects phase correctly."""
        sync_progress = sync_progress_module.SyncProgress

        progress = sync_progress.create_new(tenant_codename="django")
        assert progress.can_resume is False  # Initializing

        progress.start_discovery()
        assert progress.can_resume is True  # Discovering

    def test_is_complete_property(self, sync_progress_module):
        """is_complete reflects phase correctly."""
        sync_progress = sync_progress_module.SyncProgress

        progress = sync_progress.create_new(tenant_codename="django")
        assert progress.is_complete is False

        progress.start_discovery()
        progress.start_fetching()
        progress.mark_completed()
        assert progress.is_complete is True

    def test_duration_calculation(self, sync_progress_module):
        """Duration calculated correctly."""
        sync_progress = sync_progress_module.SyncProgress

        progress = sync_progress.create_new(tenant_codename="django")

        # Duration before completion is time since start
        duration = progress.duration
        assert duration is not None
        assert duration >= timedelta(seconds=0)

        # After completion, duration is fixed
        progress.start_discovery()
        progress.start_fetching()
        progress.mark_completed()

        duration_after = progress.duration
        assert duration_after is not None
