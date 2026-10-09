"""Reusable column types."""

from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import Enum as SAEnum


def enum_column[E: Enum](enum_cls: type[E]) -> SAEnum:
    """Store an enum by its value as a plain string (no native DB enum)."""
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=32,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


def utc_now() -> datetime:
    """Naive UTC timestamp. All datetimes in the database are naive UTC."""
    return datetime.now(UTC).replace(tzinfo=None)
