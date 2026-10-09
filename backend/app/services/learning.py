"""Learning Engine: "what should be remembered?"

    Failure Autopsy   "What happened?"
    Self-Healing      "What should change?"
    Learning          "What should be remembered?"   (this file)

Deterministic, descriptive analysis of coordination outcomes. It produces insights with their numerator,
denominator, time window, evidence strength, reasoning and limitations, plus advisory recommendations. It
never changes matching, donor state, recovery or any safety limit, never trains a model, and never
claims causation: where one event merely followed another it reports an observed association.

Populations are never mixed. RECORDED insights come only from stored records; SIMULATED insights come only
from the cascade runs handed in. Everything is synthetic demonstration data and says so.

EVIDENCE STRENGTH (transparent, sample-based; never a claim of real-world effectiveness)
    smallest compared group:   < MIN_SAMPLE (10)  → INSUFFICIENT_DATA
                               10–29              → LOW
                               30–99              → MODERATE
                               ≥ 100              → HIGH
    capped at MODERATE for associations that are observational by nature (recovery effectiveness, donor
    fatigue, failure patterns), whatever the sample size. A group below MIN_SAMPLE is shown but excluded
    from comparisons. Proportions carry a 95 % Wilson interval; two groups "clearly differ" only when
    their intervals do not overlap.
"""

import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta

from app.models.enums import (
    CoordinationOutcome,
    CoordinationStatus,
    FailureCategory,
    InteractionChannel,
    InteractionResponseStatus,
    InteractionType,
    LearningEventType,
    RecoveryActionType,
    UrgencyLevel,
)
from app.repositories.learning_repository import FailureRow, InteractionRow, LearningRepository
from app.schemas.cascade import CascadeResult, SimulatedResponse
from app.schemas.failure_autopsy import FailurePatternType, FailureSource
from app.schemas.learning import (
    BoundedAdjustment,
    EvidenceStrength,
    Insight,
    InsightCategory,
    InsightGroup,
    LearningReport,
    Recommendation,
    SufficiencyEntry,
    TimeWindow,
)
from app.services.donor_state import ACTIVITY_WINDOW_DAYS
from app.services.failure_autopsy import FailureObservation, PatternContext, detect_patterns

# ---- documented thresholds ---------------------------------------------------------------------------

MIN_SAMPLE = 10
LOW_MAX = 30                 # below this (and ≥ MIN_SAMPLE): LOW
MODERATE_MAX = 100           # below this: MODERATE; at or above: HIGH
OBSERVATIONAL_CAP = EvidenceStrength.MODERATE
MIN_PATTERN_FAILURES = 2     # failures a request needs before patterns are looked for
LATE_SHARE_ATTENTION = 0.25  # share of secured requests secured after required_by that merits attention
LEARNING_MAX_ADJUSTMENT_POINTS = 5.0   # hard bound for any advisory adjustment (match-score points)
LOAD_BANDS = ((0, 0, "0 prior contacts"), (1, 1, "1 prior contact"), (2, 3, "2–3 prior contacts"), (4, 10**9, "4+ prior contacts"))
THRESHOLDS: dict[str, int | float | str] = {
    "min_sample": MIN_SAMPLE, "low_below": LOW_MAX, "moderate_below": MODERATE_MAX,
    "observational_cap": OBSERVATIONAL_CAP.value, "pattern_min_failures": MIN_PATTERN_FAILURES,
    "confidence_interval": "95% Wilson", "contact_load_window_days": ACTIVITY_WINDOW_DAYS,
    "late_share_attention": LATE_SHARE_ATTENTION, "max_adjustment_points": LEARNING_MAX_ADJUSTMENT_POINTS,
}

RECORDED_PROVENANCE = "RECORDED: stored records in the synthetic demonstration dataset (generated, not real-world data)."
SIMULATED_PROVENANCE = "SIMULATED: in-memory Adaptive Cascade runs on the synthetic dataset (nothing persisted)."
SYNTHETIC_LIMITATION = "The data is synthetic; results describe the dataset, not real-world donors or outcomes."

ORDER = (EvidenceStrength.INSUFFICIENT_DATA, EvidenceStrength.LOW, EvidenceStrength.MODERATE, EvidenceStrength.HIGH)
CHANNEL_NAME = {
    InteractionChannel.SIMULATED_SMS: "SMS", InteractionChannel.SIMULATED_CALL: "Call",
    InteractionChannel.SIMULATED_APP: "App",
}
ESCALATION_ACTIONS = (RecoveryActionType.HUMAN_COORDINATOR_REVIEW, RecoveryActionType.BLOOD_BANK_REFERRAL)


# ---- pure statistics -----------------------------------------------------------------------------------


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    if total <= 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)


def strength_for(sample: int, cap: EvidenceStrength = EvidenceStrength.HIGH) -> tuple[EvidenceStrength, str]:
    """Label and explanation for the smallest compared group's sample size."""
    if sample < MIN_SAMPLE:
        return EvidenceStrength.INSUFFICIENT_DATA, f"{sample} observation(s) in the smallest group; at least {MIN_SAMPLE} are needed for any conclusion."
    raw = (EvidenceStrength.LOW if sample < LOW_MAX else EvidenceStrength.MODERATE if sample < MODERATE_MAX
           else EvidenceStrength.HIGH)
    label = min(raw, cap, key=ORDER.index)
    reason = f"{sample} observations in the smallest group: {raw.value} on sample size alone ({MIN_SAMPLE}–{LOW_MAX - 1} LOW, {LOW_MAX}–{MODERATE_MAX - 1} MODERATE, {MODERATE_MAX}+ HIGH)."
    if label is not raw:
        reason += f" Capped at {label.value}: observational evidence from synthetic data."
    return label, reason


def group(label: str, numerator: int, denominator: int) -> InsightGroup:
    interval = wilson(numerator, denominator)
    return InsightGroup(
        label=label, numerator=numerator, denominator=denominator,
        rate=round(numerator / denominator, 4) if denominator else None,
        ci_low=interval[0] if interval else None, ci_high=interval[1] if interval else None,
    )


def eligible(groups: Sequence[InsightGroup]) -> list[InsightGroup]:
    return [g for g in groups if (g.denominator or 0) >= MIN_SAMPLE and g.rate is not None]


def clear_difference(groups: Sequence[InsightGroup]) -> tuple[InsightGroup, InsightGroup] | None:
    """(highest, lowest) eligible groups when their 95 % intervals do not overlap, else None."""
    usable = eligible(groups)
    if len(usable) < 2:
        return None
    best, worst = max(usable, key=lambda g: g.rate or 0), min(usable, key=lambda g: g.rate or 0)
    if best.ci_low is not None and worst.ci_high is not None and best.ci_low > worst.ci_high:
        return best, worst
    return None


def smallest_sample(groups: Sequence[InsightGroup]) -> int:
    usable = eligible(groups)
    return min(g.denominator or 0 for g in usable) if usable else max((g.denominator or 0 for g in groups), default=0)


def pct(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate * 100:.0f}%"


def describe(groups: Sequence[InsightGroup]) -> str:
    return "; ".join(f"{g.label} {pct(g.rate)} ({g.numerator}/{g.denominator})" for g in groups)


def window(start: datetime | None, end: datetime | None) -> TimeWindow:
    return TimeWindow(start=start, end=end)


def median(values: Sequence[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def contact_load_bands(rows: Sequence[InteractionRow]) -> dict[str, list[int]]:
    """Response counts per prior-contact-load band: [responded, resolved]. The load of an interaction is
    how many earlier interactions the same donor had in the preceding ACTIVITY_WINDOW_DAYS (rows must be
    ordered by donor, then time). PENDING interactions have no outcome yet and are excluded."""
    counts: dict[str, list[int]] = {label: [0, 0] for _, _, label in LOAD_BANDS}
    span = timedelta(days=ACTIVITY_WINDOW_DAYS)
    index, donor = 0, None
    history: list[datetime] = []
    for row in rows:
        if row.donor_id != donor:
            donor, history, index = row.donor_id, [], 0
        while index < len(history) and row.initiated_at - history[index] > span:
            index += 1
        load = len(history) - index
        history.append(row.initiated_at)
        if row.response_status is InteractionResponseStatus.PENDING:
            continue
        label = next(name for low, high, name in LOAD_BANDS if low <= load <= high)
        counts[label][1] += 1
        counts[label][0] += row.response_status is not InteractionResponseStatus.NO_RESPONSE
    return counts


# ---- insight builders shared by both populations --------------------------------------------------------


def _insight(
    insight_id: str, category: InsightCategory, source: FailureSource, title: str, finding: str, *,
    groups: Sequence[InsightGroup], span: TimeWindow, reason: str, limitations: Sequence[str], consideration: str,
    cap: EvidenceStrength = EvidenceStrength.HIGH, numerator: int | None = None, denominator: int | None = None,
    sample: int | None = None,
) -> Insight:
    size = sample if sample is not None else smallest_sample(groups)
    strength, strength_reason = strength_for(size, cap)
    if strength is EvidenceStrength.INSUFFICIENT_DATA:
        finding += " The sample is too small to support a conclusion."
        consideration = "Collect more data before relying on this."
    total_n = sum(g.denominator or 0 for g in groups)
    return Insight(
        insight_id=insight_id, category=category, source=source,
        provenance=RECORDED_PROVENANCE if source is FailureSource.RECORDED else SIMULATED_PROVENANCE,
        title=title, finding=finding,
        numerator=numerator if numerator is not None else (sum(g.numerator or 0 for g in groups) if groups else None),
        denominator=denominator if denominator is not None else total_n if groups else None,
        sample_size=sample if sample is not None else total_n, time_window=span, strength=strength,
        strength_reason=strength_reason, reason=reason, limitations=[*limitations, SYNTHETIC_LIMITATION],
        consideration=consideration, groups=list(groups),
    )


def channel_insights(
    source: FailureSource, counts: dict[InteractionChannel, tuple[int, int, int]], span: TimeWindow,
) -> list[Insight]:
    """`counts[channel] = (responded, accepted, resolved)`."""
    caveat = ("Only donation requests are compared (availability checks and follow-ups differ in purpose). Channels "
              "were not assigned at random: urgency and donor mix differ between them, so a difference is an "
              "association, not proof that the channel caused it.")
    out = []
    for key, title, index, noun in (("CH-RESPONSE", "Response rate by channel (donation requests)", 0, "replied"),
                                    ("CH-ACCEPT", "Acceptance rate by channel (donation requests)", 1, "accepted")):
        groups = [group(CHANNEL_NAME[c], counts[c][index], counts[c][2]) for c in InteractionChannel if c in counts and counts[c][2]]
        diff = clear_difference(groups)
        if not groups:
            out.append(_insight(f"{key}-{source.value}", InsightCategory.CHANNEL_EFFECTIVENESS, source, title,
                                "No resolved outreach was available to compare channels.", groups=[], span=span,
                                reason="There are no resolved interactions.", limitations=[caveat],
                                consideration="Collect more data before relying on this.", sample=0))
            continue
        comparison = (f"{diff[0].label} was higher than {diff[1].label} and the intervals do not overlap."
                      if diff else "No channel clearly differs from the others (confidence intervals overlap or a group is too small).")
        out.append(_insight(
            f"{key}-{source.value}", InsightCategory.CHANNEL_EFFECTIVENESS, source, title,
            f"Share of resolved contacts that {noun}: {describe(groups)}. {comparison}", groups=groups, span=span,
            reason="Computed as events divided by resolved contacts per channel (pending contacts excluded), with 95% Wilson intervals.",
            limitations=[caveat],
            consideration=(f"Consider {diff[0].label} for first outreach where the existing rules allow; this is a recommendation only."
                           if diff and key == "CH-RESPONSE" else "No channel preference is supported by this evidence."),
        ))
    return out


def latency_insight(source: FailureSource, minutes: dict[InteractionChannel, list[float]], span: TimeWindow) -> Insight:
    groups = [
        InsightGroup(label=CHANNEL_NAME[c], denominator=len(v), value=median(v), unit="minutes")
        for c, v in sorted(minutes.items(), key=lambda kv: kv[0].value) if v
    ]
    slow = max(groups, key=lambda g: g.value or 0) if groups else None
    fast = min(groups, key=lambda g: g.value or 0) if groups else None
    finding = ("Median time from outreach to reply: " + "; ".join(f"{g.label} {g.value:g} min (n={g.denominator})" for g in groups)
               + ".") if groups else "No replies with a response time were available."
    return _insight(
        f"CB-LATENCY-{source.value}", InsightCategory.COORDINATION_BOTTLENECK, source, "Reply time by channel", finding,
        groups=groups, span=span, reason="Median of (response time − outreach time) over replied donation requests only; non-responses have no time.",
        limitations=["Only donors who replied contribute, so slow non-responders are not reflected.",
                     "Reply times are synthetic."],
        consideration=(f"Allow longer response windows for {slow.label} than for {fast.label}."
                       if slow and fast and slow is not fast and (slow.value or 0) > 1.25 * (fast.value or 1) else
                       "No channel needs a different response window on this evidence."),
        sample=sum(g.denominator or 0 for g in groups) and min(g.denominator or 0 for g in groups),
    ).model_copy(update={"numerator": None, "denominator": None,
                         "sample_size": sum(g.denominator or 0 for g in groups)})


def pattern_insights(
    source: FailureSource, counts: Counter[FailurePatternType], analysed: int, span: TimeWindow, unit: str,
) -> list[Insight]:
    """`counts[pattern]` = number of analysed batches (`unit`: requests or failed waves) showing the pattern."""
    note = (f"Patterns come from the Failure Autopsy rules applied to each {unit}; a pattern is an operational "
            "interpretation of recorded failures, not a diagnosed cause.")
    if analysed == 0:
        return [_insight(f"FP-NONE-{source.value}", InsightCategory.FAILURE_PATTERN, source, "Recurring failure patterns",
                         f"No {unit} with at least {MIN_PATTERN_FAILURES} failures was available to analyse.", groups=[],
                         span=span, reason="Patterns need several failures in one batch.", limitations=[note],
                         consideration="Collect more data before relying on this.", sample=0)]
    if not counts:
        return [_insight(f"FP-NONE-{source.value}", InsightCategory.FAILURE_PATTERN, source, "Recurring failure patterns",
                         f"None of {analysed} analysed {unit}s showed a multi-failure pattern.", groups=[group("No pattern", analysed, analysed)],
                         span=span, reason="The Failure Autopsy rules found no pattern in any analysed batch.", limitations=[note],
                         consideration="No pattern-driven change is suggested.", cap=OBSERVATIONAL_CAP,
                         numerator=0, denominator=analysed, sample=analysed)]
    out = []
    for pattern, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].value)):
        g = group(pattern.value, count, analysed)
        out.append(_insight(
            f"FP-{pattern.value}-{source.value}", InsightCategory.FAILURE_PATTERN, source,
            f"Pattern: {pattern.value.replace('_', ' ').lower()}",
            f"{pattern.value} appeared in {count} of {analysed} analysed {unit}s ({pct(g.rate)}).", groups=[g], span=span,
            reason=f"Counted {unit}s with at least {MIN_PATTERN_FAILURES} failures in which the Failure Autopsy rules detected this pattern.",
            limitations=[note], consideration=PATTERN_CONSIDERATION.get(pattern, "Review the affected outreach before changing rules."),
            cap=OBSERVATIONAL_CAP, numerator=count, denominator=analysed, sample=analysed,
        ))
    return out


PATTERN_CONSIDERATION = {
    FailurePatternType.CHANNEL_RESPONSE_FAILURE: "Consider an earlier switch to a different channel when several contacts on one channel go unanswered.",
    FailurePatternType.RESPONSE_WINDOW_FAILURE: "Consider longer response windows or wider waves when replies are slow across channels.",
    FailurePatternType.BRIDGE_GROUP_FAILURE: "Consider reaching beyond the bridge group sooner when its members repeatedly fail.",
    FailurePatternType.RECENT_DONATION_POOL: "Consider re-running matching sooner when many candidates are excluded by the donation-interval rule.",
    FailurePatternType.UNKNOWN_PATTERN: "Review mixed failures manually; no rule explains them.",
    FailurePatternType.INDIVIDUAL_DONOR_FAILURE: "Isolated donor failures need no systemic change.",
}


def recovery_insights(
    source: FailureSource, outcomes: dict[str, tuple[int, int]], total_actions: int, span: TimeWindow, linked_by: str,
) -> list[Insight]:
    """`outcomes[action] = (followed_by_success, with_recorded_outcome)`."""
    caveat = (f"{linked_by} This shows what happened after a recovery action, not that the action caused it: "
              "other changes (new donors, timing, luck) were not controlled.")
    if total_actions == 0:
        return [_insight(f"RE-EFFECT-{source.value}", InsightCategory.RECOVERY_EFFECTIVENESS, source,
                         "Recovery effectiveness", "No recovery actions were available.", groups=[], span=span,
                         reason="Without recovery actions there is nothing to assess.", limitations=[caveat],
                         consideration="Collect more data before relying on this.", sample=0)]
    groups = [group(name.replace("_", " ").title(), s, n) for name, (s, n) in sorted(outcomes.items()) if n]
    with_outcome = sum(n for _, n in outcomes.values())
    diff = clear_difference(groups)
    thin = [g.label for g in groups if (g.denominator or 0) < MIN_SAMPLE]
    finding = (f"Share of recoveries followed by a successful next attempt: {describe(groups)}." if groups
               else "No recovery action has a recorded outcome.")
    finding += (f" {diff[0].label} was followed by success more often than {diff[1].label} (intervals do not overlap); this is an observed association, not a causal effect."
                if diff else " No recovery action clearly differs from the others.")
    if thin:
        finding += f" Too few cases to compare: {', '.join(thin)}."
    effect = _insight(
        f"RE-EFFECT-{source.value}", InsightCategory.RECOVERY_EFFECTIVENESS, source, "Outcome after each recovery action",
        finding, groups=groups, span=span,
        reason="For each recovery action with a recorded outcome, the share whose following attempt succeeded; groups under the minimum sample are shown but not compared.",
        limitations=[caveat, "Recoveries differ in the failures they responded to, so groups are not like-for-like."],
        consideration=(f"Consider giving {diff[0].label} more weight among recovery options; an association only, and the existing policy remains the fallback."
                       if diff else "No recovery route is supported as better than another."),
        cap=OBSERVATIONAL_CAP, sample=smallest_sample(groups) if groups else 0,
    )
    coverage = _insight(
        f"RE-COVERAGE-{source.value}", InsightCategory.RECOVERY_EFFECTIVENESS, source, "Recovery outcome evidence coverage",
        f"{with_outcome} of {total_actions} recovery actions have a recorded outcome ({pct(with_outcome / total_actions)}); "
        f"{total_actions - with_outcome} have none.", groups=[group("With recorded outcome", with_outcome, total_actions)],
        span=span, reason="Only recoveries with a recorded outcome can inform effectiveness; the rest are excluded, not guessed.",
        limitations=[caveat], consideration=("Record the outcome of every recovery so effectiveness can be assessed."
                                            if with_outcome < total_actions else "Outcome coverage is complete."),
        cap=OBSERVATIONAL_CAP, numerator=with_outcome, denominator=total_actions, sample=total_actions,
    )
    return [effect, coverage]


# ---- recommendations and sufficiency ---------------------------------------------------------------------


def build_recommendations(insights: Sequence[Insight], adjustments_enabled: bool) -> list[Recommendation]:
    recommendations: list[Recommendation] = []

    def adjustment(target: str, strength: EvidenceStrength) -> BoundedAdjustment | None:
        if not adjustments_enabled or strength not in (EvidenceStrength.MODERATE, EvidenceStrength.HIGH):
            return None
        value = LEARNING_MAX_ADJUSTMENT_POINTS * (1.0 if strength is EvidenceStrength.HIGH else 0.5)
        return BoundedAdjustment(target=target, value=value, bound=LEARNING_MAX_ADJUSTMENT_POINTS)

    for insight in insights:
        base = insight.insight_id
        if insight.strength is EvidenceStrength.INSUFFICIENT_DATA:
            recommendations.append(Recommendation(
                recommendation_id=f"REC-{base}", insight_ids=[base], strength=insight.strength,
                text=f"{insight.title}: collect more data before drawing any conclusion."))
            continue
        diff = clear_difference(insight.groups)
        if insight.category is InsightCategory.CHANNEL_EFFECTIVENESS and base.startswith("CH-RESPONSE") and diff:
            recommendations.append(Recommendation(
                recommendation_id=f"REC-{base}", insight_ids=[base], strength=insight.strength,
                text=f"Consider {diff[0].label} as the preferred first channel where existing rules allow ({diff[0].label} {pct(diff[0].rate)} vs {diff[1].label} {pct(diff[1].rate)} replied). Recommendation only.",
                adjustment=adjustment(f"channel_preference:{diff[0].label.lower()}", insight.strength)))
        elif insight.category is InsightCategory.RECOVERY_EFFECTIVENESS and base.startswith("RE-EFFECT") and diff:
            recommendations.append(Recommendation(
                recommendation_id=f"REC-{base}", insight_ids=[base], strength=insight.strength,
                text=f"Consider {diff[0].label} earlier among recovery options: it was followed by success more often ({pct(diff[0].rate)} vs {pct(diff[1].rate)}), an association rather than proof of effect. The existing policy remains the fallback.",
                adjustment=adjustment(f"recovery_priority:{diff[0].label.lower().replace(' ', '_')}", insight.strength)))
        elif insight.category is InsightCategory.DONOR_FATIGUE:
            recommendations.append(Recommendation(
                recommendation_id=f"REC-{base}", insight_ids=[base], strength=insight.strength,
                text="Keep the existing contact-frequency and fatigue protections unchanged. Learning never relaxes them."))
        elif base.startswith("CB-LATE") and insight.numerator is not None and insight.denominator:
            if insight.numerator / insight.denominator > LATE_SHARE_ATTENTION:
                recommendations.append(Recommendation(
                    recommendation_id=f"REC-{base}", insight_ids=[base], strength=insight.strength,
                    text=f"{pct(insight.numerator / insight.denominator)} of secured requests were secured after the required-by time; review where time is lost before changing rules."))
    return recommendations


def build_sufficiency(insights: Sequence[Insight], extra: Sequence[SufficiencyEntry]) -> list[SufficiencyEntry]:
    labels = {
        InsightCategory.CHANNEL_EFFECTIVENESS: "Channel effectiveness",
        InsightCategory.FAILURE_PATTERN: "Failure patterns",
        InsightCategory.RECOVERY_EFFECTIVENESS: "Recovery effectiveness",
        InsightCategory.DONOR_FATIGUE: "Donor fatigue",
        InsightCategory.COORDINATION_BOTTLENECK: "Coordination bottlenecks",
    }
    entries = []
    for category, label in labels.items():
        subset = [i for i in insights if i.category is category]
        if not subset:
            entries.append(SufficiencyEntry(capability=label, status=EvidenceStrength.INSUFFICIENT_DATA,
                                            reason="No suitable evidence is available for this capability."))
            continue
        best = max(subset, key=lambda i: ORDER.index(i.strength))
        weak = sum(i.strength is EvidenceStrength.INSUFFICIENT_DATA for i in subset)
        entries.append(SufficiencyEntry(
            capability=label, status=best.strength,
            reason=f"{len(subset)} insight(s); strongest is {best.strength.value}; {weak} with insufficient data."))
    return [*entries, *extra]


def _assemble(
    source: FailureSource, population: str, span: TimeWindow, insights: list[Insight],
    extra: Sequence[SufficiencyEntry], adjustments_enabled: bool, data_notice: str,
) -> LearningReport:
    return LearningReport(
        source=source, provenance=RECORDED_PROVENANCE if source is FailureSource.RECORDED else SIMULATED_PROVENANCE,
        population=population, time_window=span, insights=insights,
        recommendations=build_recommendations(insights, adjustments_enabled),
        sufficiency=build_sufficiency(insights, extra), thresholds=dict(THRESHOLDS),
        adjustments_enabled=adjustments_enabled, data_notice=data_notice,
    )


# ---- engine ----------------------------------------------------------------------------------------------


class LearningEngine:
    def __init__(self, repository: LearningRepository | None, data_notice: str, adjustments_enabled: bool = False) -> None:
        self._repo = repository
        self._data_notice = data_notice
        self._adjustments = adjustments_enabled

    # RECORDED -----------------------------------------------------------------------------------------

    def recorded_report(self) -> LearningReport:
        assert self._repo is not None, "the recorded report needs a repository"
        repo = self._repo
        source = FailureSource.RECORDED
        interactions = repo.interactions()
        start, end = repo.interaction_window()
        contact_span = window(start, end)

        counts: dict[InteractionChannel, list[int]] = defaultdict(lambda: [0, 0, 0])
        for channel, status, count in repo.channel_counts():
            if status is InteractionResponseStatus.PENDING:
                continue
            counts[channel][2] += count
            counts[channel][0] += count if status is not InteractionResponseStatus.NO_RESPONSE else 0
            counts[channel][1] += count if status is InteractionResponseStatus.ACCEPTED else 0
        insights = channel_insights(source, {c: (v[0], v[1], v[2]) for c, v in counts.items()}, contact_span)

        category_counts = repo.failure_category_counts()
        failure_start, failure_end = repo.failure_window()
        failure_span = window(failure_start, failure_end)
        insights.append(self._category_insight(category_counts, failure_span))
        pattern_counts, analysed = self._recorded_patterns(repo.failures())
        insights += pattern_insights(source, pattern_counts, analysed, failure_span, "request")

        recovery_start, recovery_end = repo.recovery_window()
        insights += self._recorded_recovery(recovery_start, recovery_end)
        insights.append(self._fatigue_insight(contact_load_bands(interactions), contact_span))
        insights += self._recorded_bottlenecks(interactions, category_counts, contact_span, failure_span,
                                               window(recovery_start, recovery_end))

        extra = [SufficiencyEntry(
            capability="Candidate-pool exhaustion and local-pool patterns (historical)",
            status=EvidenceStrength.INSUFFICIENT_DATA,
            reason="The dataset stores no snapshot of the candidate pool at the time of each failure, so these patterns cannot be assessed historically; they are only visible in simulated cascades.")]
        population = (f"{len(interactions)} interactions, {sum(c for _, c in category_counts)} failures, "
                      f"{sum(c for _, _, c in repo.recovery_status_counts())} recovery actions, {len(repo.requests())} requests")
        return _assemble(source, population, contact_span, insights, extra, self._adjustments, self._data_notice)

    @staticmethod
    def _category_insight(category_counts: list[tuple[FailureCategory, int]], span: TimeWindow) -> Insight:
        total = sum(c for _, c in category_counts)
        groups = [group(cat.value, c, total) for cat, c in sorted(category_counts, key=lambda kv: (-kv[1], kv[0].value))]
        top = groups[0] if groups else None
        return _insight(
            "FP-CATEGORIES-RECORDED", InsightCategory.FAILURE_PATTERN, FailureSource.RECORDED, "Recorded failure categories",
            (f"Most frequent recorded failure: {top.label} ({top.numerator} of {total}, {pct(top.rate)}). All: {describe(groups)}."
             if top else "No failures were recorded."), groups=groups, span=span,
            reason="Counts of the failure category stored with each failed coordination attempt.",
            limitations=["Categories are assigned when a failure is recorded; they describe what failed, not why."],
            consideration=("Focus coordination improvements on the most frequent category first." if top else "Collect more data before relying on this."),
            numerator=top.numerator if top else None, denominator=total if top else None, sample=total,
        )

    @staticmethod
    def _recorded_patterns(rows: list[FailureRow]) -> tuple[Counter[FailurePatternType], int]:
        by_request: dict[int, list[FailureRow]] = defaultdict(list)
        for row in rows:
            by_request[row.request_id].append(row)
        counts: Counter[FailurePatternType] = Counter()
        analysed = 0
        for batch in by_request.values():
            if len(batch) < MIN_PATTERN_FAILURES:
                continue
            analysed += 1
            observations = [
                FailureObservation(
                    donor_code=r.donor_code, display_name=r.display_name, blood_group=r.blood_group,
                    failure_type=r.category, channel=r.channel, detected_at=r.detected_at,
                    bridge_group_member=r.request_bridge_group_id is not None and r.donor_bridge_group_id == r.request_bridge_group_id,
                    window_expired=r.category is FailureCategory.NO_RESPONSE,
                ) for r in batch
            ]
            # No candidate-pool snapshot is recorded, so pool-based patterns are not assessed here.
            context = PatternContext(remaining_in_radius=10**6, filtered_outside_radius=0, radius_known=False, urgency=batch[0].urgency)
            for pattern in {p.pattern_type for p in detect_patterns(observations, context)}:
                counts[pattern] += 1
        return counts, analysed

    def _recorded_recovery(self, start: datetime | None, end: datetime | None) -> list[Insight]:
        assert self._repo is not None
        wins: dict[str, int] = defaultdict(int)
        totals: dict[str, int] = defaultdict(int)
        all_actions = 0
        for action, event, count in self._repo.recovery_outcomes():
            all_actions += count
            if event is LearningEventType.RECOVERY_SUCCESS:
                wins[action.value] += count
                totals[action.value] += count
            elif event is LearningEventType.RECOVERY_FAILURE:
                totals[action.value] += count
        outcomes = {a: (wins[a], totals[a]) for a in totals}
        return recovery_insights(
            FailureSource.RECORDED, outcomes, all_actions, window(start, end),
            "Each recovery action is linked to the recorded learning event that references it (RECOVERY_SUCCESS or RECOVERY_FAILURE).")

    @staticmethod
    def _fatigue_insight(bands: dict[str, list[int]], span: TimeWindow) -> Insight:
        groups = [group(label, bands[label][0], bands[label][1]) for _, _, label in LOAD_BANDS]
        usable = eligible(groups)
        low, high = (usable[0], usable[-1]) if len(usable) >= 2 else (None, None)
        if low and high and high.ci_high is not None and low.ci_low is not None and high.ci_high < low.ci_low:
            direction, consideration = (
                "Donors with more recent contacts replied less often (an association).",
                "Consider whether more conservative contact spacing is warranted for heavily contacted donors; existing protections stay in force.")
        elif low and high and high.ci_low is not None and low.ci_high is not None and high.ci_low > low.ci_high:
            direction, consideration = (
                "Donors with more recent contacts replied more often, which more likely reflects who gets contacted than a benefit of contact.",
                "Do not use this to increase contact frequency; existing contact-frequency and fatigue protections stay unchanged.")
        else:
            direction, consideration = (
                "Reply rates do not clearly differ by recent contact load.",
                "No change to contact-frequency protections is suggested; they remain unchanged.")
        return _insight(
            "DF-CONTACT-LOAD-RECORDED", InsightCategory.DONOR_FATIGUE, FailureSource.RECORDED,
            f"Reply rate by contacts in the previous {ACTIVITY_WINDOW_DAYS} days",
            f"Reply rate by prior contact load: {describe(groups)}. {direction}", groups=groups, span=span,
            reason=f"For every resolved interaction, the donor's earlier interactions within {ACTIVITY_WINDOW_DAYS} days were counted; replies are interactions that were not NO_RESPONSE. Only aggregates are reported, never individual donors.",
            limitations=["More heavily contacted donors are not a random sample, so differences are confounded by selection.",
                         "This analysis only describes outcomes; it does not change fatigue scoring, contact limits or eligibility."],
            consideration=consideration, cap=OBSERVATIONAL_CAP,
        )

    def _recorded_bottlenecks(
        self, interactions: Sequence[InteractionRow], category_counts: list[tuple[FailureCategory, int]],
        contact_span: TimeWindow, failure_span: TimeWindow, recovery_span: TimeWindow,
    ) -> list[Insight]:
        assert self._repo is not None
        source = FailureSource.RECORDED
        minutes: dict[InteractionChannel, list[float]] = defaultdict(list)
        for row in interactions:
            if row.response_at is not None and row.interaction_type is InteractionType.DONATION_REQUEST:
                minutes[row.channel].append((row.response_at - row.initiated_at).total_seconds() / 60)
        out = [latency_insight(source, minutes, contact_span)]

        attempts = self._repo.attempts()
        by_request: dict[int, list] = defaultdict(list)
        for attempt in attempts:
            by_request[attempt.request_id].append(attempt)
        attempt_span = window(min((a.started_at for a in attempts), default=None),
                              max((a.completed_at for a in attempts if a.completed_at), default=None))
        with_failures = streaks = 0
        for batch in by_request.values():
            failed = [a for a in batch if a.status is CoordinationStatus.FAILED]
            if len(failed) < 2:
                continue
            with_failures += 1
            streaks += any(x.outcome is CoordinationOutcome.NO_RESPONSE and y.outcome is CoordinationOutcome.NO_RESPONSE
                           and y.sequence_number == x.sequence_number + 1 for x, y in zip(batch, batch[1:]))
        out.append(_insight(
            "CB-NO-RESPONSE-RUNS-RECORDED", InsightCategory.COORDINATION_BOTTLENECK, source,
            "Consecutive no-responses",
            f"{streaks} of {with_failures} requests with at least two failed attempts had two no-responses in a row ({pct(streaks / with_failures) if with_failures else 'n/a'}).",
            groups=[group("Requests with back-to-back no-responses", streaks, with_failures)], span=attempt_span,
            reason="Counted requests whose consecutive attempts both ended without a reply, among requests with two or more failed attempts.",
            limitations=["Only requests with at least two failed attempts are considered."],
            consideration=("Consider switching channel or widening the wave after the first unanswered attempt."
                           if with_failures and streaks / with_failures > 0.25 else "Back-to-back no-responses are not frequent enough to suggest a change."),
            cap=OBSERVATIONAL_CAP, numerator=streaks, denominator=with_failures, sample=with_failures))

        requests = {r.request_id: r for r in self._repo.requests()}
        hours: list[float] = []
        late = 0
        for request_id, batch in by_request.items():
            done = [a.completed_at for a in batch if a.status is CoordinationStatus.SUCCESS and a.completed_at]
            if done and request_id in requests:
                request = requests[request_id]
                first = min(done)
                hours.append((first - request.requested_at).total_seconds() / 3600)
                late += first > request.required_by
        secured_span = window(min((requests[r].requested_at for r in by_request if r in requests), default=None), attempt_span.end)
        typical = median(hours)
        out.append(_insight(
            "CB-TIME-TO-SECURE-RECORDED", InsightCategory.COORDINATION_BOTTLENECK, source, "Time to secure a donor",
            (f"Median time from request to the first accepted donor: {typical:g} hours across {len(hours)} secured requests."
             if hours else "No secured requests were available."),
            groups=[InsightGroup(label="Requests secured", denominator=len(hours), value=typical, unit="hours")], span=secured_span,
            reason="Median of (first successful attempt completion minus request time) over requests that were secured.",
            limitations=["Requests that were never secured are not included, which understates delays."],
            consideration="Compare against the required-by times before changing the process.", sample=len(hours),
        ).model_copy(update={"numerator": None, "denominator": None}))
        out.append(_insight(
            "CB-LATE-SECURE-RECORDED", InsightCategory.COORDINATION_BOTTLENECK, source, "Secured after the required-by time",
            f"{late} of {len(hours)} secured requests were secured after the required-by time ({pct(late / len(hours)) if hours else 'n/a'}).",
            groups=[group("Secured late", late, len(hours))], span=secured_span,
            reason="Counted secured requests whose first accepted donor was confirmed after required_by.",
            limitations=["Requests that were never secured are not included."],
            consideration="Review where time is lost when this share is high.", numerator=late, denominator=len(hours), sample=len(hours)))

        totals: dict[RecoveryActionType, int] = defaultdict(int)
        for action, _, count in self._repo.recovery_status_counts():
            totals[action] += count
        all_actions = sum(totals.values())
        groups = [group(a.value.replace("_", " ").title(), c, all_actions) for a, c in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0].value))]
        escalations = sum(c for a, c in totals.items() if a in ESCALATION_ACTIONS)
        out.append(_insight(
            "CB-RECOVERY-ROUTES-RECORDED", InsightCategory.COORDINATION_BOTTLENECK, source, "Which recovery routes were needed",
            (f"{describe(groups)}. {escalations} of {all_actions} recoveries ended in human or blood-bank escalation." if groups
             else "No recovery actions were recorded."), groups=groups, span=recovery_span,
            reason="Share of recorded recovery actions by type; repeated wider searches or escalations point at thin candidate pools.",
            limitations=["Counts show which routes were used, not whether they were the right ones."],
            consideration="A high share of expanded searches suggests the local pool is a recurring bottleneck.",
            numerator=escalations, denominator=all_actions, sample=all_actions))

        exhausted = dict(category_counts).get(FailureCategory.CASCADE_EXHAUSTED, 0)
        total_failures = sum(c for _, c in category_counts)
        out.append(_insight(
            "CB-POOL-EXHAUSTION-RECORDED", InsightCategory.COORDINATION_BOTTLENECK, source, "Recorded candidate-pool exhaustion",
            f"{exhausted} of {total_failures} recorded failures were classified as candidate-pool exhaustion.",
            groups=[group("Pool exhausted", exhausted, total_failures)], span=failure_span,
            reason="Counted failures stored with the CASCADE_EXHAUSTED category.",
            limitations=["Zero records does not show pools were never exhausted; the category is only recorded when someone assigns it."],
            consideration="Look for exhaustion in simulated cascades, where the candidate pool is visible.",
            numerator=exhausted, denominator=total_failures, sample=total_failures))
        return out

    # SIMULATED ----------------------------------------------------------------------------------------

    def simulated_report(self, runs: Sequence[CascadeResult], seeds: Sequence[int]) -> LearningReport:
        """Insights from in-memory cascade runs only. Nothing recorded is read or mixed in."""
        source = FailureSource.SIMULATED
        start = min((r.simulation_start for r in runs), default=None)
        end = max((r.completed_at for r in runs), default=None)
        span = window(start, end)

        counts: dict[InteractionChannel, list[int]] = defaultdict(lambda: [0, 0, 0])
        minutes: dict[InteractionChannel, list[float]] = defaultdict(list)
        patterns: Counter[FailurePatternType] = Counter()
        failed_waves = 0
        recovery_wins: dict[str, int] = defaultdict(int)
        recovery_totals: dict[str, int] = defaultdict(int)
        escalated = fulfilled = on_time = waves = 0
        elapsed: list[float] = []
        for run in runs:
            waves += run.waves_used
            elapsed.append(float(run.elapsed_minutes))
            escalated += run.requires_human_intervention
            fulfilled += run.outcome.value == "FULFILLED"
            on_time += run.deadline_met
            for index, wave in enumerate(run.waves):
                for contact in wave.contacts:
                    counts[contact.channel][2] += 1
                    counts[contact.channel][0] += contact.response is not SimulatedResponse.NO_RESPONSE
                    counts[contact.channel][1] += contact.response is SimulatedResponse.ACCEPTED
                    if contact.responded_at:
                        minutes[contact.channel].append((contact.responded_at - contact.sent_at).total_seconds() / 60)
                if wave.failure_autopsy and wave.failure_autopsy.failures_analyzed >= MIN_PATTERN_FAILURES:
                    failed_waves += 1
                    for pattern in {p.pattern_type for p in wave.failure_autopsy.patterns}:
                        patterns[pattern] += 1
                plan = wave.recovery_plan
                if plan and not plan.requires_human_intervention and index + 1 < len(run.waves):
                    name = plan.primary_action.value
                    recovery_totals[name] += 1
                    recovery_wins[name] += any(c.secured for c in run.waves[index + 1].contacts)

        n = len(runs)
        insights = channel_insights(source, {c: (v[0], v[1], v[2]) for c, v in counts.items()}, span)
        insights.append(latency_insight(source, minutes, span))
        insights += pattern_insights(source, patterns, failed_waves, span, "failed wave")
        actions = sum(recovery_totals.values())
        insights += recovery_insights(
            source, {a: (recovery_wins[a], t) for a, t in recovery_totals.items()}, actions, span,
            "Each applied Self-Healing plan is compared with whether the next simulated wave secured a donor.")
        insights.append(_insight(
            "DF-CONTACT-LOAD-SIMULATED", InsightCategory.DONOR_FATIGUE, source, "Donor fatigue in simulation",
            "Not assessable: a simulated cascade contacts each donor at most once, so there is no repeated-contact load to analyse.",
            groups=[], span=span, reason="Fatigue needs repeated contact over time, which a single cascade run does not contain.",
            limitations=["Separate runs are independent simulations, not repeated contact with the same donor."],
            consideration="Collect more data before relying on this.", cap=OBSERVATIONAL_CAP, sample=0))
        insights.append(_insight(
            "CB-ESCALATION-SIMULATED", InsightCategory.COORDINATION_BOTTLENECK, source, "Runs that needed human intervention",
            f"{escalated} of {n} simulated run(s) ended with automation stopping for human intervention; {fulfilled} of {n} secured the requirement"
            f" ({on_time} before the required-by time); median {median(elapsed) if elapsed else 'n/a'} simulated minutes.",
            groups=[group("Human intervention required", escalated, n), group("Requirement secured", fulfilled, n)], span=span,
            reason="Counted completed simulated runs by outcome; elapsed time is simulated.",
            limitations=["Outcomes depend on the response-stress setting and seeds chosen for the simulation."],
            consideration="A high intervention share under realistic stress suggests reviewing candidate-pool depth.",
            numerator=escalated, denominator=n, sample=n))
        seeds_text = f"seeds {seeds[0]}-{seeds[-1]}" if len(seeds) > 1 else f"seed {seeds[0]}" if seeds else "no seeds"
        population = f"{n} simulated cascade run(s), {seeds_text}, {waves} wave(s), {sum(v[2] for v in counts.values())} contacts"
        return _assemble(source, population, span, insights, [], self._adjustments, self._data_notice)
