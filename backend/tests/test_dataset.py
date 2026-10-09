"""Synthetic dataset: schema, generator, seed command and demo scenario."""

from collections.abc import Iterator
from datetime import datetime

import pytest
from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.seed import seed_database, table_counts
from app.db.session import create_db_engine
from app.db.synthetic import (
    COMPATIBLE_DONORS,
    DEMO_DONOR_CODES,
    DEMO_PATIENT_CODE,
    DEMO_REQUEST_CODE,
    REFERENCE_NOW,
    SEED,
    TABLE_ORDER,
    TARGET_COUNTS,
    dataset_fingerprint,
    generate_dataset,
)
from app.models import BloodRequest, CoordinationAttempt, Donor, DonorInteraction, DonorState, RecoveryAction
from app.models.enums import (
    CoordinationOutcome,
    CoordinationStatus,
    FailureCategory,
    LearningEventType,
    RecoveryStatus,
    RequestStatus,
)
from app.repositories.dataset_repository import DatasetRepository


def _new_engine() -> Engine:
    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture(scope="module")
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = _new_engine()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        seed_database(session)
    yield factory
    engine.dispose()


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as db:
        yield db


def _snapshot(session: Session) -> list[list[tuple[object, ...]]]:
    tables = Base.metadata.tables
    return [[tuple(row) for row in session.execute(select(tables[name]).order_by(text("id")))] for name in TABLE_ORDER]


@pytest.fixture
def demo_request(session: Session) -> BloodRequest:
    request = DatasetRepository(session).get_blood_request_by_code(DEMO_REQUEST_CODE)
    assert request is not None
    return request


# ---- schema & generator -----------------------------------------------------


def test_all_tables_are_created() -> None:
    engine = _new_engine()
    # The dataset tables plus the operational notifications (10A) and test_recipients (10E.1) tables, which a reseed never touches.
    assert set(inspect(engine).get_table_names()) == set(TABLE_ORDER) | {"notifications", "test_recipients"}
    engine.dispose()


def test_generator_is_deterministic_for_a_seed() -> None:
    assert dataset_fingerprint(generate_dataset(SEED)) == dataset_fingerprint(generate_dataset(SEED))
    assert dataset_fingerprint(generate_dataset(SEED)) != dataset_fingerprint(generate_dataset(SEED + 1))


def test_no_event_happens_after_the_reference_time() -> None:
    dataset = generate_dataset()
    future = [
        (table, key)
        for table, rows in dataset.items()
        for row in rows
        for key, value in row.items()
        if isinstance(value, datetime) and key != "required_by" and value > REFERENCE_NOW
    ]
    assert future == []


# ---- seeding ----------------------------------------------------------------


def test_seed_produces_exact_target_counts(session: Session) -> None:
    counts = table_counts(session)
    for table, expected in TARGET_COUNTS.items():
        assert counts[table] == expected, table


def test_seeding_twice_is_idempotent_and_reproducible() -> None:
    engine = _new_engine()
    factory = sessionmaker(bind=engine)
    with factory() as db:
        first_counts = seed_database(db)
        first = _snapshot(db)
    with factory() as db:
        second_counts = seed_database(db)
        second = _snapshot(db)
    engine.dispose()

    assert first_counts == second_counts
    assert second_counts["donors"] == TARGET_COUNTS["donors"]  # not doubled
    assert first == second


def test_every_donor_has_exactly_one_state(session: Session) -> None:
    missing = session.scalar(
        select(func.count()).select_from(Donor).outerjoin(DonorState).where(DonorState.id.is_(None))
    )
    assert missing == 0
    assert session.scalar(select(func.count()).select_from(DonorState)) == TARGET_COUNTS["donors"]


def test_foreign_keys_are_valid(session: Session) -> None:
    assert session.execute(text("PRAGMA foreign_key_check")).all() == []


def test_records_are_causally_consistent(session: Session) -> None:
    for attempt in session.scalars(select(CoordinationAttempt)):
        assert attempt.donor.blood_group in COMPATIBLE_DONORS[attempt.blood_request.blood_group]
        if attempt.status is CoordinationStatus.FAILED:
            assert attempt.failure is not None
            assert attempt.failure.recovery_actions
    for request in session.scalars(select(BloodRequest)):
        priorities = [a.priority_score for a in request.coordination_attempts]
        assert priorities == sorted(priorities, reverse=True)
        assert len(set(priorities)) == len(priorities)  # strictly decreasing cascade order
    for recovery in session.scalars(select(RecoveryAction)):
        assert recovery.blood_request_id == recovery.failure.coordination_attempt.blood_request_id
    for interaction in session.scalars(select(DonorInteraction).where(DonorInteraction.coordination_attempt_id.is_not(None))):
        assert interaction.coordination_attempt is not None
        assert interaction.blood_request_id == interaction.coordination_attempt.blood_request_id
        assert interaction.donor_id == interaction.coordination_attempt.donor_id


def test_dataset_has_useful_variation(session: Session) -> None:
    statuses = set(session.scalars(select(BloodRequest.status).distinct()))
    assert statuses == set(RequestStatus)
    multi_attempt = session.scalar(
        select(func.count()).select_from(
            select(CoordinationAttempt.blood_request_id)
            .group_by(CoordinationAttempt.blood_request_id)
            .having(func.count() > 2)
            .subquery()
        )
    )
    assert multi_attempt and multi_attempt > 10
    fatigued = session.scalar(select(func.count()).select_from(DonorState).where(DonorState.fatigue_score > 0.6))
    assert fatigued is not None and 0 < fatigued < TARGET_COUNTS["donors"] * 0.15


# ---- demo scenario ----------------------------------------------------------


def test_demo_request_exists(demo_request: BloodRequest) -> None:
    assert demo_request.patient.patient_code == DEMO_PATIENT_CODE
    assert demo_request.status is RequestStatus.FULFILLED


def test_demo_first_attempt_fails_with_no_response(demo_request: BloodRequest) -> None:
    first = demo_request.coordination_attempts[0]
    assert first.sequence_number == 1
    assert first.donor.donor_code == DEMO_DONOR_CODES[0]
    assert first.status is CoordinationStatus.FAILED
    assert first.outcome is CoordinationOutcome.NO_RESPONSE
    assert first.failure is not None
    assert first.failure.failure_category is FailureCategory.NO_RESPONSE


def test_demo_has_recovery_action_to_second_candidate(demo_request: BloodRequest) -> None:
    failure = demo_request.coordination_attempts[0].failure
    assert failure is not None
    (recovery,) = failure.recovery_actions
    assert recovery.status is RecoveryStatus.COMPLETED
    assert recovery.target_donor is not None
    assert recovery.target_donor.donor_code == DEMO_DONOR_CODES[1]


def test_demo_eventually_succeeds(demo_request: BloodRequest) -> None:
    attempts = demo_request.coordination_attempts
    assert [a.sequence_number for a in attempts] == [1, 2]
    final = attempts[-1]
    assert final.donor.donor_code == DEMO_DONOR_CODES[1]
    assert final.status is CoordinationStatus.SUCCESS
    assert final.outcome is CoordinationOutcome.DONOR_ACCEPTED
    assert {event.event_type for event in demo_request.learning_events} == {
        LearningEventType.NO_RESPONSE,
        LearningEventType.RECOVERY_SUCCESS,
        LearningEventType.SUCCESSFUL_MATCH,
    }
