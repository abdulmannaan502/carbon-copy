"""Deterministic synthetic dataset for the Carbon Copy demo.

Everything produced here is fabricated: names are random combinations, phone
numbers are placeholders, coordinates are jittered around city centres, and no
record describes a real person or a real medical event.

`generate_dataset(seed)` is a pure function: the same seed always yields exactly
the same rows (same ids, codes, timestamps and values). It knows nothing about
the database; `app.db.seed` persists its output.

The generator *simulates* coordination so records are causally linked:

    Patient → BloodRequest → availability checks (DonorInteraction)
            → CoordinationAttempt → (Failure → RecoveryAction → next attempt)…
            → success → LearningEvent

Decision rules used while simulating (compatibility, 90-day donation interval,
recovery choice) are simplified demo rules. They are not clinical guidance and
are not the future engines: those will be implemented as services.
"""

from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from app.core.blood import COMPATIBLE_DONORS
from app.core.clock import DATASET_REFERENCE_TIME
from app.models.enums import (
    AvailabilityStatus,
    BloodGroup,
    BridgeGroupType,
    CoordinationOutcome,
    CoordinationStatus,
    EligibilityStatus,
    FailureCategory,
    FailureSeverity,
    InteractionChannel,
    InteractionResponseStatus,
    InteractionType,
    LearningEventType,
    LearningOutcome,
    LearningSourceType,
    RecoveryActionType,
    RecoveryStatus,
    RequestStatus,
    UrgencyLevel,
)

Row = dict[str, Any]
Dataset = dict[str, list[Row]]

SEED = 20261008
# The dataset's "now". All history lies before it; upcoming requirements after it.
REFERENCE_NOW = DATASET_REFERENCE_TIME

DEMO_REQUEST_CODE = "DEMO-REQUEST-001"
DEMO_PATIENT_CODE = "PAT-0001"
DEMO_DONOR_CODES = ("DON-00001", "DON-00002")  # candidate #1 (no response), candidate #2 (accepts)

TARGET_COUNTS = {
    "patients": 80,
    "bridge_groups": 80,
    "donors": 6946,
    "blood_requests": 320,
    "donor_interactions": 7240,
}
REQUESTS_PER_PATIENT = TARGET_COUNTS["blood_requests"] // TARGET_COUNTS["patients"]

# Insertion order (respects foreign keys).
TABLE_ORDER = (
    "bridge_groups",
    "patients",
    "donors",
    "donor_states",
    "blood_requests",
    "coordination_attempts",
    "donor_interactions",
    "failures",
    "recovery_actions",
    "learning_events",
)

# Demo rule: minimum days between two donations by the same donor. Not clinical guidance.
DONATION_INTERVAL_DAYS = 90

_G = BloodGroup

# Approximate population distribution (South Indian donor pools skew B+/O+).
BLOOD_GROUP_WEIGHTS = {
    _G.O_POS: 33.0, _G.B_POS: 31.0, _G.A_POS: 21.0, _G.AB_POS: 8.0,
    _G.O_NEG: 2.5, _G.B_NEG: 2.0, _G.A_NEG: 1.5, _G.AB_NEG: 1.0,
}


@dataclass(frozen=True)
class City:
    name: str
    district: str
    state: str
    lat: float
    lon: float
    weight: float


CITIES = (
    City("Hyderabad", "Hyderabad", "Telangana", 17.3850, 78.4867, 0.30),
    City("Secunderabad", "Hyderabad", "Telangana", 17.4399, 78.4983, 0.08),
    City("Kukatpally", "Medchal-Malkajgiri", "Telangana", 17.4849, 78.4138, 0.08),
    City("Gachibowli", "Rangareddy", "Telangana", 17.4401, 78.3489, 0.07),
    City("Warangal", "Warangal", "Telangana", 17.9689, 79.5941, 0.10),
    City("Karimnagar", "Karimnagar", "Telangana", 18.4386, 79.1288, 0.07),
    City("Nizamabad", "Nizamabad", "Telangana", 18.6725, 78.0941, 0.06),
    City("Khammam", "Khammam", "Telangana", 17.2473, 80.1514, 0.06),
    City("Nalgonda", "Nalgonda", "Telangana", 17.0575, 79.2684, 0.05),
    City("Mahabubnagar", "Mahabubnagar", "Telangana", 16.7488, 78.0035, 0.05),
    City("Siddipet", "Siddipet", "Telangana", 18.1019, 78.8521, 0.04),
    City("Sangareddy", "Sangareddy", "Telangana", 17.6140, 78.0816, 0.04),
)
HYDERABAD = CITIES[0]

FIRST_NAMES = (
    "Aarav", "Aditi", "Akash", "Ananya", "Anil", "Anjali", "Arjun", "Ayesha", "Bhavana", "Chaitanya",
    "Daniel", "Deepa", "Divya", "Farhan", "Ganesh", "Grace", "Harini", "Harsha", "Imran", "Isha",
    "Joseph", "Jyothi", "Karthik", "Kavya", "Kiran", "Lakshmi", "Madhavi", "Mahesh", "Manoj", "Mary",
    "Meera", "Mohan", "Naveen", "Neha", "Nikhil", "Padma", "Pooja", "Prakash", "Pranav", "Priya",
    "Rahul", "Rajesh", "Ramya", "Ravi", "Rohit", "Sahana", "Sai", "Sana", "Sandeep", "Sanjana",
    "Shreya", "Siddharth", "Sneha", "Srinivas", "Swathi", "Tarun", "Teja", "Uma", "Varun", "Vasavi",
    "Venkat", "Vidya", "Vijay", "Vinay", "Yamini", "Zoya",
)
SURNAMES = (
    "Agarwal", "Ahmed", "Banerjee", "Bhat", "Chowdary", "Das", "Desai", "Goud", "Gupta", "Hegde",
    "Iyer", "Jain", "Joseph", "Khan", "Kulkarni", "Kumar", "Mehta", "Menon", "Mishra", "Murthy",
    "Naidu", "Nair", "Patel", "Pillai", "Prasad", "Rao", "Reddy", "Sharma", "Shetty", "Singh",
    "Sinha", "Thomas", "Varma", "Yadav",
)

GROUP_DESCRIPTORS = (
    "Asha", "Jeevan", "Kinship", "Lifeline", "Prana", "Raksha", "Sahaya", "Saathi", "Sankalp", "Seva",
)
GROUP_SUFFIXES = {
    BridgeGroupType.NGO: ("Foundation", "Trust", "Welfare Society"),
    BridgeGroupType.VOLUNTEER_NETWORK: ("Donor Circle", "Volunteers", "Volunteer Network"),
    BridgeGroupType.CAREGIVER_GROUP: ("Caregivers Circle", "Family Network", "Parents Collective"),
    BridgeGroupType.COMMUNITY_GROUP: ("Community Collective", "Neighbourhood Network", "Residents Forum"),
}
GROUP_TYPE_WEIGHTS = {
    BridgeGroupType.NGO: 35, BridgeGroupType.VOLUNTEER_NETWORK: 30,
    BridgeGroupType.CAREGIVER_GROUP: 20, BridgeGroupType.COMMUNITY_GROUP: 15,
}
URGENCY_WEIGHTS = {UrgencyLevel.LOW: 15, UrgencyLevel.MODERATE: 40, UrgencyLevel.HIGH: 30, UrgencyLevel.CRITICAL: 15}
URGENCY_ORDER = tuple(UrgencyLevel)
TRANSFUSION_FREQUENCIES = (14, 21, 21, 21, 28, 28, 30, 35)

# Final status of each patient's current request (one per active non-demo patient: 76).
CURRENT_STATUS_MIX = {
    RequestStatus.OPEN: 12,
    RequestStatus.MATCHING: 14,
    RequestStatus.COORDINATING: 22,
    RequestStatus.RECOVERING: 12,
    RequestStatus.FULFILLED: 16,
}
# Relative share of broadcast availability checks a request receives.
CHECK_WEIGHTS = {
    RequestStatus.OPEN: 0.08, RequestStatus.MATCHING: 0.7, RequestStatus.COORDINATING: 1.0,
    RequestStatus.FULFILLED: 1.0, RequestStatus.RECOVERING: 1.3, RequestStatus.CANCELLED: 0.15,
}
# How long before REFERENCE_NOW the latest event of a current request happened (minutes).
CURRENT_LAST_EVENT_MINUTES = {
    RequestStatus.OPEN: (5, 240), RequestStatus.MATCHING: (5, 90), RequestStatus.COORDINATING: (20, 180),
    RequestStatus.RECOVERING: (10, 90), RequestStatus.FULFILLED: (120, 1800), RequestStatus.CANCELLED: (1440, 5760),
}

FAILURE_OUTCOME_WEIGHTS = {
    CoordinationOutcome.NO_RESPONSE: 45, CoordinationOutcome.DONOR_UNAVAILABLE: 25,
    CoordinationOutcome.DONOR_DECLINED: 20, CoordinationOutcome.OTHER: 10,
}
OUTCOME_CATEGORY = {
    CoordinationOutcome.NO_RESPONSE: FailureCategory.NO_RESPONSE,
    CoordinationOutcome.DONOR_UNAVAILABLE: FailureCategory.UNAVAILABLE,
    CoordinationOutcome.DONOR_DECLINED: FailureCategory.DECLINED,
}
UNAVAILABLE_REASONS = (
    "Travelling out of town this week",
    "Unwell this week (self-reported)",
    "Work commitments on the required dates",
    "Family commitment on the required dates",
)
DECLINE_REASONS = (
    "Not able to donate this time",
    "Prefers to donate at a later date",
    "Travel distance to the hospital is too long",
)
RECOMMENDED_ACTIONS = {
    FailureCategory.NO_RESPONSE: "Contact the next-ranked compatible donor; prefer a phone call over SMS.",
    FailureCategory.UNAVAILABLE: "Move to the next available compatible donor.",
    FailureCategory.DECLINED: "Respect the donor's decision and move to the next compatible donor.",
    FailureCategory.CONTACT_FAILURE: "Switch to an alternative channel or donor and verify contact details.",
    FailureCategory.FATIGUE: "Pause outreach to this donor and select a less recently contacted donor.",
    FailureCategory.OTHER: "Flag for coordinator review.",
}
RECOVERY_DESCRIPTIONS = {
    RecoveryActionType.NEXT_DONOR: "Moved to the next-ranked compatible donor in the cascade.",
    RecoveryActionType.ALTERNATIVE_DONOR: "Switched to an alternative compatible donor and changed the outreach channel to a phone call.",
    RecoveryActionType.BRIDGE_GROUP_ESCALATION: "Escalated to the patient's bridge group to reach an affiliated donor.",
    RecoveryActionType.EXPANDED_SEARCH: "Expanded the search beyond the patient's city to the wider region.",
    RecoveryActionType.BLOOD_BANK_REFERRAL: "Referred the requirement to a partner blood bank (simulated).",
    RecoveryActionType.HUMAN_COORDINATOR_REVIEW: "Flagged for review by a human coordinator.",
}
FAILURE_LEARNING = {
    CoordinationOutcome.NO_RESPONSE: (LearningEventType.NO_RESPONSE, -0.35),
    CoordinationOutcome.DONOR_DECLINED: (LearningEventType.DONOR_DECLINED, -0.20),
    CoordinationOutcome.DONOR_UNAVAILABLE: (LearningEventType.FAILED_MATCH, -0.10),
    CoordinationOutcome.OTHER: (LearningEventType.FAILED_MATCH, -0.15),
}


def _weighted[T](rng: random.Random, options: dict[T, float]) -> T:
    return rng.choices(list(options), weights=list(options.values()))[0]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _minutes(value: int) -> timedelta:
    return timedelta(minutes=value)


@dataclass
class _DonorTraits:
    """Latent behaviour used by the simulation (not stored directly)."""

    reliability: float
    responsiveness: float
    base_donation_count: int
    base_last_donation: datetime | None
    base_days_since_contact: int | None
    fatigue_prone: bool = False
    ineligible: bool = False


DEMO_DONOR_TRAITS = (
    _DonorTraits(0.74, 0.38, 6, REFERENCE_NOW - timedelta(days=240), 60),
    _DonorTraits(0.93, 0.91, 11, REFERENCE_NOW - timedelta(days=150), 45),
)


@dataclass(frozen=True)
class _AttemptPlan:
    outcome: CoordinationOutcome | None  # None: outreach sent, still waiting
    category: FailureCategory | None = None
    follow_up: bool = False

    @property
    def interaction_count(self) -> int:
        if self.outcome is CoordinationOutcome.DONOR_ACCEPTED:
            return 2  # donation request + confirmation
        return 2 if self.follow_up else 1


_SUCCESS = _AttemptPlan(CoordinationOutcome.DONOR_ACCEPTED)
_DEMO_PLAN = (
    _AttemptPlan(CoordinationOutcome.NO_RESPONSE, FailureCategory.NO_RESPONSE, follow_up=True),
    _SUCCESS,
)


@dataclass
class _RequestSpec:
    patient_index: int
    is_current: bool
    is_demo: bool
    blood_group: BloodGroup
    urgency: UrgencyLevel
    units: int
    status: RequestStatus
    requested_at: datetime
    required_by: datetime
    plan: tuple[_AttemptPlan, ...] = ()
    checks: int = 0
    id: int = 0


@dataclass
class _RequestContext:
    request_id: int
    bridge_group_id: int | None
    rows: list[Row] = field(default_factory=list)  # every row created for this request
    interactions: list[Row] = field(default_factory=list)
    attempts: list[Row] = field(default_factory=list)
    contact_count: dict[int, int] = field(default_factory=dict)


class _Generator:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.rows: Dataset = {name: [] for name in TABLE_ORDER}
        self.traits: list[_DonorTraits] = []
        self.city_pool: dict[tuple[str, BloodGroup], list[int]] = defaultdict(list)
        self.region_pool: dict[BloodGroup, list[int]] = defaultdict(list)
        self.group_members: dict[int, list[int]] = defaultdict(list)
        # Simulated history per donor index, used to derive DonorState.
        self.donations: dict[int, list[datetime]] = defaultdict(list)
        self.contacts: dict[int, list[datetime]] = defaultdict(list)
        self.answered: dict[int, list[bool]] = defaultdict(list)
        self.attempt_results: dict[int, list[bool]] = defaultdict(list)

    def run(self) -> Dataset:
        self._bridge_groups_and_patients()
        self._donors()
        specs = self._request_specs()
        self._allocate_checks(specs)
        for spec in specs:
            self._simulate(spec)
        self._donor_states()
        return self.rows

    # ---- reference entities ------------------------------------------------

    def _pick_city(self) -> City:
        return self.rng.choices(CITIES, weights=[c.weight for c in CITIES])[0]

    def _bridge_groups_and_patients(self) -> None:
        rng = self.rng
        count = TARGET_COUNTS["patients"]
        inactive_patients = set(rng.sample(range(1, count), 3))
        inactive_groups = set(rng.sample(range(1, count), 3))
        used_names: set[str] = set()

        for i in range(count):
            demo = i == 0
            city = HYDERABAD if demo else self._pick_city()
            group_type = BridgeGroupType.NGO if demo else _weighted(rng, GROUP_TYPE_WEIGHTS)
            while True:
                name = f"{rng.choice(GROUP_DESCRIPTORS)} {rng.choice(GROUP_SUFFIXES[group_type])}, {city.name}"
                if name not in used_names:
                    used_names.add(name)
                    break
            group_id = i + 1
            self.rows["bridge_groups"].append({
                "id": group_id,
                "group_code": f"BG-{group_id:04d}",
                "name": name,
                "city": city.name, "district": city.district, "state": city.state,
                "group_type": group_type,
                "active": i not in inactive_groups,
                "created_at": REFERENCE_NOW - timedelta(days=rng.randint(180, 1600)),
            })

            frequency = 21 if demo else rng.choice(TRANSFUSION_FREQUENCIES)
            # Keep the previous cycle strictly in the past so its history fits before "now".
            next_expected = REFERENCE_NOW.date() + timedelta(days=3 if demo else rng.randint(1, min(12, frequency - 2)))
            first, surname = rng.choice(FIRST_NAMES), rng.choice(SURNAMES)
            self.rows["patients"].append({
                "id": i + 1,
                "patient_code": f"PAT-{i + 1:04d}",
                "display_name": "Meera S." if demo else f"{first} {surname[0]}.",
                "blood_group": BloodGroup.B_NEG if demo else _weighted(rng, BLOOD_GROUP_WEIGHTS),
                "city": city.name, "district": city.district, "state": city.state,
                "urgency_level": UrgencyLevel.HIGH if demo else _weighted(rng, URGENCY_WEIGHTS),
                "transfusion_frequency_days": frequency,
                "last_transfusion_date": next_expected - timedelta(days=frequency),
                "next_expected_requirement": next_expected,
                "bridge_group_id": group_id,
                "active": i not in inactive_patients,
                "created_at": REFERENCE_NOW - timedelta(days=rng.randint(200, 1500)),
                "updated_at": REFERENCE_NOW - timedelta(days=rng.randint(0, 14)),
            })

    def _donors(self) -> None:
        rng = self.rng
        groups_by_city: dict[str, list[int]] = defaultdict(list)
        for group in self.rows["bridge_groups"]:
            groups_by_city[group["city"]].append(group["id"])

        for i in range(TARGET_COUNTS["donors"]):
            demo = i < len(DEMO_DONOR_CODES)
            city = HYDERABAD if demo else self._pick_city()
            blood_group = BloodGroup.B_NEG if demo else _weighted(rng, BLOOD_GROUP_WEIGHTS)
            spread = 0.06 if city is HYDERABAD else 0.035
            city_groups = groups_by_city.get(city.name, [])
            group_id = rng.choice(city_groups) if city_groups and rng.random() < 0.45 else None
            active = demo or rng.random() < 0.93
            first, surname = rng.choice(FIRST_NAMES), rng.choice(SURNAMES)

            reliability = rng.betavariate(5, 2)
            base_count = 0 if rng.random() < 0.18 else min(40, 1 + int(rng.expovariate(1 / 6)))
            traits = _DonorTraits(
                reliability=reliability,
                responsiveness=_clamp(0.8 * reliability + rng.gauss(0.12, 0.12), 0.05, 0.98),
                base_donation_count=base_count,
                base_last_donation=REFERENCE_NOW - timedelta(days=rng.randint(20, 900)) if base_count else None,
                base_days_since_contact=rng.randint(14, 540) if rng.random() < 0.7 else None,
                fatigue_prone=rng.random() < 0.09,
                ineligible=rng.random() < 0.03,
            )
            if demo:
                traits = DEMO_DONOR_TRAITS[i]
                group_id = 1

            donor_id = i + 1
            self.rows["donors"].append({
                "id": donor_id,
                "donor_code": f"DON-{donor_id:05d}",
                "display_name": f"{first} {surname}",
                "blood_group": blood_group,
                "city": city.name, "district": city.district, "state": city.state,
                "latitude": round(city.lat + rng.gauss(0, spread), 6),
                "longitude": round(city.lon + rng.gauss(0, spread), 6),
                "phone_placeholder": f"SIM-PHONE-{donor_id:05d}",
                "bridge_group_id": group_id,
                "active": active,
                "created_at": REFERENCE_NOW - timedelta(days=rng.randint(30, 2200)),
            })
            self.traits.append(traits)
            # Demo donors are reserved for DEMO-REQUEST-001 so the scenario stays clean.
            if active and not traits.ineligible and not demo:
                self.city_pool[(city.name, blood_group)].append(i)
                self.region_pool[blood_group].append(i)
                if group_id is not None:
                    self.group_members[group_id].append(i)

    # ---- request planning --------------------------------------------------

    def _vary_urgency(self, base: UrgencyLevel) -> UrgencyLevel:
        index = URGENCY_ORDER.index(base)
        roll = self.rng.random()
        if roll < 0.15:
            index -= 1
        elif roll < 0.30:
            index += 1
        return URGENCY_ORDER[max(0, min(len(URGENCY_ORDER) - 1, index))]

    def _failure_plan(self) -> _AttemptPlan:
        rng = self.rng
        outcome = _weighted(rng, FAILURE_OUTCOME_WEIGHTS)
        if outcome is CoordinationOutcome.OTHER:
            category = FailureCategory.CONTACT_FAILURE if rng.random() < 0.6 else FailureCategory.FATIGUE
        else:
            category = OUTCOME_CATEGORY[outcome]
        follow_up = outcome is CoordinationOutcome.NO_RESPONSE and rng.random() < 0.7
        return _AttemptPlan(outcome, category, follow_up)

    def _plan(self, status: RequestStatus, units: int, current: bool) -> tuple[_AttemptPlan, ...]:
        rng = self.rng
        plans: list[_AttemptPlan] = []
        if status is RequestStatus.FULFILLED:
            for _ in range(units):
                failures = _weighted(rng, {0: 50, 1: 28, 2: 14, 3: 8})
                if current:
                    failures = min(failures, 2)
                plans += [self._failure_plan() for _ in range(failures)] + [_SUCCESS]
        elif status is RequestStatus.RECOVERING:
            plans = [self._failure_plan() for _ in range(_weighted(rng, {1: 50, 2: 35, 3: 15}))]
        elif status is RequestStatus.COORDINATING:
            plans = [self._failure_plan() for _ in range(_weighted(rng, {0: 60, 1: 40}))]
            plans.append(_AttemptPlan(None))
        return tuple(plans)

    def _request_specs(self) -> list[_RequestSpec]:
        rng = self.rng
        current_statuses = [status for status, n in CURRENT_STATUS_MIX.items() for _ in range(n)]
        rng.shuffle(current_statuses)
        next_status = iter(current_statuses)
        specs: list[_RequestSpec] = []

        for p_index, patient in enumerate(self.rows["patients"]):
            frequency = patient["transfusion_frequency_days"]
            for cycle in range(REQUESTS_PER_PATIENT):
                current = cycle == REQUESTS_PER_PATIENT - 1
                demo = current and p_index == 0
                due: date = patient["next_expected_requirement"] - timedelta(
                    days=(REQUESTS_PER_PATIENT - 1 - cycle) * frequency
                )
                required_by = datetime.combine(due, time(10, 0))
                urgency = UrgencyLevel.HIGH if demo else self._vary_urgency(patient["urgency_level"])

                if demo:
                    status = RequestStatus.FULFILLED
                elif current:
                    status = next(next_status) if patient["active"] else RequestStatus.CANCELLED
                else:
                    status = RequestStatus.CANCELLED if rng.random() < 0.04 else RequestStatus.FULFILLED

                two_unit_chance = 0.4 if urgency is UrgencyLevel.CRITICAL else 0.18
                units = 2 if rng.random() < two_unit_chance else 1
                if current and status is RequestStatus.FULFILLED:
                    units = 1
                # Current requests get a provisional time; their timeline is anchored to "now" later.
                requested_at = (
                    REFERENCE_NOW - timedelta(days=2) if current
                    else required_by - timedelta(hours=rng.randint(36, 168))
                )
                specs.append(_RequestSpec(
                    patient_index=p_index, is_current=current, is_demo=demo,
                    blood_group=patient["blood_group"], urgency=urgency, units=units, status=status,
                    requested_at=requested_at, required_by=required_by,
                    plan=_DEMO_PLAN if demo else self._plan(status, units, current),
                ))

        specs.sort(key=lambda s: (s.requested_at, s.patient_index))
        for request_id, spec in enumerate(specs, start=1):
            spec.id = request_id
        return specs

    def _allocate_checks(self, specs: list[_RequestSpec]) -> None:
        """Split the broadcast availability checks so interactions hit the target exactly."""
        core = sum(plan.interaction_count for spec in specs for plan in spec.plan)
        remaining = TARGET_COUNTS["donor_interactions"] - core
        if remaining <= 0:
            raise RuntimeError("Attempt interactions alone exceed the interaction target.")
        weights = [CHECK_WEIGHTS[spec.status] * self.rng.uniform(0.6, 1.4) for spec in specs]
        total = sum(weights)
        quotas = [remaining * w / total for w in weights]
        counts = [int(q) for q in quotas]
        by_remainder = sorted(range(len(specs)), key=lambda i: (counts[i] - quotas[i], i))
        for i in by_remainder[: remaining - sum(counts)]:
            counts[i] += 1
        for spec, count in zip(specs, counts, strict=True):
            spec.checks = count

    # ---- simulation --------------------------------------------------------

    def _region_compatible(self, blood_group: BloodGroup) -> list[int]:
        return [d for g in COMPATIBLE_DONORS[blood_group] for d in self.region_pool[g]]

    def _candidate_pool(self, city: str, blood_group: BloodGroup, needed: int) -> list[int]:
        pool = [d for g in COMPATIBLE_DONORS[blood_group] for d in self.city_pool[(city, g)]]
        if len(pool) < needed:
            pool = self._region_compatible(blood_group)
        if len(pool) < needed:
            raise RuntimeError(f"Not enough compatible donors for {blood_group} (needed {needed}).")
        return pool

    def _can_donate(self, donor: int, at: datetime) -> bool:
        window = timedelta(days=DONATION_INTERVAL_DAYS)
        last = self.traits[donor].base_last_donation
        if last is not None and abs(at - last) < window:
            return False
        return all(abs(at - t) >= window for t in self.donations[donor])

    def _choose_weighted_donor(self, candidates: list[int], plan: _AttemptPlan) -> int:
        if plan.outcome is CoordinationOutcome.DONOR_ACCEPTED:
            weights = [self.traits[d].reliability ** 2 for d in candidates]
        elif plan.outcome is CoordinationOutcome.NO_RESPONSE:
            weights = [1.1 - self.traits[d].responsiveness for d in candidates]
        else:
            weights = [1.0] * len(candidates)
        return self.rng.choices(candidates, weights=weights)[0]

    def _pick_attempt_donor(
        self,
        spec: _RequestSpec,
        pool: list[int],
        responders: list[int],
        used: set[int],
        plan: _AttemptPlan,
        recovery: Row | None,
        at: datetime,
    ) -> int:
        rng = self.rng
        success = plan.outcome is CoordinationOutcome.DONOR_ACCEPTED
        compatible = COMPATIBLE_DONORS[spec.blood_group]

        def usable(d: int) -> bool:
            return d not in used and (not success or self._can_donate(d, at))

        action = recovery["action_type"] if recovery else None
        if action is RecoveryActionType.BRIDGE_GROUP_ESCALATION:
            group_id = self.rows["patients"][spec.patient_index]["bridge_group_id"]
            members = [
                d for d in self.group_members[group_id]
                if self.rows["donors"][d]["blood_group"] in compatible and usable(d)
            ]
            if members:
                return self._choose_weighted_donor(members, plan)

        candidates = self._region_compatible(spec.blood_group) if action is RecoveryActionType.EXPANDED_SEARCH else pool
        if success:
            fresh = [d for d in responders if usable(d)]
            if fresh and rng.random() < 0.7:
                return self._choose_weighted_donor(fresh, plan)
        sample = [d for d in rng.sample(candidates, min(60, len(candidates))) if usable(d)]
        if not sample:
            sample = [d for d in candidates if usable(d)]
        return self._choose_weighted_donor(sample, plan)

    def _choose_recovery(
        self, category: FailureCategory, failure_index: int, urgency: UrgencyLevel, still_open: bool
    ) -> RecoveryActionType:
        """Demo policy used only to synthesise history (the Self-Healing Engine comes later)."""
        if still_open:
            if urgency is UrgencyLevel.CRITICAL:
                return RecoveryActionType.BLOOD_BANK_REFERRAL
            if failure_index >= 3:
                return RecoveryActionType.HUMAN_COORDINATOR_REVIEW
        if failure_index == 1:
            if category in (FailureCategory.NO_RESPONSE, FailureCategory.CONTACT_FAILURE, FailureCategory.FATIGUE):
                return RecoveryActionType.ALTERNATIVE_DONOR
            return RecoveryActionType.NEXT_DONOR
        if failure_index == 2:
            return RecoveryActionType.BRIDGE_GROUP_ESCALATION
        return RecoveryActionType.EXPANDED_SEARCH

    def _add(self, ctx: _RequestContext, table: str, row: Row) -> Row:
        self.rows[table].append(row)
        ctx.rows.append(row)
        return row

    def _next_id(self, table: str) -> int:
        return len(self.rows[table]) + 1

    def _interact(
        self,
        ctx: _RequestContext,
        donor: int,
        attempt_id: int | None,
        interaction_type: InteractionType,
        channel: InteractionChannel,
        initiated_at: datetime,
        status: InteractionResponseStatus,
        response_at: datetime | None = None,
        reason: str | None = None,
    ) -> Row:
        ctx.contact_count[donor] = ctx.contact_count.get(donor, 0) + 1
        row_id = self._next_id("donor_interactions")
        row = self._add(ctx, "donor_interactions", {
            "id": row_id,
            "interaction_code": f"INT-{row_id:06d}",
            "blood_request_id": ctx.request_id,
            "donor_id": donor + 1,
            "coordination_attempt_id": attempt_id,
            "interaction_type": interaction_type,
            "channel": channel,
            "initiated_at": initiated_at,
            "response_status": status,
            "response_at": response_at,
            "failure_reason": reason,
            "attempt_number": ctx.contact_count[donor],
        })
        ctx.interactions.append(row)
        return row

    def _learn(
        self,
        ctx: _RequestContext,
        donor: int,
        source_type: LearningSourceType,
        source_reference: str,
        event_type: LearningEventType,
        signal: float,
        created_at: datetime,
    ) -> None:
        row_id = self._next_id("learning_events")
        self._add(ctx, "learning_events", {
            "id": row_id,
            "event_code": f"LRN-{row_id:05d}",
            "blood_request_id": ctx.request_id,
            "donor_id": donor + 1,
            "source_type": source_type,
            "source_reference": source_reference,
            "event_type": event_type,
            "outcome": LearningOutcome.POSITIVE if signal > 0 else LearningOutcome.NEGATIVE,
            "signal": round(_clamp(signal, -1.0, 1.0), 3),
            "created_at": created_at,
        })

    def _availability_checks(self, ctx: _RequestContext, spec: _RequestSpec, pool: list[int]) -> list[int]:
        rng = self.rng
        responders: list[int] = []
        for j, donor in enumerate(rng.sample(pool, spec.checks)):
            initiated = spec.requested_at + _minutes(15 + 45 * (j // 12) + rng.randint(0, 6))
            channel = InteractionChannel.SIMULATED_SMS if rng.random() < 0.55 else InteractionChannel.SIMULATED_APP
            if rng.random() < self.traits[donor].responsiveness * 0.75:
                status = _weighted(rng, {
                    InteractionResponseStatus.RESPONDED: 60,
                    InteractionResponseStatus.UNAVAILABLE: 25,
                    InteractionResponseStatus.DECLINED: 15,
                })
                response_at: datetime | None = initiated + _minutes(rng.randint(3, 180))
                reason = {
                    InteractionResponseStatus.RESPONDED: None,
                    InteractionResponseStatus.UNAVAILABLE: rng.choice(UNAVAILABLE_REASONS),
                    InteractionResponseStatus.DECLINED: rng.choice(DECLINE_REASONS),
                }[status]
            else:
                status, response_at, reason = InteractionResponseStatus.NO_RESPONSE, None, "No reply received"
            self._interact(ctx, donor, None, InteractionType.AVAILABILITY_CHECK, channel, initiated, status, response_at, reason)
            if status is InteractionResponseStatus.RESPONDED:
                responders.append(donor)
        return responders

    def _run_attempt(
        self, ctx: _RequestContext, attempt: Row, plan: _AttemptPlan, donor: int, channel: InteractionChannel
    ) -> None:
        """Create the attempt's interactions and set its status, outcome and completion time."""
        rng = self.rng
        R = InteractionResponseStatus
        attempt_id = attempt["id"]
        sent = attempt["started_at"] + _minutes(2)

        if plan.outcome is None:
            self._interact(ctx, donor, attempt_id, InteractionType.DONATION_REQUEST, channel, sent, R.PENDING)
            attempt["status"] = CoordinationStatus.WAITING if rng.random() < 0.7 else CoordinationStatus.OUTREACH_SENT
            return

        if plan.outcome is CoordinationOutcome.DONOR_ACCEPTED:
            accepted = sent + _minutes(rng.randint(8, 90))
            self._interact(ctx, donor, attempt_id, InteractionType.DONATION_REQUEST, channel, sent, R.ACCEPTED, accepted)
            confirm_sent = accepted + _minutes(rng.randint(15, 60))
            confirmed = confirm_sent + _minutes(rng.randint(2, 30))
            self._interact(ctx, donor, attempt_id, InteractionType.CONFIRMATION, channel, confirm_sent, R.RESPONDED, confirmed)
            attempt.update(status=CoordinationStatus.SUCCESS, outcome=plan.outcome, completed_at=confirmed)
            return

        category = plan.category
        if category is FailureCategory.NO_RESPONSE:
            window = rng.choice((2, 3, 4))
            reason = f"No response within the {window}-hour response window"
            self._interact(ctx, donor, attempt_id, InteractionType.DONATION_REQUEST, channel, sent, R.NO_RESPONSE, None, "No reply received")
            if plan.follow_up:
                follow_up_at = sent + _minutes(rng.randint(60, 100))
                self._interact(ctx, donor, attempt_id, InteractionType.FOLLOW_UP, channel, follow_up_at, R.NO_RESPONSE, None, "No reply received")
            completed = sent + timedelta(hours=window)
        elif category is FailureCategory.CONTACT_FAILURE:
            reason = "Outreach could not be delivered (simulated delivery failure)"
            self._interact(ctx, donor, attempt_id, InteractionType.DONATION_REQUEST, channel, sent, R.NO_RESPONSE, None, reason)
            completed = sent + _minutes(rng.randint(20, 60))
        else:
            if category is FailureCategory.UNAVAILABLE:
                status, reason = R.UNAVAILABLE, rng.choice(UNAVAILABLE_REASONS)
            elif category is FailureCategory.DECLINED:
                status, reason = R.DECLINED, rng.choice(DECLINE_REASONS)
            else:
                status, reason = R.DECLINED, "Donor asked to pause outreach after several recent contacts"
            completed = sent + _minutes(rng.randint(10, 120))
            self._interact(ctx, donor, attempt_id, InteractionType.DONATION_REQUEST, channel, sent, status, completed, reason)
        attempt.update(status=CoordinationStatus.FAILED, outcome=plan.outcome, completed_at=completed, failure_reason=reason)

    def _simulate(self, spec: _RequestSpec) -> None:
        rng = self.rng
        patient = self.rows["patients"][spec.patient_index]
        ctx = _RequestContext(request_id=spec.id, bridge_group_id=patient["bridge_group_id"])
        request = self._add(ctx, "blood_requests", {
            "id": spec.id,
            "request_code": DEMO_REQUEST_CODE if spec.is_demo else f"REQ-{spec.id:05d}",
            "patient_id": patient["id"],
            "bridge_group_id": patient["bridge_group_id"],
            "blood_group": spec.blood_group,
            "units_required": spec.units,
            "urgency_level": spec.urgency,
            "requested_at": spec.requested_at,
            "required_by": spec.required_by,
            "status": spec.status,
            "city": patient["city"], "district": patient["district"], "state": patient["state"],
        })

        pool = self._candidate_pool(patient["city"], spec.blood_group, spec.checks + len(spec.plan) + 10)
        responders = self._availability_checks(ctx, spec, pool)
        last_check = max((row["initiated_at"] for row in ctx.interactions), default=spec.requested_at)
        cursor = last_check + _minutes(rng.randint(45, 120))

        used: set[int] = set()
        pending_recovery: Row | None = None  # recovery waiting for its follow-on attempt
        failure_count = 0
        still_open = spec.status is RequestStatus.RECOVERING

        for sequence, plan in enumerate(spec.plan, start=1):
            if pending_recovery is not None:
                cursor = pending_recovery["initiated_at"] + _minutes(rng.randint(2, 12))
            if spec.is_demo:
                donor = sequence - 1  # DON-00001, then DON-00002
            else:
                donor = self._pick_attempt_donor(spec, pool, responders, used, plan, pending_recovery, cursor)
            used.add(donor)

            if spec.is_demo and sequence == 1:
                channel = InteractionChannel.SIMULATED_SMS
            elif pending_recovery is not None and pending_recovery["action_type"] is RecoveryActionType.ALTERNATIVE_DONOR:
                channel = InteractionChannel.SIMULATED_CALL
            else:
                channel = _weighted(rng, {
                    InteractionChannel.SIMULATED_SMS: 45,
                    InteractionChannel.SIMULATED_APP: 30,
                    InteractionChannel.SIMULATED_CALL: 25,
                })

            # Cascade order: each later attempt has a strictly lower priority.
            priority = round(_clamp(0.93 - 0.06 * (sequence - 1) + rng.gauss(0, 0.03), 0.3, 0.99), 3)
            if ctx.attempts:
                priority = min(priority, round(ctx.attempts[-1]["priority_score"] - 0.01, 3))
            attempt_id = self._next_id("coordination_attempts")
            attempt = self._add(ctx, "coordination_attempts", {
                "id": attempt_id,
                "attempt_code": f"ATT-{attempt_id:05d}",
                "blood_request_id": spec.id,
                "donor_id": donor + 1,
                "sequence_number": sequence,
                "priority_score": priority,
                "status": CoordinationStatus.INITIATED,
                "started_at": cursor,
                "completed_at": None,
                "outcome": None,
                "failure_reason": None,
            })
            ctx.attempts.append(attempt)

            resolved_recovery = pending_recovery
            if resolved_recovery is not None:
                resolved_recovery.update(target_donor_id=donor + 1, status=RecoveryStatus.COMPLETED, completed_at=cursor)
                pending_recovery = None

            self._run_attempt(ctx, attempt, plan, donor, channel)
            if plan.outcome is None:
                break  # still waiting for this donor

            completed: datetime = attempt["completed_at"]
            succeeded = attempt["status"] is CoordinationStatus.SUCCESS
            if succeeded:
                self._learn(ctx, donor, LearningSourceType.COORDINATION_ATTEMPT, attempt["attempt_code"],
                            LearningEventType.SUCCESSFUL_MATCH, rng.uniform(0.6, 0.9), completed + _minutes(5))
            else:
                event_type, base_signal = FAILURE_LEARNING[plan.outcome]
                self._learn(ctx, donor, LearningSourceType.COORDINATION_ATTEMPT, attempt["attempt_code"],
                            event_type, base_signal + rng.gauss(0, 0.04), completed + _minutes(1))
            if resolved_recovery is not None:
                self._learn(
                    ctx, donor, LearningSourceType.RECOVERY_ACTION, resolved_recovery["recovery_code"],
                    LearningEventType.RECOVERY_SUCCESS if succeeded else LearningEventType.RECOVERY_FAILURE,
                    rng.uniform(0.5, 0.8) if succeeded else -rng.uniform(0.2, 0.4),
                    completed + _minutes(2),
                )

            if succeeded:
                cursor = completed + _minutes(rng.randint(30, 90))  # next unit, if any
                continue

            failure_count += 1
            is_last = sequence == len(spec.plan)
            open_ending = still_open and is_last
            severity_index = URGENCY_ORDER.index(spec.urgency) + (1 if failure_count >= 3 else 0)
            failure_id = self._next_id("failures")
            self._add(ctx, "failures", {
                "id": failure_id,
                "failure_code": f"FLR-{failure_id:05d}",
                "coordination_attempt_id": attempt_id,
                "failure_category": plan.category,
                "failure_reason": attempt["failure_reason"],
                "severity": list(FailureSeverity)[min(severity_index, len(FailureSeverity) - 1)],
                "detected_at": completed,
                "recommended_action": RECOMMENDED_ACTIONS[plan.category],
                # The newest failure of a request that is still recovering awaits autopsy.
                "analyzed": not open_ending,
                "created_at": completed,
            })

            assert plan.category is not None
            action = self._choose_recovery(plan.category, failure_count, spec.urgency, open_ending)
            recovery_id = self._next_id("recovery_actions")
            recovery = self._add(ctx, "recovery_actions", {
                "id": recovery_id,
                "recovery_code": f"RCV-{recovery_id:05d}",
                "failure_id": failure_id,
                "blood_request_id": spec.id,
                "action_type": action,
                "description": RECOVERY_DESCRIPTIONS[action],
                "target_donor_id": None,
                "target_bridge_group_id": ctx.bridge_group_id if action is RecoveryActionType.BRIDGE_GROUP_ESCALATION else None,
                "status": RecoveryStatus.PENDING,
                "initiated_at": completed + _minutes(rng.randint(3, 15)),
                "completed_at": None,
            })
            if not open_ending:
                pending_recovery = recovery
                continue
            recovery["status"] = RecoveryStatus.IN_PROGRESS if rng.random() < 0.7 else RecoveryStatus.PENDING
            if action not in (RecoveryActionType.BLOOD_BANK_REFERRAL, RecoveryActionType.HUMAN_COORDINATOR_REVIEW):
                target = self._pick_attempt_donor(spec, pool, responders, used, _SUCCESS, recovery, recovery["initiated_at"])
                recovery["target_donor_id"] = target + 1

        if spec.is_current:
            self._anchor_to_now(ctx, request)
        self._record_history(ctx)

    def _anchor_to_now(self, ctx: _RequestContext, request: Row) -> None:
        """Shift a current request's timeline so its latest event lands shortly before REFERENCE_NOW."""
        rng = self.rng
        lo, hi = CURRENT_LAST_EVENT_MINUTES[request["status"]]
        moments = [v for row in ctx.rows for k, v in row.items() if isinstance(v, datetime) and k != "required_by"]
        delta = (REFERENCE_NOW - _minutes(rng.randint(lo, hi))) - max(moments)
        for row in ctx.rows:
            for key, value in row.items():
                if isinstance(value, datetime) and key != "required_by":
                    row[key] = value + delta
        # Broadcast checks sent in the last few hours have simply not been answered yet.
        for row in ctx.interactions:
            recent = REFERENCE_NOW - row["initiated_at"] < timedelta(hours=4)
            if (row["interaction_type"] is InteractionType.AVAILABILITY_CHECK and recent
                    and row["response_status"] is InteractionResponseStatus.NO_RESPONSE):
                row.update(response_status=InteractionResponseStatus.PENDING, failure_reason=None)

    def _record_history(self, ctx: _RequestContext) -> None:
        for row in ctx.interactions:
            donor = row["donor_id"] - 1
            self.contacts[donor].append(row["initiated_at"])
            if row["response_status"] is not InteractionResponseStatus.PENDING:
                self.answered[donor].append(row["response_status"] is not InteractionResponseStatus.NO_RESPONSE)
        for attempt in ctx.attempts:
            donor = attempt["donor_id"] - 1
            if attempt["status"] is CoordinationStatus.SUCCESS:
                self.attempt_results[donor].append(True)
                self.donations[donor].append(attempt["completed_at"])
            elif attempt["status"] is CoordinationStatus.FAILED:
                self.attempt_results[donor].append(False)

    # ---- donor state -------------------------------------------------------

    def _donor_states(self) -> None:
        """Plausible state values derived from latent traits plus simulated history.
        `current_priority_score` is a placeholder until the Donor State Engine exists."""
        rng = self.rng
        recent_window = timedelta(days=30)
        for index, donor in enumerate(self.rows["donors"]):
            traits = self.traits[index]
            donation_times = [t for t in [traits.base_last_donation, *self.donations[index]] if t is not None]
            last_donation = max(donation_times, default=None)
            days_since_donation = (REFERENCE_NOW - last_donation).days if last_donation else None
            contacts = self.contacts[index]
            days_since_contact = (REFERENCE_NOW - max(contacts)).days if contacts else traits.base_days_since_contact

            if traits.ineligible:
                eligibility = EligibilityStatus.INELIGIBLE
            elif days_since_donation is not None and days_since_donation < DONATION_INTERVAL_DAYS:
                eligibility = EligibilityStatus.TEMPORARILY_DEFERRED
            else:
                eligibility = EligibilityStatus.ELIGIBLE

            availability = _weighted(rng, {
                AvailabilityStatus.AVAILABLE: 58, AvailabilityStatus.LIMITED: 27, AvailabilityStatus.UNAVAILABLE: 15,
            })
            if not donor["active"]:
                availability = AvailabilityStatus.UNAVAILABLE

            answers = self.answered[index]
            response_rate = traits.responsiveness if not answers else 0.6 * traits.responsiveness + 0.4 * sum(answers) / len(answers)
            results = self.attempt_results[index]
            reliability = traits.reliability if not results else 0.7 * traits.reliability + 0.3 * sum(results) / len(results)

            recent_contacts = sum(1 for t in contacts if REFERENCE_NOW - t <= recent_window)
            fatigue = (
                0.05 + 0.1 * recent_contacts
                + (0.2 if days_since_donation is not None and days_since_donation < 120 else 0.0)
                + (rng.uniform(0.35, 0.55) if traits.fatigue_prone else 0.0)
                + rng.gauss(0, 0.04)
            )
            fatigue = _clamp(fatigue)

            priority = 0.45 * reliability + 0.30 * response_rate + 0.25 * (1 - fatigue)
            if eligibility is not EligibilityStatus.ELIGIBLE or availability is AvailabilityStatus.UNAVAILABLE:
                priority *= 0.35
            elif availability is AvailabilityStatus.LIMITED:
                priority *= 0.75

            self.rows["donor_states"].append({
                "id": index + 1,
                "donor_id": donor["id"],
                "availability_status": availability,
                "eligibility_status": eligibility,
                "reliability_score": round(reliability, 3),
                "response_rate": round(response_rate, 3),
                "fatigue_score": round(fatigue, 3),
                "donation_count": traits.base_donation_count + len(self.donations[index]),
                "days_since_last_donation": days_since_donation,
                "days_since_last_contact": days_since_contact,
                "current_priority_score": round(priority, 3),
                "updated_at": REFERENCE_NOW,
            })


def generate_dataset(seed: int = SEED) -> Dataset:
    """Build the full synthetic dataset in memory. Pure and deterministic."""
    return _Generator(seed).run()


def dataset_fingerprint(dataset: Dataset) -> str:
    """Stable hash of every row, used to prove reproducibility."""
    digest = hashlib.sha256()
    for table in TABLE_ORDER:
        for row in dataset[table]:
            digest.update(repr(sorted(row.items())).encode())
    return digest.hexdigest()
