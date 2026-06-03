"""Build the right :class:`TimeclockAdapter` for a device from its config.

The concrete drivers (pyodbc for .mdb / SQL Express, pyzk for TCP) are pulled in
lazily so the web/worker image doesn't hard-depend on platform-specific
libraries until a device of that type is actually configured.
"""

from __future__ import annotations

from datetime import datetime

from app.core.logging import get_logger
from app.modules.attendance.adapters.base import RawPunch, TimeclockAdapter
from app.modules.attendance.models import AdapterType, AttendanceDevice

logger = get_logger("attendance.adapter")


class NullAdapter:
    """Fallback adapter: pulls nothing. Used for MANUAL devices and as a safe
    default until a real driver is wired for a device type."""

    def __init__(self, device: AttendanceDevice) -> None:
        self._device = device

    def fetch_logs(self, since: datetime | None) -> list[RawPunch]:
        logger.info(
            "timeclock_pull_noop",
            device_id=self._device.id,
            adapter=self._device.adapter_type,
        )
        return []


def build_adapter(device: AttendanceDevice) -> TimeclockAdapter:
    """Return an adapter instance for the device's ``adapter_type``.

    Concrete drivers are implemented incrementally; unknown/not-yet-implemented
    types fall back to :class:`NullAdapter` so a pull never crashes the batch.
    """
    if device.adapter_type == AdapterType.MDB:
        # from app.modules.attendance.adapters.mdb import MdbAdapter
        # return MdbAdapter(device)
        return NullAdapter(device)
    if device.adapter_type == AdapterType.SQLEXPRESS:
        # from app.modules.attendance.adapters.sqlexpress import SqlExpressAdapter
        return NullAdapter(device)
    if device.adapter_type == AdapterType.TCP:
        # from app.modules.attendance.adapters.tcp import ZkTcpAdapter
        return NullAdapter(device)
    return NullAdapter(device)
