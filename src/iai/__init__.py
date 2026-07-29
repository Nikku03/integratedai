"""integratedai - catalyst-driven, point-in-time-safe equity research stack."""

from .core.config import Config
from .core.types import Event, LookaheadError, events_to_frame, validate_events

__version__ = "0.1.0"

__all__ = ["Config", "Event", "LookaheadError", "events_to_frame", "validate_events"]
