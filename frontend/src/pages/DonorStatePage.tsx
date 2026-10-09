import { useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { BehaviourCard } from "../components/donor/BehaviourCard";
import { CurrentStateCard } from "../components/donor/CurrentStateCard";
import { DonorComparisonTable } from "../components/donor/DonorComparisonTable";
import { DonorStateHeader } from "../components/donor/DonorStateHeader";
import { WhyThisDonor } from "../components/donor/WhyThisDonor";
import { Card, CardBody } from "../components/ui/Card";
import { useApiQuery } from "../hooks/useApiQuery";
import { cn } from "../lib/cn";
import { formatBloodGroup } from "../lib/format";
import { donorService } from "../services/donorService";
import type { DonorRequestAssessment, DonorStateAssessment, EvaluateAt } from "../types/donorState";

export const DEMO_REQUEST_CODE = "DEMO-REQUEST-001";
const MAX_COMPARED = 10;
const EVALUATE_OPTIONS: Array<{ value: EvaluateAt; label: string }> = [
  { value: "auto", label: "Auto" },
  { value: "now", label: "Now" },
  { value: "request_start", label: "At request start" },
];

interface Loaded {
  state: DonorStateAssessment;
  context: DonorRequestAssessment | null;
}

function Message({ title, body }: { title: string; body: string }) {
  return (
    <Card className="mx-auto max-w-lg text-center">
      <CardBody className="py-10">
        <h1 className="text-lg font-semibold text-slate-900">{title}</h1>
        <p className="mt-2 text-sm text-slate-600">{body}</p>
        <Link to="/donors" className="mt-6 inline-block text-sm font-medium text-brand-700 hover:underline">
          Browse donors
        </Link>
      </CardBody>
    </Card>
  );
}

function ContextBar({ requestCode, evaluateAt }: { requestCode: string | null; evaluateAt: EvaluateAt }) {
  const [, setParams] = useSearchParams();
  const [draft, setDraft] = useState(requestCode ?? DEMO_REQUEST_CODE);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const code = draft.trim().toUpperCase();
    if (code) setParams({ request: code, at: evaluateAt });
  };

  return (
    <Card>
      <CardBody className="flex flex-col gap-4 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex rounded-lg border border-slate-200 p-0.5 text-sm" role="tablist" aria-label="Assessment context">
          <button
            type="button"
            role="tab"
            aria-selected={requestCode === null}
            onClick={() => setParams({})}
            className={cn("rounded-md px-3 py-1.5", requestCode === null ? "bg-slate-900 text-white" : "text-slate-600")}
          >
            General state
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={requestCode !== null}
            onClick={() => setParams({ request: draft.trim().toUpperCase() || DEMO_REQUEST_CODE, at: evaluateAt })}
            className={cn("rounded-md px-3 py-1.5", requestCode !== null ? "bg-slate-900 text-white" : "text-slate-600")}
          >
            For a request
          </button>
        </div>

        {requestCode !== null && (
          <form onSubmit={submit} className="flex flex-wrap items-center gap-3 text-sm">
            <label className="flex items-center gap-2 text-slate-600">
              Request
              <input
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                className="w-44 rounded-md border border-slate-300 px-2.5 py-1.5 font-mono text-slate-900"
                aria-label="Request code"
              />
            </label>
            <label className="flex items-center gap-2 text-slate-600">
              Evaluate
              <select
                value={evaluateAt}
                onChange={(event) => setParams({ request: requestCode, at: event.target.value })}
                className="rounded-md border border-slate-300 bg-white py-1.5 pr-8 pl-2.5 text-slate-900"
              >
                {EVALUATE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" className="rounded-md bg-brand-600 px-3 py-1.5 font-medium text-white hover:bg-brand-700">
              Assess
            </button>
          </form>
        )}
      </CardBody>
    </Card>
  );
}

function CompatibilityBanner({ context }: { context: DonorRequestAssessment }) {
  const { compatibility, request } = context;
  const tone = !compatibility.compatible
    ? "border-red-200 bg-red-50 text-red-800"
    : compatibility.exact_match
      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
      : "border-slate-200 bg-slate-50 text-slate-800";
  const verdict = !compatibility.compatible
    ? "Not compatible"
    : compatibility.exact_match
      ? "Exact blood group match"
      : "Compatible substitute";
  return (
    <div className={cn("rounded-xl border px-5 py-4 text-sm", tone)}>
      <p className="font-medium">
        {verdict}: {formatBloodGroup(compatibility.donor_blood_group)} donor for {request.request_code} (
        {formatBloodGroup(request.blood_group)}, {request.urgency_level.toLowerCase()} urgency, patient {request.patient_code})
      </p>
      <p className="mt-1 opacity-80">
        Compatible donor groups: {compatibility.compatible_donor_groups.map(formatBloodGroup).join(", ")} ·{" "}
        {compatibility.rule_set}. {context.evaluation_note}
      </p>
      <Link to={`/requests/${request.request_code}/matching`} className="mt-2 inline-block font-medium underline">
        See all ranked candidates for {request.request_code}
      </Link>
    </div>
  );
}

function RequestComparison({
  requestCode,
  evaluateAt,
  donorCode,
}: {
  requestCode: string;
  evaluateAt: EvaluateAt;
  donorCode: string;
}) {
  const [extra, setExtra] = useState<string[]>([]);
  const [draft, setDraft] = useState("");

  // Default set: donors this request's cascade contacted. Add this donor and any extras on top.
  const base = useApiQuery(
    (signal) => donorService.compareForRequest(requestCode, evaluateAt, undefined, signal),
    `compare:${requestCode}:${evaluateAt}`,
  );
  const baseCodes = base.status === "success" ? base.data.candidates.map((c) => c.state.donor.donor_code) : [];
  const desired = [...new Set([...baseCodes, donorCode, ...extra])].slice(0, MAX_COMPARED);
  const needsCustom = base.status === "success" && desired.some((code) => !baseCodes.includes(code));
  const custom = useApiQuery(
    (signal) =>
      needsCustom ? donorService.compareForRequest(requestCode, evaluateAt, desired, signal) : Promise.resolve(null),
    `compare:${requestCode}:${evaluateAt}:${needsCustom ? desired.join(",") : "-"}`,
  );
  const result = needsCustom ? custom : base;

  const add = (event: FormEvent) => {
    event.preventDefault();
    const code = draft.trim().toUpperCase();
    if (code && !desired.includes(code) && desired.length < MAX_COMPARED) setExtra([...extra, code]);
    setDraft("");
  };

  const addControl = (
    <form onSubmit={add} className="flex items-center gap-2 text-sm">
      <input
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder="DON-00042"
        className="w-28 rounded-md border border-slate-300 px-2 py-1 font-mono text-slate-900"
        aria-label="Donor code to add to the comparison"
      />
      <button type="submit" className="rounded-md border border-slate-300 px-2.5 py-1 font-medium text-slate-700 hover:bg-slate-50">
        Add
      </button>
    </form>
  );

  if (result.status === "loading") return <p className="text-sm text-slate-500">Comparing donors…</p>;
  if (result.status === "error") {
    return (
      <Card>
        <CardBody className="text-sm text-red-700">
          {result.error.message}{" "}
          {extra.length > 0 && (
            <button type="button" onClick={() => setExtra([])} className="ml-2 font-medium underline">
              Remove added donors
            </button>
          )}
        </CardBody>
      </Card>
    );
  }
  if (result.data === null) return null;
  return <DonorComparisonTable comparison={result.data} highlight={donorCode} action={addControl} />;
}

export function DonorStatePage() {
  const { donorCode = "" } = useParams();
  const [params] = useSearchParams();
  const requestCode = params.get("request");
  const evaluateAt = (EVALUATE_OPTIONS.some((o) => o.value === params.get("at")) ? params.get("at") : "auto") as EvaluateAt;

  const query = useApiQuery<Loaded>(
    (signal) =>
      requestCode
        ? donorService
            .getStateForRequest(donorCode, requestCode, evaluateAt, signal)
            .then((context) => ({ state: context.state, context }))
        : donorService.getState(donorCode, signal).then((state) => ({ state, context: null })),
    `donor:${donorCode}:${requestCode ?? "-"}:${evaluateAt}`,
  );

  if (query.status === "loading") {
    return <p className="py-20 text-center text-sm text-slate-500">Assessing donor {donorCode}…</p>;
  }
  if (query.status === "error") {
    return query.error.status === 404 ? (
      <Message title="Not found" body={query.error.message.includes("404") ? `${donorCode} or ${requestCode ?? "the request"} was not found.` : query.error.message} />
    ) : (
      <Message title="Donor state unavailable" body={query.error.message} />
    );
  }

  const { state, context } = query.data;
  return (
    <div className="space-y-6">
      <DonorStateHeader
        state={state}
        priorityContext={context ? `for ${context.request.request_code}` : "general operational priority (no request)"}
      />
      <ContextBar key={requestCode ?? "-"} requestCode={requestCode} evaluateAt={evaluateAt} />
      {context && <CompatibilityBanner context={context} />}

      <div className="grid items-start gap-6 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <CurrentStateCard state={state} />
        </div>
        <div className="lg:col-span-2">
          <WhyThisDonor priority={state.priority} />
        </div>
      </div>

      <BehaviourCard state={state} />

      {context && (
        <RequestComparison
          key={`${context.request.request_code}:${evaluateAt}`}
          requestCode={context.request.request_code}
          evaluateAt={evaluateAt}
          donorCode={state.donor.donor_code}
        />
      )}

      <p className="text-center text-xs text-slate-500">
        Demo coordination rules and operational priority only — not a medical eligibility or suitability assessment.{" "}
        {state.data_notice}
      </p>
    </div>
  );
}
