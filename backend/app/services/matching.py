"""Matching Engine: "for this blood request, which donors are the best candidates to contact, and why?"

Pipeline
--------
request → candidate discovery (SQL) → compatibility gate (SQL) → eligibility gate (Donor State Engine)
        → candidate state assessment (Donor State Engine, one batch) → contextual ranking → explanation

The Donor State Engine is the single source of truth for every donor-level value (availability,
eligibility, reliability, response, fatigue, freshness and operational priority). Matching adds only
what is specific to the request: patient link, distance, coordination context, urgency weighting and a
small deterministic exploration bonus. It does not decide contact order or recovery; that is the
Adaptive Cascade's job.

Everything is deterministic: no randomness, no LLM, explicit tie-breakers ending in donor_code.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from math import cos, radians

from app.core.blood import COMPATIBLE_DONORS
from app.core.config import DATA_NOTICE
from app.core.geo import bounding_box, haversine_km
from app.models import BloodRequest, Donor
from app.models.enums import InteractionResponseStatus, UrgencyLevel
from app.repositories.matching_repository import MatchingRepository, RequestHistory
from app.schemas.donor_state import (
    CoordinationAvailability,
    DataSufficiency,
    DonorStateAssessment,
    FatigueBand,
    Impact,
    ScoreBand,
    WeightProfile,
)
from app.schemas.matching import (
    CandidateStrategy,
    DiscoveryInfo,
    EvaluationInfo,
    ExclusionCount,
    MatchCandidate,
    MatchingResult,
    MatchingSummary,
    MatchingWeights,
    MatchReason,
    ScoreComponent,
    TwinContext,
)
from app.services.digital_twin import DigitalTwinService
from app.services.donor_state import DonorStateEngine, UnknownCode, request_summary

# ---- demo matching settings ---------------------------------------------------------------

RADIUS_STEPS_KM: tuple[float | None, ...] = (30.0, 80.0, None)  # None = whole dataset region
MIN_POOL = 40                     # expand the radius until at least this many compatible donors are found
POOL_CAP = 400                    # nearest compatible donors assessed per request
RECENT_WINDOW_DAYS = 30
GEO_ZERO_KM = 50.0                # geographic fit reaches 0 at this distance
MAX_LIMIT = 50

COMPONENT_LABELS = {
    "donor_state": "Donor state priority",
    "request_fit": "Request fit",
    "geographic_fit": "Geographic fit",
    "context": "Coordination context",
}
# HIGH/CRITICAL urgency leans on proven readiness and proximity; other requests leave more room to explore.
MATCH_WEIGHTS: dict[WeightProfile, dict[str, int]] = {
    WeightProfile.URGENT: {"donor_state": 50, "request_fit": 15, "geographic_fit": 20, "context": 15},
    WeightProfile.STANDARD: {"donor_state": 45, "request_fit": 20, "geographic_fit": 15, "context": 20},
}
# Exploration vs exploitation, by urgency (points added to the match score):
#   urgent requests discount unproven donors; other requests reward controlled exploration.
EXPLORATION_BONUS = {WeightProfile.URGENT: 0, WeightProfile.STANDARD: 5}
UNCERTAINTY_DISCOUNT = {WeightProfile.URGENT: 5, WeightProfile.STANDARD: 0}

GATE_LABELS = {
    "blood_group_compatibility": "Incompatible blood group",
    "active_donor": "Inactive donor record",
    "registry_deferral": "Registry deferral flag",
    "donation_interval": "Recent donation (within the 90-day demo interval)",
}
DECLINED_HERE = "Declined or unavailable for this request"
FAILED_HERE = "Already contacted for this request without success"
ENGAGED_HERE = "Already engaged in this request's cascade"
CONTACTED_IN_CASCADE = "Contacted earlier in this cascade"


def _blood(group: object) -> str:
    return str(getattr(group, "value", group)).replace("-", "−")


def _profile(request: BloodRequest) -> WeightProfile:
    return WeightProfile.URGENT if request.urgency_level in (UrgencyLevel.HIGH, UrgencyLevel.CRITICAL) else WeightProfile.STANDARD


# ---- pure scoring rules -----------------------------------------------------------------


def geographic_fit(distance_km: float | None) -> int:
    """100 at the request location, falling linearly to 0 at 50 km; 50 (neutral) when location is unknown."""
    if distance_km is None:
        return 50
    return round(100 * max(0.0, 1 - distance_km / GEO_ZERO_KM))


def request_fit(exact_match: bool, donated_for_patient: bool, bridge_group_member: bool) -> int:
    """0.6 × blood fit (exact 100 / compatible substitute 60, conserving scarcer groups)
    + 0.4 × patient link (donated for this patient before 100 / patient's bridge group 80 / none 50)."""
    blood = 100 if exact_match else 60
    link = 100 if donated_for_patient else 80 if bridge_group_member else 50
    return round(0.6 * blood + 0.4 * link)


@dataclass(frozen=True)
class ContextResult:
    score: int
    reasons: list[MatchReason]
    exclusion: str | None


def coordination_context(
    donor_id: int, state: DonorStateAssessment, history: RequestHistory
) -> ContextResult:
    """Request-specific coordination signals. Starts at 100; known dead ends exclude the donor."""
    reply = history.check_reply.get(donor_id)
    if donor_id in history.failed_here:
        return ContextResult(0, [], FAILED_HERE)
    if donor_id in history.engaged_here:
        return ContextResult(0, [], ENGAGED_HERE)
    if reply in (InteractionResponseStatus.DECLINED, InteractionResponseStatus.UNAVAILABLE):
        return ContextResult(0, [], DECLINED_HERE)

    score, reasons = 100, []
    if reply is InteractionResponseStatus.RESPONDED:
        reasons.append(MatchReason(text="Replied available to this request's availability check", impact=Impact.POSITIVE))
    elif reply is InteractionResponseStatus.NO_RESPONSE:
        score -= 30
        reasons.append(MatchReason(text="No reply to this request's availability check (−30)", impact=Impact.NEGATIVE))
    elif reply is InteractionResponseStatus.PENDING:
        score -= 15
        reasons.append(MatchReason(text="Availability check for this request awaiting reply (−15)", impact=Impact.NEUTRAL))

    failures = history.recent_failures.get(donor_id, 0)
    if failures:
        penalty = min(25 * failures, 50)
        score -= penalty
        reasons.append(MatchReason(
            text=f"{failures} failed coordination attempt(s) in the last {RECENT_WINDOW_DAYS} days (−{penalty})",
            impact=Impact.NEGATIVE,
        ))
    if state.fatigue.contacts_last_30_days >= 3:
        score -= 20
        reasons.append(MatchReason(
            text=f"Repeated recent contacts ({state.fatigue.contacts_last_30_days} in {RECENT_WINDOW_DAYS} days, −20)",
            impact=Impact.NEGATIVE,
        ))
    if state.availability.availability_status is CoordinationAvailability.RECENTLY_CONTACTED:
        score -= 20
        reasons.append(MatchReason(text="Contacted within the last few days (−20)", impact=Impact.NEGATIVE))
    return ContextResult(max(0, score), reasons, None)


def is_proven(state: DonorStateAssessment) -> bool:
    """≥ 1 successful attempt, ≥ 3 interactions, or reliability evidence ≥ 2 (e.g. 10 earlier donations)."""
    return (
        state.reliability.successful_attempts > 0
        or state.response.data_sufficiency is DataSufficiency.SUFFICIENT
        or state.reliability.evidence_weight >= 2
    )


def candidate_strategy(state: DonorStateAssessment, fit: int) -> tuple[CandidateStrategy, str]:
    """Deterministic exploration vs exploitation label.

    RELIABLE     proven (see is_proven) and reliability ≥ 70
                 and, when measurable, response rate ≥ 60 %
    EXPLORATION  thin history, yet available, low fatigue, not recently contacted and a good request fit
    BALANCED     everything else
    """
    reliability, response = state.reliability, state.response
    proven = is_proven(state)
    responsive = response.response_rate is None or response.response_rate >= 60
    if proven and reliability.reliability_score >= 70 and responsive:
        return CandidateStrategy.RELIABLE, "Proven donor with a strong coordination track record"
    if (
        not proven
        and state.availability.availability_status is CoordinationAvailability.AVAILABLE
        and state.fatigue.fatigue_band is FatigueBand.LOW
        and state.freshness.contact_freshness_score >= 70
        and fit >= 60
    ):
        return CandidateStrategy.EXPLORATION, (
            "Little history yet, but available, rested, not recently contacted and a good fit: "
            "selected for controlled exploration"
        )
    if not proven:
        return CandidateStrategy.BALANCED, "Limited history and at least one current constraint"
    return CandidateStrategy.BALANCED, "Some history, with a mixed or moderate track record"


def candidate_reasons(
    state: DonorStateAssessment,
    request: BloodRequest,
    distance_km: float | None,
    donated_for_patient: bool,
    bridge_group_code: str | None,
    context: ContextResult,
    strategy: CandidateStrategy,
    adjustment: int,
) -> list[MatchReason]:
    P, N, X = Impact.POSITIVE, Impact.NEUTRAL, Impact.NEGATIVE
    r: list[MatchReason] = [MatchReason(text="Eligible under demo coordination rules", impact=P)]
    donor = state.donor
    if donor.blood_group is request.blood_group:
        r.append(MatchReason(text=f"Exact blood group match ({_blood(donor.blood_group)})", impact=P))
    else:
        r.append(MatchReason(
            text=f"Compatible substitute ({_blood(donor.blood_group)} for {_blood(request.blood_group)}); scarcer group conserved",
            impact=N,
        ))

    if state.availability.availability_status is CoordinationAvailability.AVAILABLE:
        r.append(MatchReason(text="Currently available", impact=P))
    else:
        r.append(MatchReason(text=state.availability.availability_reason, impact=X))

    rel, resp = state.reliability, state.response
    thin = resp.data_sufficiency is DataSufficiency.INSUFFICIENT_DATA and rel.evidence_weight < 2
    if thin:
        r.append(MatchReason(text="Limited historical data", impact=N))
    elif rel.reliability_band is ScoreBand.HIGH:
        r.append(MatchReason(text=f"High historical reliability ({rel.reliability_score}/100)", impact=P))
    elif rel.reliability_band is ScoreBand.LOW:
        r.append(MatchReason(text=f"Weak coordination track record ({rel.reliability_score}/100)", impact=X))
    else:
        r.append(MatchReason(text=f"Moderate reliability ({rel.reliability_score}/100)", impact=N))
    if resp.response_rate is not None:
        rate = resp.response_rate
        r.append(MatchReason(
            text=f"{'Strong' if rate >= 70 else 'Moderate' if rate >= 40 else 'Weak'} response behaviour ({rate}%)",
            impact=P if rate >= 70 else N if rate >= 40 else X,
        ))

    if distance_km is None:
        r.append(MatchReason(text="Location unavailable", impact=N))
    else:
        r.append(MatchReason(
            text=f"{distance_km:.1f} km from the request location (synthetic coordinates)",
            impact=P if distance_km <= 10 else N if distance_km <= 30 else X,
        ))

    fatigue = state.fatigue
    if fatigue.fatigue_band is FatigueBand.LOW:
        r.append(MatchReason(text=f"Low coordination fatigue ({fatigue.fatigue_score}/100)", impact=P))
    elif fatigue.fatigue_band is FatigueBand.HIGH:
        r.append(MatchReason(text=f"High coordination fatigue ({fatigue.fatigue_score}/100)", impact=X))
    if state.freshness.contact_freshness_score >= 70:
        r.append(MatchReason(text="Not recently contacted", impact=P))

    if donated_for_patient:
        r.append(MatchReason(text="Donated for this patient before", impact=P))
    elif bridge_group_code:
        r.append(MatchReason(text=f"Member of the patient's bridge group ({bridge_group_code})", impact=P))

    r.extend(context.reasons)
    if adjustment > 0:
        r.append(MatchReason(text=f"Selected for controlled exploration (+{adjustment})", impact=P))
    elif adjustment < 0:
        r.append(MatchReason(
            text=f"Urgent request: unproven donor carries an uncertainty discount ({adjustment})", impact=X
        ))
    elif strategy is CandidateStrategy.EXPLORATION:
        r.append(MatchReason(text="Under-tested but promising (no exploration bonus at this urgency)", impact=N))
    if strategy is CandidateStrategy.RELIABLE:
        r.append(MatchReason(text="Proven donor (reliable strategy)", impact=P))
    return r


# ---- engine ------------------------------------------------------------------------------


class MatchingEngine:
    def __init__(
        self, repository: MatchingRepository, donor_states: DonorStateEngine, digital_twins: DigitalTwinService
    ) -> None:
        self._repo = repository
        self._donor_states = donor_states
        self._twins = digital_twins

    def match(
        self,
        request_code: str,
        limit: int = 10,
        include_excluded: bool = False,
        evaluate_at: str = "auto",
        *,
        exclude_donor_codes: frozenset[str] = frozenset(),
        radius_step: int = 0,
    ) -> MatchingResult:
        """`exclude_donor_codes` and `radius_step` let the Adaptive Cascade re-match between waves
        (donors it already contacted; a wider starting radius after an expanded-search recovery)."""
        request = self._repo.get_request(request_code)
        if request is None:
            raise UnknownCode("Request", request_code)
        as_of, point, note = self._donor_states.evaluation(request, evaluate_at)
        profile = _profile(request)
        compatible = list(COMPATIBLE_DONORS[request.blood_group])

        # 1–2. Candidate discovery and compatibility gate, in SQL.
        center = self._repo.city_centroid(request.city)
        donors, discovery = self._discover(compatible, center, radius_step)

        # 3–4. Eligibility gate and state assessment: one Donor State Engine batch.
        states = self._donor_states.assess_donors(donors, as_of, request, point)
        history = self._repo.request_history(
            request, [d.id for d in donors], as_of, as_of - timedelta(days=RECENT_WINDOW_DAYS)
        )

        # 5. Contextual ranking.
        weights = MATCH_WEIGHTS[profile]
        patient_group = request.patient.bridge_group
        ranked: list[MatchCandidate] = []
        excluded: list[MatchCandidate] = []
        for donor in donors:
            candidate = self._candidate(
                donor, states[donor.id], request, center, history, profile, patient_group, exclude_donor_codes
            )
            (ranked if candidate.eligible else excluded).append(candidate)

        ranked.sort(key=lambda c: (
            -c.match_score, -c.donor_priority_score,
            c.distance_km if c.distance_km is not None else float("inf"), c.donor_code,
        ))
        for position, candidate in enumerate(ranked, start=1):
            candidate.rank = position
        excluded.sort(key=lambda c: (c.distance_km if c.distance_km is not None else float("inf"), c.donor_code))

        twin = self._twins.build(request.patient.patient_code)
        assert twin is not None
        return MatchingResult(
            request=request_summary(request),
            evaluation=EvaluationInfo(evaluation_point=point, assessed_at=as_of, note=note),
            digital_twin_context=TwinContext(
                patient_code=twin.patient.patient_code,
                operational_state=twin.operational_state,
                active_request_code=twin.requirement_state.active_request_code,
                requirement_covered=twin.requirement_state.requirement_covered,
                network_strength_score=twin.network_state.network_strength_score,
                network_strength_band=twin.network_state.network_strength_band,
            ),
            discovery=discovery,
            candidate_pool_size=len(donors),
            eligible_candidate_count=len(ranked),
            excluded_candidate_count=len(excluded),
            weights=MatchingWeights(
                profile=profile, components=weights,
                exploration_bonus=EXPLORATION_BONUS[profile], uncertainty_discount=UNCERTAINTY_DISCOUNT[profile],
            ),
            ranking=ranked[:limit],
            excluded=excluded[:limit] if include_excluded else [],
            matching_summary=MatchingSummary(
                top_candidate=ranked[0].donor_code if ranked else None,
                average_match_score=round(sum(c.match_score for c in ranked) / len(ranked), 1) if ranked else None,
                candidates_by_strategy={
                    strategy: sum(c.candidate_strategy is strategy for c in ranked) for strategy in CandidateStrategy
                },
                top_exclusion_reasons=self._exclusion_reasons(excluded, discovery),
            ),
            data_notice=DATA_NOTICE,
        )

    # -- steps ---------------------------------------------------------------------------------

    def _discover(
        self, compatible: list, center: tuple[float, float] | None, radius_step: int = 0
    ) -> tuple[Sequence[Donor], DiscoveryInfo]:
        """Smallest radius step (from `radius_step` on) that yields at least MIN_POOL compatible active donors."""
        lon_scale = cos(radians(center[0])) if center else 1.0
        first = min(max(radius_step, 0), len(RADIUS_STEPS_KM) - 1)
        steps = RADIUS_STEPS_KM[first:] if center is not None else (None,)
        for index, radius in enumerate(steps):
            box = bounding_box(center[0], center[1], radius) if center is not None and radius is not None else None
            counts = self._repo.discovery_counts(compatible, box)
            if counts.compatible_in_area >= MIN_POOL or index == len(steps) - 1:
                donors = self._repo.discover(compatible, center, box, lon_scale, POOL_CAP)
                return donors, DiscoveryInfo(
                    total_donors=counts.total,
                    request_location_known=center is not None,
                    radius_km=radius,
                    radius_expanded=index > 0 or (center is not None and first > 0),
                    filtered_inactive=counts.inactive,
                    filtered_incompatible=counts.incompatible,
                    filtered_outside_radius=counts.compatible_total - counts.compatible_in_area,
                    pool_cap=POOL_CAP,
                    pool_capped=counts.compatible_in_area > POOL_CAP,
                    compatible_donor_groups=compatible,
                )
        raise AssertionError("unreachable")

    def _candidate(
        self,
        donor: Donor,
        state: DonorStateAssessment,
        request: BloodRequest,
        center: tuple[float, float] | None,
        history: RequestHistory,
        profile: WeightProfile,
        patient_group,  # type: ignore[no-untyped-def]
        exclude_donor_codes: frozenset[str] = frozenset(),
    ) -> MatchCandidate:
        weights = MATCH_WEIGHTS[profile]
        distance = round(haversine_km(center[0], center[1], donor.latitude, donor.longitude), 1) if center else None
        donated_before = donor.id in history.donated_for_patient
        group_member = patient_group is not None and donor.bridge_group_id == patient_group.id
        fit = request_fit(donor.blood_group is request.blood_group, donated_before, group_member)
        geo = geographic_fit(distance)
        context = coordination_context(donor.id, state, history)

        failed_gate = next((c for c in state.eligibility.checks if not c.passed), None)
        exclusion = GATE_LABELS.get(failed_gate.rule, failed_gate.detail) if failed_gate else context.exclusion
        if exclusion is None and donor.donor_code in exclude_donor_codes:
            exclusion = CONTACTED_IN_CASCADE
        eligible = exclusion is None

        components = {
            "donor_state": state.priority.priority_score,
            "request_fit": fit,
            "geographic_fit": geo,
            "context": context.score,
        }
        breakdown = [
            ScoreComponent(
                key=key, label=COMPONENT_LABELS[key], score=components[key], weight=weight,
                points=round(weight * components[key] / 100, 1) if eligible else 0.0,
            )
            for key, weight in weights.items()
        ]
        strategy, strategy_reason = candidate_strategy(state, fit) if eligible else (None, None)
        adjustment = 0
        if eligible and strategy is CandidateStrategy.EXPLORATION:
            adjustment += EXPLORATION_BONUS[profile]
        if eligible and not is_proven(state):
            adjustment -= UNCERTAINTY_DISCOUNT[profile]
        weighted = round(sum(weight * components[key] / 100 for key, weight in weights.items()))
        match = max(0, min(100, weighted + adjustment)) if eligible else 0
        reasons = (
            candidate_reasons(
                state, request, distance, donated_before,
                patient_group.group_code if group_member else None, context, strategy,  # type: ignore[arg-type]
                adjustment,
            )
            if eligible else [MatchReason(text=f"Excluded: {exclusion}", impact=Impact.NEGATIVE)]
        )
        return MatchCandidate(
            rank=None,
            donor_code=donor.donor_code,
            display_name=donor.display_name,
            blood_group=donor.blood_group,
            city=donor.city,
            distance_km=distance,
            eligible=eligible,
            availability_status=state.availability.availability_status,
            reliability_score=state.reliability.reliability_score,
            response_rate=state.response.response_rate,
            response_score=state.response.response_score,
            response_data_sufficiency=state.response.data_sufficiency,
            fatigue_score=state.fatigue.fatigue_score,
            freshness_score=state.freshness.contact_freshness_score,
            donor_priority_score=state.priority.priority_score,
            request_fit_score=fit,
            geographic_fit_score=geo,
            context_score=context.score,
            strategy_adjustment=adjustment,
            match_score=match,
            candidate_strategy=strategy,
            strategy_reason=strategy_reason,
            score_breakdown=breakdown,
            reasons=reasons,
            exclusion_reason=exclusion,
            bridge_group_member=group_member,
        )

    @staticmethod
    def _exclusion_reasons(excluded: Sequence[MatchCandidate], discovery: DiscoveryInfo) -> list[ExclusionCount]:
        gate = Counter(c.exclusion_reason for c in excluded if c.exclusion_reason)
        reasons = [
            ExclusionCount(reason=reason, count=count, stage="gate")
            for reason, count in sorted(gate.items(), key=lambda item: (-item[1], item[0]))
        ]
        discovered = [
            ("Incompatible blood group", discovery.filtered_incompatible),
            ("Inactive donor record", discovery.filtered_inactive),
            ("Outside search radius", discovery.filtered_outside_radius),
        ]
        reasons += [
            ExclusionCount(reason=reason, count=count, stage="discovery")
            for reason, count in sorted(discovered, key=lambda item: (-item[1], item[0]))
            if count
        ]
        return reasons
