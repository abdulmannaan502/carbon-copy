"""Donor State Intelligence Engine.

Computes a donor's current operational coordination state from observable
synthetic data: interaction history, coordination attempts and the donor's
registry record. Answers "what is the current state of this donor, and how
suitable are they for this request, and why?". It does not choose donors; that
is the future Matching Engine's job.

Sources of truth
----------------
* This engine is authoritative for availability, eligibility, reliability,
  response behaviour, fatigue, freshness and priority.
* The persisted `donor_states` row is a seeded baseline. The engine reads only
  its registry-type inputs (declared availability, the registry deferral flag
  and the donation record) and ignores its placeholder scores.

All rules are deterministic demo coordination rules: no LLM, no clinical claims.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.blood import COMPATIBLE_DONORS
from app.core.clock import DATASET_REFERENCE_TIME
from app.core.config import DATA_NOTICE
from app.models import BloodRequest, Donor
from app.models.enums import AvailabilityStatus, EligibilityStatus, RequestStatus, UrgencyLevel
from app.repositories.donor_state_repository import DonorObservations, DonorStateRepository
from app.schemas.donor_state import (
    AvailabilityAssessment,
    CompatibilityAssessment,
    CoordinationAvailability,
    DataSufficiency,
    DonorComparison,
    DonorIdentity,
    DonorRequestAssessment,
    DonorStateAssessment,
    EligibilityAssessment,
    EligibilityCheck,
    EvaluationPoint,
    FatigueAssessment,
    FatigueBand,
    FreshnessAssessment,
    Impact,
    PriorityAssessment,
    PriorityBand,
    PriorityFactor,
    PriorityReason,
    ReliabilityAssessment,
    RequestSummary,
    ResponseBehavior,
    ScoreBand,
    WeightProfile,
)

# ---- demo coordination settings --------------------------------------------------

DONATION_INTERVAL_DAYS = 90          # demo rule shared with the synthetic generator
RECENT_CONTACT_DAYS = 3              # avoid repeat outreach inside this window
UNAVAILABLE_REPLY_DAYS = 14          # an "unavailable" reply is honoured this long
ACTIVITY_WINDOW_DAYS = 30            # window for fatigue counts
FRESHNESS_FULL_DAYS = 30             # days without contact for full freshness
MIN_RESPONSE_OBSERVATIONS = 3        # below this, response rates are not reported
PRIOR_DONATION_CAP = 10              # registry donations counted toward reliability
PRIOR_DONATION_WEIGHT = 0.2
RECENT_DONATION_FATIGUE_DAYS = 120

ACTIVE_REQUEST_STATUSES = frozenset(
    {RequestStatus.OPEN, RequestStatus.MATCHING, RequestStatus.COORDINATING, RequestStatus.RECOVERING}
)

FACTOR_LABELS = {
    "availability": "Availability",
    "reliability": "Reliability",
    "response": "Response",
    "fatigue": "Low fatigue",
    "freshness": "Freshness",
    "context": "Request fit",
}
# How a lead on each factor reads in a comparison sentence.
LEAD_PHRASES = {
    "availability": "better availability",
    "reliability": "higher reliability",
    "response": "stronger response behaviour",
    "fatigue": "lower coordination fatigue",
    "freshness": "less recent contact",
    "context": "better request fit",
}
# Percent weights. Eligibility (including compatibility) is a gate, not a weight.
WEIGHT_PROFILES: dict[WeightProfile, dict[str, int]] = {
    WeightProfile.GENERAL: {"availability": 30, "reliability": 25, "response": 20, "fatigue": 15, "freshness": 10},
    WeightProfile.STANDARD: {
        "availability": 25, "reliability": 25, "response": 20, "fatigue": 10, "freshness": 10, "context": 10,
    },
    # HIGH / CRITICAL requests favour donors who answer quickly.
    WeightProfile.URGENT: {
        "availability": 25, "reliability": 20, "response": 30, "fatigue": 8, "freshness": 7, "context": 10,
    },
}


def _days_between(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 86_400


def _percent(numerator: int, denominator: int) -> int:
    return round(100 * numerator / denominator)


def _ago(days: int) -> str:
    return "today" if days == 0 else ("1 day ago" if days == 1 else f"{days} days ago")


def _blood(group: object) -> str:
    return str(getattr(group, "value", group)).replace("-", "−")


# ---- registry inputs ---------------------------------------------------------------


@dataclass(frozen=True)
class DonationRecord:
    count: int
    last_donation_at: datetime | None


def donation_record(donor: Donor, obs: DonorObservations, as_of: datetime) -> DonationRecord:
    """The donor's donation record as of `as_of`.

    The registry row describes the record at the dataset reference time. Donations
    the dataset shows *after* `as_of` are subtracted, and a recorded last donation
    after `as_of` is ignored (its earlier date is unknown)."""
    state = donor.state_record
    count = max(0, (state.donation_count if state else 0) - obs.successes_after)
    recorded = None
    if state and state.days_since_last_donation is not None:
        recorded = DATASET_REFERENCE_TIME - timedelta(days=state.days_since_last_donation)
        if recorded > as_of:
            recorded = None
    candidates = [t for t in (recorded, obs.last_success_at) if t is not None]
    return DonationRecord(count=count, last_donation_at=max(candidates, default=None))


# ---- pure rules ------------------------------------------------------------------


def assess_availability(donor: Donor, obs: DonorObservations, as_of: datetime) -> AvailabilityAssessment:
    declared = donor.state_record.availability_status if donor.state_record else None
    days_since_contact = int(_days_between(as_of, obs.last_contact_at)) if obs.last_contact_at else None
    unavailable_reply_days = (
        _days_between(as_of, obs.last_unavailable_reply_at) if obs.last_unavailable_reply_at else None
    )

    if not donor.active:
        status, reason = CoordinationAvailability.INACTIVE, "Donor record is inactive."
    elif declared is AvailabilityStatus.UNAVAILABLE:
        status, reason = CoordinationAvailability.TEMPORARILY_UNAVAILABLE, "Declared unavailable in the donor registry."
    elif unavailable_reply_days is not None and unavailable_reply_days < UNAVAILABLE_REPLY_DAYS:
        status = CoordinationAvailability.TEMPORARILY_UNAVAILABLE
        reason = f"Replied 'unavailable' {_ago(int(unavailable_reply_days))} (honoured for {UNAVAILABLE_REPLY_DAYS} days)."
    elif obs.pending:
        status, reason = CoordinationAvailability.RECENTLY_CONTACTED, "Awaiting a reply to an outreach message."
    elif days_since_contact is not None and _days_between(as_of, obs.last_contact_at) < RECENT_CONTACT_DAYS:  # type: ignore[arg-type]
        status = CoordinationAvailability.RECENTLY_CONTACTED
        reason = f"Contacted {_ago(days_since_contact)}; no repeat outreach within {RECENT_CONTACT_DAYS} days."
    else:
        status = CoordinationAvailability.AVAILABLE
        reason = (
            "Available, with limited declared availability."
            if declared is AvailabilityStatus.LIMITED
            else "No recent contact or unavailability signal."
        )
    return AvailabilityAssessment(
        availability_status=status,
        availability_reason=reason,
        declared_availability=declared,
        last_contacted_at=obs.last_contact_at,
        days_since_last_contact=days_since_contact,
        awaiting_reply=obs.pending > 0,
    )


def availability_score(availability: AvailabilityAssessment) -> int:
    if availability.availability_status is CoordinationAvailability.AVAILABLE:
        return 60 if availability.declared_availability is AvailabilityStatus.LIMITED else 100
    if availability.availability_status is CoordinationAvailability.RECENTLY_CONTACTED:
        return 40
    return 0


def assess_eligibility(
    donor: Donor, record: DonationRecord, as_of: datetime, request: BloodRequest | None
) -> EligibilityAssessment:
    """Demo coordination eligibility rules. Every check is a gate."""
    checks: list[EligibilityCheck] = []
    if request is not None:
        compatible = donor.blood_group in COMPATIBLE_DONORS[request.blood_group]
        checks.append(EligibilityCheck(
            rule="blood_group_compatibility",
            passed=compatible,
            detail=f"{_blood(donor.blood_group)} donor {'is' if compatible else 'is not'} compatible with a "
                   f"{_blood(request.blood_group)} request (simplified ABO/Rh demo table).",
        ))
    checks.append(EligibilityCheck(
        rule="active_donor", passed=donor.active,
        detail="Active donor record." if donor.active else "Donor record is inactive.",
    ))
    deferred = donor.state_record is not None and donor.state_record.eligibility_status is EligibilityStatus.INELIGIBLE
    checks.append(EligibilityCheck(
        rule="registry_deferral", passed=not deferred,
        detail="Registry deferral flag set (synthetic)." if deferred else "No registry deferral flag.",
    ))
    days_since = int(_days_between(as_of, record.last_donation_at)) if record.last_donation_at else None
    interval_ok = days_since is None or days_since >= DONATION_INTERVAL_DAYS
    checks.append(EligibilityCheck(
        rule="donation_interval", passed=interval_ok,
        detail=(
            "No donation on record." if days_since is None
            else f"Last donation {_ago(days_since)} "
                 f"({'meets' if interval_ok else 'within'} the {DONATION_INTERVAL_DAYS}-day demo interval)."
        ),
    ))
    return EligibilityAssessment(
        eligible=all(c.passed for c in checks),
        checks=checks,
        eligibility_reasons=[c.detail for c in checks],
        donation_count=record.count,
        last_donation_at=record.last_donation_at,
        days_since_last_donation=days_since,
    )


def assess_reliability(obs: DonorObservations, record: DonationRecord) -> ReliabilityAssessment:
    """Coordination track record, Laplace-smoothed so it starts at 50 with no evidence.

    positive = successful attempts + 0.2 × min(prior registry donations, 10)
    negative = 1.0 × no-response failures + 0.5 × declined/unavailable failures + 0.25 × other failures
    score    = 100 × (positive + 1) ÷ (positive + negative + 2)
    """
    prior = max(0, record.count - obs.successes)
    counted_prior = min(prior, PRIOR_DONATION_CAP)
    positive = obs.successes + PRIOR_DONATION_WEIGHT * counted_prior
    negative = obs.no_response_failures + 0.5 * obs.declined_failures + 0.25 * obs.other_failures
    score = round(100 * (positive + 1) / (positive + negative + 2))
    band = ScoreBand.HIGH if score >= 70 else ScoreBand.MEDIUM if score >= 45 else ScoreBand.LOW

    factors: list[str] = []
    if obs.successes:
        factors.append(f"{obs.successes} successful coordination attempt(s)")
    if obs.no_response_failures:
        factors.append(f"{obs.no_response_failures} attempt(s) failed with no response")
    if obs.declined_failures:
        factors.append(f"{obs.declined_failures} attempt(s) declined or unavailable")
    if obs.other_failures:
        factors.append(f"{obs.other_failures} attempt(s) failed for other reasons")
    if counted_prior:
        factors.append(f"{prior} earlier donation(s) on record" + (f" ({counted_prior} counted)" if prior > counted_prior else ""))
    if positive + negative < 2:
        factors.append("Limited history: score stays close to the neutral starting point of 50")

    return ReliabilityAssessment(
        reliability_score=score,
        reliability_band=band,
        successful_attempts=obs.successes,
        failed_attempts=obs.no_response_failures + obs.declined_failures + obs.other_failures,
        no_response_failures=obs.no_response_failures,
        declined_or_unavailable_failures=obs.declined_failures,
        other_failures=obs.other_failures,
        prior_donations_counted=counted_prior,
        evidence_weight=round(positive + negative, 2),
        reliability_factors=factors,
    )


def assess_response(obs: DonorObservations) -> ResponseBehavior:
    """Response score = 100 × (responses + 1) ÷ (interactions + 2). Reported rates need ≥ 3 interactions."""
    responses = obs.responded + obs.accepted + obs.declined + obs.unavailable
    sufficient = obs.interactions >= MIN_RESPONSE_OBSERVATIONS
    return ResponseBehavior(
        total_interactions=obs.interactions,
        total_responses=responses,
        acceptances=obs.accepted,
        declines=obs.declined,
        unavailable_replies=obs.unavailable,
        no_responses=obs.no_response,
        pending=obs.pending,
        donation_requests=obs.donation_requests,
        data_sufficiency=DataSufficiency.SUFFICIENT if sufficient else DataSufficiency.INSUFFICIENT_DATA,
        response_rate=_percent(responses, obs.interactions) if sufficient else None,
        acceptance_rate=(
            _percent(obs.accepted, obs.donation_requests) if sufficient and obs.donation_requests else None
        ),
        no_response_rate=_percent(obs.no_response, obs.interactions) if sufficient else None,
        response_score=round(100 * (responses + 1) / (obs.interactions + 2)),
    )


def assess_fatigue(obs: DonorObservations, days_since_donation: int | None) -> FatigueAssessment:
    """Coordination fatigue (outreach load), 0–100:
    min(10 × contacts in 30 days, 50) + min(15 × (distinct requests in 30 days − 1), 30)
    + 20 if the donor donated within 120 days."""
    contact_points = min(10 * obs.contacts_in_window, 50)
    request_points = min(15 * max(obs.requests_in_window - 1, 0), 30)
    donation_points = 20 if days_since_donation is not None and days_since_donation < RECENT_DONATION_FATIGUE_DAYS else 0
    score = min(100, contact_points + request_points + donation_points)

    reasons: list[str] = []
    if contact_points:
        reasons.append(f"{obs.contacts_in_window} contact(s) in the last {ACTIVITY_WINDOW_DAYS} days (+{contact_points})")
    if request_points:
        reasons.append(f"Contacted for {obs.requests_in_window} different requests (+{request_points})")
    if donation_points:
        reasons.append(f"Donated {_ago(days_since_donation or 0)} (+{donation_points})")
    if not reasons:
        reasons.append(f"No coordination contacts in the last {ACTIVITY_WINDOW_DAYS} days")
    band = FatigueBand.HIGH if score >= 60 else FatigueBand.MODERATE if score >= 30 else FatigueBand.LOW
    return FatigueAssessment(
        fatigue_score=score,
        fatigue_band=band,
        contacts_last_30_days=obs.contacts_in_window,
        requests_last_30_days=obs.requests_in_window,
        fatigue_reasons=reasons,
    )


def assess_freshness(obs: DonorObservations, as_of: datetime) -> FreshnessAssessment:
    """0 right after a contact, rising linearly to 100 at 30 days; 100 with no contact on record."""
    if obs.last_contact_at is None:
        return FreshnessAssessment(days_since_last_contact=None, contact_freshness_score=100)
    days = _days_between(as_of, obs.last_contact_at)
    return FreshnessAssessment(
        days_since_last_contact=int(days),
        contact_freshness_score=min(100, round(100 * days / FRESHNESS_FULL_DAYS)),
    )


def context_score(donor: Donor, request: BloodRequest) -> tuple[int, list[PriorityReason]]:
    """Exact blood-group match 100 / compatible substitute 70; same city 100 / same district 75 / elsewhere 40."""
    exact = donor.blood_group is request.blood_group
    if donor.city == request.city:
        location, location_text = 100, f"Same city as the request ({request.city})"
    elif donor.district == request.district:
        location, location_text = 75, f"Same district as the request ({request.district})"
    else:
        location, location_text = 40, f"Different area from the request ({donor.city} vs {request.city})"
    reasons = [
        PriorityReason(text=f"Exact blood group match ({_blood(donor.blood_group)})", impact=Impact.POSITIVE)
        if exact else
        PriorityReason(
            text=f"Compatible substitute ({_blood(donor.blood_group)} donor for a {_blood(request.blood_group)} request)",
            impact=Impact.NEUTRAL,
        ),
        PriorityReason(text=location_text, impact=Impact.POSITIVE if location == 100 else Impact.NEUTRAL if location == 75 else Impact.NEGATIVE),
    ]
    return round(((100 if exact else 70) + location) / 2), reasons


def weight_profile_for(request: BloodRequest | None) -> WeightProfile:
    if request is None:
        return WeightProfile.GENERAL
    return WeightProfile.URGENT if request.urgency_level in (UrgencyLevel.HIGH, UrgencyLevel.CRITICAL) else WeightProfile.STANDARD


def assess_priority(
    *,
    eligibility: EligibilityAssessment,
    availability: AvailabilityAssessment,
    reliability: ReliabilityAssessment,
    response: ResponseBehavior,
    fatigue: FatigueAssessment,
    freshness: FreshnessAssessment,
    context: tuple[int, list[PriorityReason]] | None,
    profile: WeightProfile,
) -> PriorityAssessment:
    scores = {
        "availability": availability_score(availability),
        "reliability": reliability.reliability_score,
        "response": response.response_score,
        "fatigue": 100 - fatigue.fatigue_score,
        "freshness": freshness.contact_freshness_score,
    }
    if context is not None:
        scores["context"] = context[0]
    weights = WEIGHT_PROFILES[profile]
    gated = not eligibility.eligible
    factors = [
        PriorityFactor(
            key=key, label=FACTOR_LABELS[key], score=scores[key], weight=weight,
            contribution=0.0 if gated else round(weight * scores[key] / 100, 1),
        )
        for key, weight in weights.items()
    ]
    score = 0 if gated else max(0, min(100, round(sum(weight * scores[key] / 100 for key, weight in weights.items()))))
    if gated:
        band = PriorityBand.NOT_ELIGIBLE
    else:
        band = PriorityBand.HIGH if score >= 70 else PriorityBand.MEDIUM if score >= 45 else PriorityBand.LOW

    reasons: list[PriorityReason] = [
        PriorityReason(text=f"Not eligible: {check.detail}", impact=Impact.NEGATIVE)
        for check in eligibility.checks if not check.passed
    ]
    if eligibility.eligible:
        reasons.append(PriorityReason(text="Meets demo coordination eligibility rules", impact=Impact.POSITIVE))
    if context is not None:
        reasons.extend(context[1])

    status = availability.availability_status
    if status is CoordinationAvailability.AVAILABLE:
        reasons.append(PriorityReason(
            text="Currently available" + (" (limited declared availability)" if scores["availability"] < 100 else ""),
            impact=Impact.POSITIVE if scores["availability"] == 100 else Impact.NEUTRAL,
        ))
    else:
        reasons.append(PriorityReason(text=availability.availability_reason, impact=Impact.NEGATIVE))

    band_text = {ScoreBand.HIGH: ("Strong", Impact.POSITIVE), ScoreBand.MEDIUM: ("Moderate", Impact.NEUTRAL),
                 ScoreBand.LOW: ("Weak", Impact.NEGATIVE)}[reliability.reliability_band]
    reasons.append(PriorityReason(
        text=f"{band_text[0]} coordination track record ({reliability.reliability_score}/100)", impact=band_text[1]
    ))

    if response.data_sufficiency is DataSufficiency.INSUFFICIENT_DATA:
        if response.total_interactions == 0:
            reasons.append(PriorityReason(text="No messaging history yet", impact=Impact.NEUTRAL))
        else:
            reasons.append(PriorityReason(
                text=f"Limited messaging history: {response.total_responses} of "
                     f"{response.total_interactions} message(s) answered",
                impact=Impact.NEGATIVE if not response.total_responses else Impact.NEUTRAL,
            ))
    elif response.response_rate is not None:
        rate = response.response_rate
        reasons.append(PriorityReason(
            text=f"{'High' if rate >= 70 else 'Moderate' if rate >= 40 else 'Low'} historical response rate ({rate}%)",
            impact=Impact.POSITIVE if rate >= 70 else Impact.NEUTRAL if rate >= 40 else Impact.NEGATIVE,
        ))

    fatigue_impact = {FatigueBand.LOW: Impact.POSITIVE, FatigueBand.MODERATE: Impact.NEUTRAL,
                      FatigueBand.HIGH: Impact.NEGATIVE}[fatigue.fatigue_band]
    reasons.append(PriorityReason(
        text=f"{fatigue.fatigue_band.value.capitalize()} coordination fatigue ({fatigue.fatigue_score}/100)",
        impact=fatigue_impact,
    ))

    if freshness.days_since_last_contact is None:
        reasons.append(PriorityReason(text="No previous contact on record", impact=Impact.POSITIVE))
    elif freshness.contact_freshness_score >= 70:
        reasons.append(PriorityReason(text=f"Not recently contacted (last {_ago(freshness.days_since_last_contact)})", impact=Impact.POSITIVE))
    elif freshness.contact_freshness_score < 30:
        reasons.append(PriorityReason(text=f"Recently contacted ({_ago(freshness.days_since_last_contact)})", impact=Impact.NEGATIVE))

    return PriorityAssessment(
        priority_score=score,
        priority_band=band,
        gated=gated,
        weight_profile=profile,
        priority_factors=factors,
        priority_reasons=reasons,
    )


# ---- engine ------------------------------------------------------------------------


class UnknownCode(LookupError):
    """A donor or request code that does not exist."""

    def __init__(self, kind: str, code: str) -> None:
        super().__init__(f"{kind} {code} not found")
        self.kind = kind
        self.code = code



def _identity(donor: Donor) -> DonorIdentity:
    return DonorIdentity(
        donor_code=donor.donor_code,
        display_name=donor.display_name,
        blood_group=donor.blood_group,
        city=donor.city, district=donor.district, state=donor.state,
        bridge_group_code=donor.bridge_group.group_code if donor.bridge_group else None,
        active=donor.active,
    )


def request_summary(request: BloodRequest) -> RequestSummary:
    return RequestSummary(
        request_code=request.request_code,
        patient_code=request.patient.patient_code,
        blood_group=request.blood_group,
        urgency_level=request.urgency_level,
        status=request.status,
        city=request.city,
        requested_at=request.requested_at,
        required_by=request.required_by,
    )


class DonorStateEngine:
    def __init__(self, repository: DonorStateRepository, now: datetime) -> None:
        self._repo = repository
        self._now = now

    # -- core ----------------------------------------------------------------------

    def assess_donors(
        self,
        donors: Sequence[Donor],
        as_of: datetime,
        request: BloodRequest | None = None,
        evaluation_point: EvaluationPoint = EvaluationPoint.CURRENT,
    ) -> dict[int, DonorStateAssessment]:
        """Assess any number of donors with a constant number of queries."""
        observations = self._repo.observations(
            [d.id for d in donors], as_of, as_of - timedelta(days=ACTIVITY_WINDOW_DAYS)
        )
        profile = weight_profile_for(request)
        results: dict[int, DonorStateAssessment] = {}
        for donor in donors:
            obs = observations[donor.id]
            record = donation_record(donor, obs, as_of)
            availability = assess_availability(donor, obs, as_of)
            eligibility = assess_eligibility(donor, record, as_of, request)
            reliability = assess_reliability(obs, record)
            response = assess_response(obs)
            fatigue = assess_fatigue(obs, eligibility.days_since_last_donation)
            freshness = assess_freshness(obs, as_of)
            priority = assess_priority(
                eligibility=eligibility, availability=availability, reliability=reliability, response=response,
                fatigue=fatigue, freshness=freshness,
                context=context_score(donor, request) if request is not None else None,
                profile=profile,
            )
            results[donor.id] = DonorStateAssessment(
                assessed_at=as_of,
                evaluation_point=evaluation_point,
                donor=_identity(donor),
                availability=availability,
                eligibility=eligibility,
                reliability=reliability,
                response=response,
                fatigue=fatigue,
                freshness=freshness,
                priority=priority,
                data_notice=DATA_NOTICE,
            )
        return results

    def assess_ids(self, donor_ids: Sequence[int]) -> dict[int, DonorStateAssessment]:
        """Current state for a set of donors (used by the Digital Twin's network view)."""
        return self.assess_donors(self._repo.get_donors_by_ids(donor_ids), self._now)

    # -- public operations ------------------------------------------------------------

    def assess(self, donor_code: str) -> DonorStateAssessment | None:
        donor = self._repo.get_donor(donor_code)
        return self.assess_donors([donor], self._now)[donor.id] if donor else None

    def evaluation(self, request: BloodRequest, evaluate_at: str) -> tuple[datetime, EvaluationPoint, str]:
        """'auto': active requests are assessed now; resolved ones at the moment coordination began."""
        if evaluate_at == "now" or (evaluate_at == "auto" and request.status in ACTIVE_REQUEST_STATUSES):
            return self._now, EvaluationPoint.CURRENT, "Assessed with everything known now."
        return (
            request.requested_at,
            EvaluationPoint.REQUEST_START,
            f"Request is {request.status.value.lower()}; assessed as of when coordination began "
            f"({request.requested_at:%d %b %Y %H:%M} UTC), using only history known at that time.",
        )

    def _request_assessment(
        self, donor: Donor, request: BloodRequest, state: DonorStateAssessment, note: str
    ) -> DonorRequestAssessment:
        groups = COMPATIBLE_DONORS[request.blood_group]
        return DonorRequestAssessment(
            request=request_summary(request),
            compatibility=CompatibilityAssessment(
                request_blood_group=request.blood_group,
                donor_blood_group=donor.blood_group,
                compatible=donor.blood_group in groups,
                exact_match=donor.blood_group is request.blood_group,
                compatible_donor_groups=list(groups),
            ),
            evaluation_note=note,
            state=state,
        )

    def assess_for_request(
        self, donor_code: str, request_code: str, evaluate_at: str = "auto"
    ) -> DonorRequestAssessment:
        donor = self._repo.get_donor(donor_code)
        if donor is None:
            raise UnknownCode("Donor", donor_code)
        request = self._repo.get_request(request_code)
        if request is None:
            raise UnknownCode("Request", request_code)
        as_of, point, note = self.evaluation(request, evaluate_at)
        state = self.assess_donors([donor], as_of, request, point)[donor.id]
        return self._request_assessment(donor, request, state, note)

    def compare_for_request(
        self, request_code: str, donor_codes: Sequence[str] | None = None, evaluate_at: str = "auto"
    ) -> DonorComparison:
        """Compare listed donors (default: the donors this request's cascade contacted)."""
        request = self._repo.get_request(request_code)
        if request is None:
            raise UnknownCode("Request", request_code)
        codes = list(dict.fromkeys(donor_codes or self._repo.attempted_donor_codes(request.id)))
        donors = self._repo.get_donors_by_codes(codes)
        missing = sorted(set(codes) - {d.donor_code for d in donors})
        if missing:
            raise UnknownCode("Donor", ", ".join(missing))
        as_of, point, note = self.evaluation(request, evaluate_at)
        states = self.assess_donors(donors, as_of, request, point)
        candidates = sorted(
            (self._request_assessment(d, request, states[d.id], note) for d in donors),
            key=lambda c: (-c.state.priority.priority_score, -c.state.reliability.reliability_score,
                           c.state.donor.donor_code),
        )
        recommended, reason = recommendation(candidates)
        return DonorComparison(
            request=request_summary(request),
            evaluation_point=point,
            assessed_at=as_of,
            candidates=candidates,
            recommended_donor_code=recommended,
            recommendation_reason=reason,
        )


def recommendation(candidates: Sequence[DonorRequestAssessment]) -> tuple[str | None, str]:
    """Explain why the top-ranked eligible donor leads the runner-up."""
    eligible = [c for c in candidates if c.state.eligibility.eligible]
    if not eligible:
        return None, "None of the listed donors meets the demo coordination eligibility rules."
    best = eligible[0]
    code = best.state.donor.donor_code
    if len(candidates) == 1:
        return code, "Only donor in the comparison."
    runner_up = next(c for c in candidates if c is not best)
    if not runner_up.state.eligibility.eligible:
        failed = next(check.detail for check in runner_up.state.eligibility.checks if not check.passed)
        return code, f"{runner_up.state.donor.donor_code} is not eligible under demo rules: {failed}"
    theirs = {f.key: f.score for f in runner_up.state.priority.priority_factors}
    leads = sorted(
        ((f.score - theirs[f.key], f) for f in best.state.priority.priority_factors if f.score - theirs[f.key] >= 5),
        key=lambda item: -item[0] * item[1].weight,
    )[:2]
    margin = best.state.priority.priority_score - runner_up.state.priority.priority_score
    if not leads:
        return code, f"Highest operational priority by {margin} point(s); the donors are otherwise similar."
    described = " and ".join(f"{LEAD_PHRASES[f.key]} (+{gap})" for gap, f in leads)
    return code, f"{described[0].upper()}{described[1:]}; leads {runner_up.state.donor.donor_code} by {margin} priority point(s)."
