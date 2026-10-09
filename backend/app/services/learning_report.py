"""Learning report for simulated cascades: runs the (deterministic, in-memory) cascade for consecutive seeds
and hands the results to the Learning Engine. Nothing is persisted."""

from app.schemas.learning import LearningReport
from app.services.cascade import DEFAULT_MAX_WAVES, AdaptiveCascadeEngine
from app.services.learning import LearningEngine

MAX_LEARNING_RUNS = 10


class LearningReportService:
    def __init__(self, cascade: AdaptiveCascadeEngine, learning: LearningEngine) -> None:
        self._cascade = cascade
        self._learning = learning

    def simulated(
        self, request_code: str, *, seed: int, runs: int = 1, evaluate_at: str = "auto",
        max_waves: int = DEFAULT_MAX_WAVES, wave_size: int | None = None, response_stress: str = "none",
    ) -> LearningReport:
        """Raises UnknownCode for an unknown request. Run i uses seed + i, so results are reproducible."""
        seeds = [seed + offset for offset in range(max(1, min(runs, MAX_LEARNING_RUNS)))]
        results = [
            self._cascade.simulate(request_code, evaluate_at=evaluate_at, max_waves=max_waves, wave_size=wave_size,
                                   seed=s, response_stress=response_stress)
            for s in seeds
        ]
        return self._learning.simulated_report(results, seeds)
