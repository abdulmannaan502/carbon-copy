"""Self-Healing report: the recovery plans of a simulated cascade, plus an advisory plan for the failures
that were actually recorded in the synthetic dataset. The two sources are kept apart."""

from app.models.enums import FailureCategory
from app.schemas.failure_autopsy import FailureSource
from app.schemas.self_healing import RecoveryPlan, SelfHealingReport, WavePlan
from app.services.cascade import DEFAULT_MAX_WAVES, RANKING_DEPTH, WAVE_SIZE, AdaptiveCascadeEngine
from app.services.failure_autopsy import FailureAutopsyEngine
from app.services.matching import MatchingEngine
from app.services.self_healing import HIGH_FATIGUE_SCORE, CascadeState, SelfHealingEngine


class SelfHealingReportService:
    def __init__(
        self, cascade: AdaptiveCascadeEngine, failure_autopsy: FailureAutopsyEngine, matching: MatchingEngine,
        self_healing: SelfHealingEngine, data_notice: str,
    ) -> None:
        self._cascade = cascade
        self._failure_autopsy = failure_autopsy
        self._matching = matching
        self._self_healing = self_healing
        self._data_notice = data_notice

    def report(
        self, request_code: str, *, evaluate_at: str = "auto", max_waves: int = DEFAULT_MAX_WAVES,
        wave_size: int | None = None, seed: int, response_stress: str = "none",
    ) -> SelfHealingReport:
        """Raises UnknownCode for an unknown request."""
        run = self._cascade.simulate(
            request_code, evaluate_at=evaluate_at, max_waves=max_waves, wave_size=wave_size, seed=seed,
            response_stress=response_stress,
        )
        plans = [WavePlan(wave_number=w.wave_number, plan=w.recovery_plan) for w in run.waves if w.recovery_plan]
        parameters: dict[str, str | int] = {
            "seed": seed, "response_stress": response_stress, "max_waves": max_waves, "evaluate_at": evaluate_at,
            "wave_size": run.parameters.wave_size,
        }
        return SelfHealingReport(
            request_code=request_code, simulated_plans=plans, simulated_outcome=run.outcome.value,
            automatic_recovery_attempts=sum(not p.plan.requires_human_intervention for p in plans),
            requires_human_intervention=run.requires_human_intervention, escalation_type=run.escalation_type,
            recorded_plan=self._recorded_plan(request_code, evaluate_at), parameters=parameters,
            data_notice=self._data_notice,
        )

    def _recorded_plan(self, request_code: str, evaluate_at: str) -> RecoveryPlan | None:
        autopsy = self._failure_autopsy.analyze_request(request_code, evaluate_at)
        if autopsy.failures_analyzed == 0:
            return None
        match = self._matching.match(request_code, RANKING_DEPTH, evaluate_at=evaluate_at)
        urgency = match.request.urgency_level
        remaining = match.ranking  # donors who declined, failed or are engaged here are already excluded
        counts: dict[str, int] = {}
        for failure in autopsy.individual_failures:
            counts[failure.failure_type.value] = counts.get(failure.failure_type.value, 0) + 1
        state = CascadeState(
            wave_number=1, max_waves=DEFAULT_MAX_WAVES, urgency=urgency, wave_size=WAVE_SIZE[urgency],
            channel_override=None, radius_step=0, contacted_total=autopsy.failures_analyzed,
            remaining_candidates=len(remaining),
            fatigued_remaining=sum(c.fatigue_score >= HIGH_FATIGUE_SCORE for c in remaining),
            bridge_remaining=sum(c.bridge_group_member for c in remaining),
            wave_contacted=autopsy.failures_analyzed,
            no_response_channels=tuple(
                f.affected_channel for f in autopsy.individual_failures
                if f.failure_type is FailureCategory.NO_RESPONSE and f.affected_channel is not None
            ),
            failure_totals=counts,
        )
        return self._self_healing.plan(request_code, state, autopsy, source=FailureSource.RECORDED)
