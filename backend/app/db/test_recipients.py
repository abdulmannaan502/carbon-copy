"""Operator tool: register, list and suppress the controlled TEST recipients for live SMS.

    python -m app.db.test_recipients add --label "Project owner" --phone +15551230000 \
        --consent "Agreed by email on 2026-10-09 to receive Carbon Copy test SMS" --verified
    python -m app.db.test_recipients list
    python -m app.db.test_recipients opt-out TR-AB12CD34

A recipient can be sent a live test only if it has a recorded consent, was verified by you (the number belongs to
the person who consented), and has not opted out. Only register people who have actually agreed; never register a
number taken from the synthetic dataset. This is a local operator action, not an API: the prototype has no
authentication, so no endpoint may create recipients. Phone numbers are masked in all output.
"""

import argparse
import re
import sys
import uuid

from sqlalchemy import select

from app.core.config import E164_PATTERN
from app.db.session import SessionLocal, init_db
from app.db.types import utc_now
from app.models import TestRecipient


def mask(phone: str) -> str:
    return f"{phone[:3]}{'*' * max(len(phone) - 5, 0)}{phone[-2:]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="register a test recipient")
    add.add_argument("--label", required=True, help="who this is (max 80 characters)")
    add.add_argument("--phone", required=True, help="E.164 number, e.g. +15551230000")
    add.add_argument("--consent", help="how and when the person agreed to receive test messages (recorded as consent)")
    add.add_argument("--verified", action="store_true", help="you confirmed the number belongs to the consenting person")
    commands.add_parser("list", help="list recipients (numbers masked)")
    out = commands.add_parser("opt-out", help="suppress a recipient permanently")
    out.add_argument("code")
    args = parser.parse_args(argv)

    init_db()
    with SessionLocal() as session:
        if args.command == "add":
            if not E164_PATTERN.fullmatch(args.phone):
                print("The phone number must be in E.164 format, e.g. +15551230000.", file=sys.stderr)
                return 2
            if len(args.label) > 80 or (args.consent and len(args.consent) > 240):
                print("The label is limited to 80 characters and the consent statement to 240.", file=sys.stderr)
                return 2
            now = utc_now()
            recipient = TestRecipient(
                recipient_code=f"TR-{uuid.uuid4().hex[:8].upper()}", label=args.label.strip(), phone_e164=args.phone,
                consent_recorded_at=now if args.consent else None, consent_statement=args.consent,
                verified_at=now if args.verified else None,
            )
            session.add(recipient)
            session.commit()
            ready = recipient.consent_recorded_at and recipient.verified_at
            print(f"Registered {recipient.recipient_code} ({mask(args.phone)}). "
                  f"{'Authorised for controlled test sends.' if ready else 'NOT authorised yet: needs --consent and --verified.'}")
        elif args.command == "list":
            for r in session.scalars(select(TestRecipient).order_by(TestRecipient.id)):
                state = "opted out" if r.opted_out_at else ("authorised" if r.consent_recorded_at and r.verified_at else "incomplete")
                print(f"{r.recipient_code}  {mask(r.phone_e164)}  {r.label}  [{state}]")
        else:
            if not re.fullmatch(r"TR-[0-9A-F]{8}", args.code):
                print("Not a test-recipient code.", file=sys.stderr)
                return 2
            recipient = session.scalar(select(TestRecipient).where(TestRecipient.recipient_code == args.code))
            if recipient is None:
                print("No such recipient.", file=sys.stderr)
                return 1
            recipient.opted_out_at = recipient.opted_out_at or utc_now()
            session.commit()
            print(f"{args.code} is opted out; no further messages will be sent to it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
