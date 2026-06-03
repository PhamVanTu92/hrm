"""Time-clock device integration adapters (Strategy pattern)."""

from app.modules.attendance.adapters.base import RawPunch, TimeclockAdapter
from app.modules.attendance.adapters.factory import build_adapter

__all__ = ["RawPunch", "TimeclockAdapter", "build_adapter"]
