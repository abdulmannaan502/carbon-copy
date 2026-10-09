"""Controlled test recipients for live SMS.

Live sending is never allowed to a synthetic donor or patient record (they hold no real phone numbers and have
given no consent). A TestRecipient is a real person who has explicitly agreed to receive controlled test
messages. Rows are created only by an operator through `python -m app.db.test_recipients`; there is no API
that creates them, because the prototype has no authentication and an open endpoint would let anyone authorise
a send to any phone. The phone number is stored here only to be able to send, and is never returned by the API.
"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import utc_now


class TestRecipient(Base):
    __test__ = False  # not a pytest test class

    __tablename__ = "test_recipients"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_code: Mapped[str] = mapped_column(String(11), unique=True, index=True)  # TR-XXXXXXXX
    label: Mapped[str] = mapped_column(String(80))
    phone_e164: Mapped[str] = mapped_column(String(16))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)  # operator confirmed the number belongs to the consenting person
    consent_recorded_at: Mapped[datetime | None] = mapped_column(DateTime)
    consent_statement: Mapped[str | None] = mapped_column(String(240))
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime)  # suppression: blocks every further send
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
