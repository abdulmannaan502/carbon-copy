import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { ExcludedSection } from "../components/matching/ExcludedSection";
import { RankingTable } from "../components/matching/RankingTable";
import { STRATEGY_LABELS } from "../components/matching/StrategyBadge";
import { WhyCandidate } from "../components/matching/WhyCandidate";
import { OPERATIONAL_STATE_DISPLAY } from "../components/twin/display";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { Metric } from "../components/ui/Metric";
import { StatusBadge } from "../components/ui/Status";
import { useApiQuery } from "../hooks/useApiQuery";
import { formatBloodGroup, formatDateTime, humanize } from "../lib/format";
import { matchingService } from "../services/matchingService";
import type { CandidateStrategy, EvaluateAt, MatchingResult } from "../types/matching";

const LIMITS = [10, 25, 50];
const EVALUATE_OPTIONS: Array<{ value: EvaluateAt; label: string }> = [
  { value: "auto", label: "Auto" },
  { value: "now", label: "Now" },
  { value: "request_start", label: "At request start" },
];

function MatchingHeader({ result, evaluateAt }: { result: MatchingResult; evaluateAt: EvaluateAt }) {
  const [params, setParams] = useSearchParams();
  const { request, digital_twin_context: twin } = result;
  const twinState = OPERATIONAL_STATE_DISPLAY[twin.operational_state];

  return (
    <Card>
      <div className="flex flex-col gap-6 px-6 py-6 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold tracking-[0.2em] text-brand-600">MATCHING ENGINE</p>
          <h1 className="mt-3 font-mono text-3xl font-semibold tracking-tight text-slate-900">{request.request_code}</h1>
          <dl className="mt-4 grid grid-cols-2 gap-x-8 gap-y-3 text-sm sm:flex sm:flex-wrap">
            <div>
              <dt className="text-xs text-slate-500">Patient</dt>
              <dd>
                <Link to={`/patients/${request.patient_code}/digital-twin`} className="font-mono font-medium text-slate-900 hover:underline">
                  {request.patient_code}
                </Link>
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Blood group</dt>
              <dd className="font-semibold text-slate-900">{formatBloodGroup(request.blood_group)}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Urgency</dt>
              <dd className="font-medium text-slate-900">{humanize(request.urgency_level)}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Status</dt>
              <dd className="font-medium text-slate-900">{humanize(request.status)}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Location</dt>
              <dd className="font-medium text-slate-900">{request.city}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Digital Twin</dt>
              <dd className="flex items-center gap-2">
                <StatusBadge tone={twinState.tone}>{twinState.label}</StatusBadge>
                <span className="text-xs text-slate-500 tabular-nums">network {twin.network_strength_score}/100</span>
              </dd>
            </div>
          </dl>
        </div>

        <div className="flex shrink-0 flex-col gap-2 lg:items-end">
          <label className="flex items-center gap-2 text-sm text-slate-600">
            Evaluate
            <select
              value={evaluateAt}
              onChange={(event) => {
                const next = new URLSearchParams(params);
                next.set("at", event.target.value);
                setParams(next);
              }}
              className="rounded-md border border-slate-300 bg-white py-1.5 pr-8 pl-2.5 text-slate-900"
            >
              {EVALUATE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <p className="max-w-sm text-xs text-slate-500 lg:text-right">{result.evaluation.note}</p>
          <p className="text-xs text-slate-400 tabular-nums">Assessed as of {formatDateTime(result.evaluation.assessed_at)} UTC</p>
          <Link
            to={`/requests/${request.request_code}/cascade`}
            className="mt-1 inline-flex items-center rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            Simulate adaptive cascade
          </Link>
        </div>
      </div>
    </Card>
  );
}

function CandidateOverview({ result }: { result: MatchingResult }) {
  const { discovery, matching_summary: summary, weights } = result;
  const strategies = Object.entries(summary.candidates_by_strategy) as Array<[CandidateStrategy, number]>;

  return (
    <Card>
      <CardHeader
        title="Candidate overview"
        description={`Compatible groups ${discovery.compatible_donor_groups.map(formatBloodGroup).join(", ")} · ${
          discovery.radius_km === null ? "whole region" : `${discovery.radius_km} km radius`
        }${discovery.radius_expanded ? " (expanded)" : ""}${discovery.pool_capped ? ` · nearest ${discovery.pool_cap}` : ""}`}
      />
      <CardBody>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4 lg:grid-cols-6">
          <Metric size="lg" label="Evaluated" value={result.candidate_pool_size} hint={`of ${discovery.total_donors.toLocaleString("en-US")} donors`} />
          <Metric size="lg" label="Eligible" value={result.eligible_candidate_count} />
          <Metric size="lg" label="Excluded" value={result.excluded_candidate_count} hint="failed a gate" />
          <Metric
            size="lg"
            label="Avg match"
            value={summary.average_match_score ?? "—"}
            hint={`${humanize(weights.profile)} weighting`}
          />
          {strategies.map(([strategy, count]) => (
            <Metric key={strategy} label={STRATEGY_LABELS[strategy]} value={count} hint="eligible candidates" />
          ))}
        </dl>
        <p className="mt-4 text-xs text-slate-500">
          Weights:{" "}
          {Object.entries(weights.components)
            .map(([key, weight]) => `${humanize(key)} ${weight}%`)
            .join(" · ")}
          {weights.exploration_bonus > 0 && ` · exploration bonus +${weights.exploration_bonus}`}
          {weights.uncertainty_discount > 0 && ` · unproven donors −${weights.uncertainty_discount} (urgent)`}
        </p>
      </CardBody>
    </Card>
  );
}

export function MatchingPage() {
  const { requestCode = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const evaluateAt = (EVALUATE_OPTIONS.some((o) => o.value === params.get("at")) ? params.get("at") : "auto") as EvaluateAt;
  const limit = LIMITS.includes(Number(params.get("limit"))) ? Number(params.get("limit")) : LIMITS[0];
  const [selected, setSelected] = useState<string | null>(null);

  const query = useApiQuery(
    (signal) => matchingService.getMatching(requestCode, limit, evaluateAt, signal),
    `matching:${requestCode}:${limit}:${evaluateAt}`,
  );

  if (query.status === "loading") {
    return <p className="py-20 text-center text-sm text-slate-500">Matching candidates for {requestCode}…</p>;
  }
  if (query.status === "error") {
    return (
      <Card className="mx-auto max-w-lg text-center">
        <CardBody className="py-10">
          <h1 className="text-lg font-semibold text-slate-900">
            {query.error.status === 404 ? "Request not found" : "Matching unavailable"}
          </h1>
          <p className="mt-2 text-sm text-slate-600">
            {query.error.status === 404 ? `There is no request with code ${requestCode}.` : query.error.message}
          </p>
        </CardBody>
      </Card>
    );
  }

  const result = query.data;
  const focus = result.ranking.find((c) => c.donor_code === selected) ?? result.ranking[0];
  const limitControl = (
    <label className="flex items-center gap-2 text-sm text-slate-600">
      Show
      <select
        value={limit}
        onChange={(event) => {
          const next = new URLSearchParams(params);
          next.set("limit", event.target.value);
          setParams(next);
        }}
        className="rounded-md border border-slate-300 bg-white py-1 pr-7 pl-2 text-slate-900"
      >
        {LIMITS.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="space-y-6">
      <MatchingHeader result={result} evaluateAt={evaluateAt} />
      <CandidateOverview result={result} />

      {result.ranking.length === 0 ? (
        <Card>
          <CardBody className="text-sm text-slate-600">No eligible candidates were found for this request.</CardBody>
        </Card>
      ) : (
        <div className="grid items-start gap-6 xl:grid-cols-3">
          <div className="min-w-0 xl:col-span-2">
            <RankingTable
              candidates={result.ranking}
              eligibleCount={result.eligible_candidate_count}
              selected={focus.donor_code}
              onSelect={setSelected}
              limitControl={limitControl}
            />
          </div>
          <div className="xl:sticky xl:top-6">
            <WhyCandidate candidate={focus} requestCode={result.request.request_code} />
          </div>
        </div>
      )}

      <ExcludedSection result={result} />

      <p className="text-center text-xs text-slate-500">
        Coordination recommendation from deterministic rules — not a medical recommendation or clinical suitability
        assessment. {result.notice} {result.data_notice}
      </p>
    </div>
  );
}
