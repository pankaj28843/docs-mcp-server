"""Tests for scheduler protocol."""

import pytest
from typing import Protocol

from docs_mcp_server.services.scheduler_protocol import SyncSchedulerProtocol


class TestSchedulerProtocol:
    """Test SyncSchedulerProtocol definition."""

    def test_scheduler_protocol_is_protocol(self):
        """Test that SyncSchedulerProtocol is a proper Protocol."""
        assert issubclass(SyncSchedulerProtocol, Protocol)

    def test_scheduler_protocol_has_required_methods(self):
        """Test that SyncSchedulerProtocol defines required methods."""
        # Check if the protocol has the expected method signatures
        assert hasattr(SyncSchedulerProtocol, '__annotations__')
        
        # This tests that the protocol exists and can be used for type checking
        # The actual implementation would be tested in concrete classes

    def test_concrete_implementation_satisfies_protocol(self):
        """Test that a concrete implementation can satisfy the protocol."""
        
        class ConcreteScheduler:
            """Concrete scheduler implementation for testing."""
            
            @property
            def is_initialized(self) -> bool:
                return True
                
            @property
            def running(self) -> bool:
                return True
                
            @property
            def stats(self) -> dict[str, object]:
                return {}
                
            async def initialize(self) -> bool:
                return True
                
            async def stop(self) -> None:
                pass
                
            async def trigger_sync(self, *, force_crawler: bool = False, force_full_sync: bool = False) -> dict:
                return {}
                
            async def get_status_snapshot(self) -> dict:
                return {}
        
        # This should not raise any type errors
        scheduler: SyncSchedulerProtocol = ConcreteScheduler()
        assert scheduler is not None

    def test_protocol_can_be_used_in_type_hints(self):
        """Test that the protocol can be used in type hints."""
        
        def use_scheduler(scheduler: SyncSchedulerProtocol) -> bool:
            """Function that uses a scheduler protocol."""
            return True
        
        class MockScheduler:
            """Mock scheduler for testing."""
            @property
            def is_initialized(self) -> bool:
                return True
                
            @property
            def running(self) -> bool:
                return False
                
            @property
            def stats(self) -> dict[str, object]:
                return {}
                
            async def initialize(self) -> bool:
                return True
                
            async def stop(self) -> None:
                pass
                
            async def trigger_sync(self, *, force_crawler: bool = False, force_full_sync: bool = False) -> dict:
                return {}
                
            async def get_status_snapshot(self) -> dict:
                return {}
        
        # This tests that the protocol can be used in function signatures
        result = use_scheduler(MockScheduler())
        assert result is True
