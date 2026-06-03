"""Adapter contract for pulling raw punches from a time-clock device.

Each concrete device technology (MS Access .mdb, SQL Express, ZKTeco TCP)
implements :class:`TimeclockAdapter`. Connection details come from the device's
``config`` JSONB, so adding/swapping a device is configuration, not code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class RawPunch:
    """A single punch as reported by a device, before normalisation."""

    device_user_id: str
    punch_at: datetime
    direction: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class TimeclockAdapter(Protocol):
    """Pulls punches newer than ``since`` from one device."""

    def fetch_logs(self, since: datetime | None) -> list[RawPunch]: ...
