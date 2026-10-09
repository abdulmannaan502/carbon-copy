import { ShieldAlert } from "lucide-react";
import { useSearchParams } from "react-router";
import { InsightCard, RecommendationList, StrengthBadge } from "../components/learning/InsightCard";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { useApiQuery } from "../hooks/useApiQuery";
import { learningService } from "../services/learningService";
import type { InsightCategory, LearningReport, LearningSimulationQuery } from "../types/learning";

const DEMO_REQUEST = "DEMO-REQUEST-001";
const STRESS: Array<{ value: LearningSimulationQuery["stress"]; label: string }> = [
  { value: "none", label: "None (calibrated)" },
  { value: "moderate", label: "Moderate (replies ×0.75)" },
  { value: "severe", label: "Severe (replies ×0.5)" },
];
const SECTIONS: Array<{ category: InsightCategory; title: string }> = [
  { category: "CHANNEL_EFFECTIVENESS", title: "Channel effectiveness" },
  { category: "FAILURE_PATTERN", title: "Failure patterns" },
  { category: "RECOVERY_EFFECTIVENESS", title: "Recovery effectiveness" },
  { category: "DONOR_FATIGUE", title: "Donor fatigue" },
  { category: "COORDINATION_BOTTLENECK", title: "Coordination bottlenecks" },
];

function readQuery(params: URLSearchParams): LearningSimulationQuery & { request: string } {
  const seed = Number(params.get("seed"));
  const runs = Number(params.get("runs"));
  const stress = params.get("stress") as LearningSimulationQuery["stress"];
  return {
    request: params.get("request") || DEMO_REQUEST,
    seed: params.has("seed") && Number.isInteger(seed) && seed >= 0 ? seed : 25,
    runs: Number.isInteger(runs) && runs >= 1 && runs <= 10 ? runs : 5,
    stress: STRESS.some((s) => s.value === stress) ? stress : "none",
  };
}

function Sufficiency({ report }: { report: LearningReport }) {
  return (
    <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" aria-label="Data sufficiency">
      {report.sufficiency.map((entry) => (
        <li key={entry.capability} className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm">
          <p className="flex flex-wrap items-center justify-between gap-2 font-medium text-slate-900">
            {entry.capability}
            <StrengthBadge strength={entry.status} />
          </p>
          <p className="mt-1 text-xs text-slate-600">{entry.reason}</p>
        </li>
      ))}
    </ul>
  );
}

function ReportBody({ report }: { report: LearningReport }) {
  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600">
        <span className="font-medium text-slate-900">Population: </span>
        {report.population}. <span className="text-slate-500">{report.provenance}</span>
      </p>
      <section aria-label="Data sufficiency" className="space-y-2">
        <h3 className="text-sm font-semibold text-slate-900">Data sufficiency</h3>
        <Sufficiency report={report} />
      </section>
      {SECTIONS.map(({ category, title }) => {
        const insights = report.insights.filter((insight) => insight.category === category);
        if (insights.length === 0) return null;
        return (
          <section key={category} aria-label={title} className="space-y-3">
            <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
            <div className="grid items-start gap-3 lg:grid-cols-2">
              {insights.map((insight) => (
                <InsightCard key={insight.insight_id} insight={insight} />
              ))}
            </div>
          </section>
        );
      })}
      <section aria-label="Recommendations" className="space-y-2">
        <h3 className="text-sm font-semibold text-slate-900">Suggested coordination improvements</h3>
        <p className="text-xs text-slate-500">
          Recommendations are not implemented changes. {report.operational_effect} Learning adjustments are{" "}
          {report.adjustments_enabled ? "enabled (bounded proposals only)" : "disabled"}.
        </p>
        <RecommendationList items={report.recommendations} adjustmentsEnabled={report.adjustments_enabled} />
      </section>
      <details className="text-xs text-slate-600">
        <summary className="cursor-pointer font-medium text-slate-700">Evidence-strength thresholds</summary>
        <dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
          {Object.entries(report.thresholds).map(([key, value]) => (
            <div key={key} className="flex justify-between gap-3 border-b border-slate-100 py-1">
              <dt>{key.replaceAll("_", " ")}</dt>
              <dd className="font-mono">{String(value)}</dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  );
}

function Loading({ label }: { label: string }) {
  return <p className="py-10 text-center text-sm text-slate-500">{label}</p>;
}

function Failed({ message }: { message: string }) {
  return <p className="py-6 text-center text-sm text-red-700">{message}</p>;
}

export function LearningPage() {
  const [params, setParams] = useSearchParams();
  const query = readQuery(params);
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next);
  };
  const recorded = useApiQuery((signal) => learningService.getRecordedReport(signal), "learning:recorded");
  const simulated = useApiQuery(
    (signal) => learningService.getSimulationReport(query.request, query, signal),
    `learning:sim:${query.request}:${query.seed}:${query.runs}:${query.stress}`,
  );
  const select = "rounded-md border border-slate-300 bg-white py-1.5 pr-8 pl-2.5 text-sm text-slate-900";

  return (
    <div className="space-y-6">
      <Card>
        <div className="px-6 py-6">
          <p className="text-xs font-semibold tracking-[0.2em] text-brand-600">LEARNING ENGINE</p>
          <h1 className="mt-3 text-2xl font-semibold tracking-tight text-slate-900">What should be remembered?</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            Descriptive, evidence-backed insights from coordination outcomes. Failure Autopsy says what happened, Self-Healing says
            what should change, Learning says what the evidence suggests remembering. Recorded and simulated results are kept apart.
          </p>
        </div>
      </Card>

      <div role="note" className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900">
        <ShieldAlert className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
        <p>
          <span className="font-semibold">Synthetic demonstration data — not for clinical use.</span> Insights describe this generated dataset only.
          They are observational associations, not causal findings, not evidence of real-world effectiveness, and recommendations are
          not implemented operational changes.
        </p>
      </div>

      <Card>
        <CardHeader title="Recorded data" description="RECORDED: stored outcomes in the synthetic dataset" />
        <CardBody>
          {recorded.status === "loading" && <Loading label="Analysing recorded outcomes…" />}
          {recorded.status === "error" && <Failed message={recorded.error.message} />}
          {recorded.status === "success" && <ReportBody report={recorded.data} />}
        </CardBody>
      </Card>

      <Card className="border-sky-200">
        <CardHeader
          title="Simulation"
          description="SIMULATED: in-memory cascade runs; never combined with the recorded results above"
        />
        <CardBody className="space-y-5">
          <div className="flex flex-wrap items-end gap-x-6 gap-y-3 text-sm">
            <label className="flex flex-col gap-1 text-xs text-slate-500">
              Request
              <input
                value={query.request}
                onChange={(e) => e.target.value && set("request", e.target.value.trim())}
                className="w-48 rounded-md border border-slate-300 px-2.5 py-1.5 font-mono text-sm text-slate-900"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-500">
              First seed
              <input
                type="number"
                min={0}
                value={query.seed}
                onChange={(e) => e.target.value !== "" && set("seed", e.target.value)}
                className="w-32 rounded-md border border-slate-300 px-2.5 py-1.5 font-mono text-sm text-slate-900"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-500">
              Runs pooled
              <select value={query.runs} onChange={(e) => set("runs", e.target.value)} className={select}>
                {[1, 2, 3, 5, 8, 10].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
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
          </div>
          {simulated.status === "loading" && <Loading label="Simulating cascades…" />}
          {simulated.status === "error" && (
            <Failed message={simulated.error.status === 404 ? `There is no request with code ${query.request}.` : simulated.error.message} />
          )}
          {simulated.status === "success" && <ReportBody report={simulated.data} />}
        </CardBody>
      </Card>

      <p className="text-center text-xs text-slate-500">
        Synthetic demonstration data — not for clinical use. Learning is advisory and deterministic: no model is trained and
        nothing here changes matching, donor state, recovery or safety limits.
      </p>
    </div>
  );
}
