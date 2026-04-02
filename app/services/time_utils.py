from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")


def beijing_now() -> datetime:
    """Return current Beijing time as a naive local datetime.

    The service currently persists local ISO strings without timezone offsets.
    Keeping the returned datetime naive preserves that storage format while
    making the source timezone explicit and stable.
    """

    return datetime.now(BEIJING_TIMEZONE).replace(tzinfo=None, microsecond=0)
