"""The operational clock: what "now" means for time-relative calculations.

The synthetic dataset is anchored at a fixed reference time, so by default the
engines evaluate everything as of that moment. This keeps demo results stable no
matter which day the prototype is shown. Set CLOCK_MODE=system to use real time.
"""

from datetime import UTC, datetime

from app.core.config import Settings

# Latest moment represented in the synthetic dataset (naive UTC).
DATASET_REFERENCE_TIME = datetime(2026, 10, 8, 9, 0)


def operational_now(settings: Settings) -> datetime:
    if settings.clock_mode == "system":
        return datetime.now(UTC).replace(tzinfo=None)
    return DATASET_REFERENCE_TIME
