import { CheckCircle2, ChevronRight, ShieldAlert } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router";
import { FailureAutopsyPanel } from "../components/cascade/FailureAutopsyPanel";
import { HealingConnector } from "../components/cascade/HealingConnector";
import { WaveCard } from "../components/cascade/WaveCard";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { useApiQuery } from "../hooks/useApiQuery";
import { cn } from "../lib/cn";
import { formatBloodGroup, formatDateTime, humanize } from "../lib/format";
import { cascadeService } from "../services/cascadeService";
import { failureAutopsyService } from "../services/failureAutopsyService";
import type { CascadeQuery, CascadeResult, EvaluateAt, ResponseStress } from "../types/cascade";

const DEFAULT_SEED = 20261008;
const EVALUATE: EvaluateAt[] = ["auto", "now", "request_start"];
const STRESS: Array<{ value: ResponseStress; label: string }> = [
  { value: "none", label: "None (calibrated)" },
  { value: "moderate", label: "Moderate (replies ×0.75)" },
  { value: "severe", label: "Severe (replies ×0.5)" },
];

function readQuery(params: URLSearchParams): CascadeQuery {
  const seed = Number(params.get("seed"));
  const waves = Number(params.get("waves"));
  const at = params.get("at") as EvaluateAt;
  const stress = params.get("stress") as ResponseStress;
  return {
    seed: Number.isInteger(seed) && seed >= 0 && params.has("seed") ? seed : DEFAULT_SEED,
    maxWaves: Number.isInteger(waves) && waves >= 1 && waves <= 8 ? waves : 5,
    evaluateAt: EVALUATE.includes(at) ? at : "auto",
    stress: STRESS.some((s) => s.value === stress) ? stress : "none",
  };
}

function Controls({ query }: { query: CascadeQuery }) {
  const [params, setParams] = useSearchParams();
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next);
  };
  const select = "rounded-md border border-slate-300 bg-white py-1.5 pr-8 pl-2.5 text-sm text-slate-900";

  return (
    <Card>
      <CardBody className="flex flex-wrap items-end gap-x-6 gap-y-3 py-4 text-sm">
        <label className="flex flex-col gap-1 text-xs text-slate-500">
          Scenario seed
          <span className="flex items-center gap-2">
            <input
              type="number"
              min={0}
              value={query.seed}
              onChange={(e) => e.target.value !== "" && set("seed", e.target.value)}
              className="w-32 rounded-md border border-slate-300 px-2.5 py-1.5 font-mono text-sm text-slate-900"
            />
            <button
              type="button"
              onClick={() => set("seed", String(query.seed + 1))}
              className="inline-flex items-center gap-1 rounded-md border border-slate-300 px-2.5 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Next scenario <ChevronRight className="size-3.5" aria-hidden="true" />
            </button>
          </span>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-500">
          Response stress test
          <select value={query.stress} onChange={(e) => set("stress", e.target.value)} className={select}>
            {STRESS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-500">
          Max waves
          <select value={query.maxWaves} onChange={(e) => set("waves", e.target.value)} className={select}>
            {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-500">
          Evaluate
          <select value={query.evaluateAt} onChange={(e) => set("at", e.target.value)} className={select}>
            {EVALUATE.map((v) => (
              <option key={v} value={v}>
                {humanize(v)}
              </option>
            ))}
          </select>
        </label>
      </CardBody>
    </Card>
  );
}

/** RECORDED Failure Autopsy for this request's actual dataset history — fetched separately
 * from the SIMULATED cascade above, via the standalone `/failures/autopsy` endpoint. */
function RecordedFailureAutopsy({ requestCode, hasFailures }: { requestCode: string; hasFailures: boolean }) {
  const query = useApiQuery(
    (signal) => failureAutopsyService.getRequestAutopsy(requestCode, signal),
    `recorded-autopsy:${requestCode}`,
  );
  if (!hasFailures || query.status !== "success") return null;
  return (
    <div className="mt-4">
      <FailureAutopsyPanel autopsy={query.data} />
    </div>
  );
}

function OutcomeBanner({ result }: { result: CascadeResult }) {
  const fulfilled = result.outcome === "FULFILLED";
  const hours = Math.floor(result.elapsed_minutes / 60);
  const elapsed = hours ? `${hours} h ${result.elapsed_minutes % 60} min` : `${result.elapsed_minutes} min`;
  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-xl border px-6 py-5 sm:flex-row sm:items-center sm:justify-between",
        fulfilled ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50",
      )}
    >
      <div className="flex items-start gap-3">
        {fulfilled ? (
          <CheckCircle2 className="mt-0.5 size-6 shrink-0 text-emerald-600" aria-hidden="true" />
        ) : (
          <ShieldAlert className="mt-0.5 size-6 shrink-0 text-red-600" aria-hidden="true" />
        )}
        <div>
          <p className={cn("text-lg font-semibold", fulfilled ? "text-emerald-900" : "text-red-900")}>
            {fulfilled
              ? `Requirement secured in ${result.waves_used} wave${result.waves_used === 1 ? "" : "s"}`
              : result.requires_human_intervention
                ? `Human intervention required: ${humanize(result.escalation_type ?? "HUMAN_COORDINATOR")}`
                : `Escalated: ${humanize(result.escalation?.action ?? "HUMAN_COORDINATOR_REVIEW")}`}
          </p>
          <p className={cn("text-sm", fulfilled ? "text-emerald-800" : "text-red-800")}>
            {result.units_secured} of {result.units_required} unit(s) · {result.total_contacts} donors contacted ·{" "}
            {elapsed} simulated
            {fulfilled && ` · ${result.deadline_met ? "before" : "after"} the required-by time`}
            {fulfilled && result.secured_donor_codes.length > 0 && ` · secured by ${result.secured_donor_codes.join(", ")}`}
          </p>
          {!fulfilled && result.escalation && <p className="mt-1 text-sm text-red-800">{result.escalation.rationale}</p>}
        </div>
      </div>
    </div>
  );
}

export function CascadePage() {
  const { requestCode = "" } = useParams();
  const [params] = useSearchParams();
  const query = readQuery(params);
  const state = useApiQuery(
    (signal) => cascadeService.simulate(requestCode, query, signal),
    `cascade:${requestCode}:${query.seed}:${query.maxWaves}:${query.evaluateAt}:${query.stress}`,
  );

  if (state.status === "loading") {
    return <p className="py-20 text-center text-sm text-slate-500">Simulating cascade for {requestCode}…</p>;
  }
  if (state.status === "error") {
    return (
      <Card className="mx-auto max-w-lg text-center">
        <CardBody className="py-10">
          <h1 className="text-lg font-semibold text-slate-900">
            {state.error.status === 404 ? "Request not found" : "Cascade unavailable"}
          </h1>
          <p className="mt-2 text-sm text-slate-600">
            {state.error.status === 404 ? `There is no request with code ${requestCode}.` : state.error.message}
          </p>
        </CardBody>
      </Card>
    );
  }

  const result = state.data;
  const { request, parameters } = result;
  const recoverySignals = result.learning_preview.filter((s) => s.donor_code === null);

  return (
    <div className="space-y-6">
      <Card>
        <div className="flex flex-col gap-4 px-6 py-6 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-xs font-semibold tracking-[0.2em] text-brand-600">ADAPTIVE CASCADE · SIMULATION</p>
            <h1 className="mt-3 font-mono text-3xl font-semibold tracking-tight text-slate-900">{request.request_code}</h1>
            <p className="mt-3 text-sm text-slate-600">
              Patient{" "}
              <Link to={`/patients/${request.patient_code}/digital-twin`} className="font-mono font-medium text-slate-900 hover:underline">
                {request.patient_code}
              </Link>{" "}
              · {formatBloodGroup(request.blood_group)} · {humanize(request.urgency_level)} urgency · {request.city} ·
              required by {formatDateTime(request.required_by)} UTC
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Waves of {parameters.wave_size}, {parameters.response_window_minutes}-minute response window · {parameters.initial_channel_policy}.
            </p>
          </div>
          <div className="flex shrink-0 flex-col gap-2 text-sm lg:items-end">
            <Link
              to={`/requests/${request.request_code}/matching`}
              className="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline"
            >
              Candidate ranking (Matching Engine) <ChevronRight className="size-3.5" aria-hidden="true" />
            </Link>
            <p className="text-xs text-slate-500 tabular-nums">
              Starts {formatDateTime(result.simulation_start)} UTC ·{" "}
              {result.evaluation_point === "REQUEST_START" ? "as of request start" : "as of now"}
            </p>
          </div>
        </div>
      </Card>

      <Controls query={query} />
      <OutcomeBanner result={result} />

      <section aria-label="Waves" className="space-y-0">
        {result.waves.map((wave) => (
          <div key={wave.wave_number}>
            <WaveCard wave={wave} requestCode={request.request_code} />
            {wave.healing && (
              <HealingConnector
                failureAutopsy={wave.failure_autopsy}
                healing={wave.healing}
                plan={wave.recovery_plan}
                nextWave={result.waves.find((w) => w.wave_number === wave.wave_number + 1) ?? null}
                terminal={wave.recovery_plan?.requires_human_intervention ?? false}
              />
            )}
          </div>
        ))}
      </section>

      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Learning preview" description="Signals this run would record (not persisted)" />
          <CardBody>
            <ul className="divide-y divide-slate-100 text-sm">
              {result.learning_preview.map((s, index) => (
                <li key={index} className="flex justify-between gap-4 py-1.5">
                  <span className="text-slate-700">
                    {humanize(s.event_type)}
                    <span className="text-slate-400"> · {s.donor_code ?? s.source}</span>
                  </span>
                  <span className={cn("font-medium tabular-nums", s.signal >= 0 ? "text-emerald-700" : "text-amber-700")}>
                    {s.signal > 0 ? "+" : ""}
                    {s.signal.toFixed(2)}
                  </span>
                </li>
              ))}
            </ul>
            {recoverySignals.length === 0 && (
              <p className="mt-2 text-xs text-slate-500">No recovery was needed, so there are no recovery signals.</p>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="What actually happened" description="Recorded coordination attempts in the synthetic dataset" />
          <CardBody>
            {result.historical_attempts.length === 0 ? (
              <p className="text-sm text-slate-500">No attempts recorded for this request yet.</p>
            ) : (
              <ol className="space-y-1.5 text-sm">
                {result.historical_attempts.map((a) => (
                  <li key={a.sequence_number} className="flex justify-between gap-4">
                    <span>
                      <span className="text-slate-400 tabular-nums">{a.sequence_number}.</span>{" "}
                      <Link to={`/donors/${a.donor_code}?request=${request.request_code}`} className="font-mono text-slate-900 hover:underline">
                        {a.donor_code}
                      </Link>
                    </span>
                    <span className="text-slate-600">
                      {humanize(a.status)}
                      {a.outcome ? ` · ${humanize(a.outcome)}` : ""}
                    </span>
                  </li>
                ))}
              </ol>
            )}
            <p className="mt-3 text-xs text-slate-500">
              The simulation above shows what the Adaptive Cascade would do from the same starting point.
            </p>
            <RecordedFailureAutopsy
              requestCode={request.request_code}
              hasFailures={result.historical_attempts.some((a) => a.status === "FAILED")}
            />
          </CardBody>
        </Card>
      </div>

      <p className="text-center text-xs text-slate-500">
        {result.notice} Coordination simulation only — not a medical recommendation. {result.data_notice}
      </p>
    </div>
  );
}
