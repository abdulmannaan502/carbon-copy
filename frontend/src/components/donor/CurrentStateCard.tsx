import { CheckCircle2, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import type { DonorStateAssessment } from "../../types/donorState";
import { Card, CardBody, CardHeader } from "../ui/Card";
import { StatusBadge } from "../ui/Status";
import { AVAILABILITY_DISPLAY, FATIGUE_BAND_LABEL, SCORE_BAND_LABEL } from "./display";

function Tile({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 px-4 py-3">
      <dt className="text-xs font-medium tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className="mt-1.5 text-lg font-semibold text-slate-900 tabular-nums">{value}</dd>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

const outOf100 = (value: number) => (
  <>
    {value}
    <span className="text-sm font-normal text-slate-400"> / 100</span>
  </>
);

export function CurrentStateCard({ state }: { state: DonorStateAssessment }) {
  const availability = AVAILABILITY_DISPLAY[state.availability.availability_status];
  const { eligibility, reliability, response, fatigue, freshness } = state;

  return (
    <Card>
      <CardHeader title="Current state" description="Computed from observable coordination history" />
      <CardBody className="space-y-5">
        <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <Tile
            label="Availability"
            value={<StatusBadge tone={availability.tone}>{availability.label}</StatusBadge>}
            hint={state.availability.availability_reason}
          />
          <Tile
            label="Eligibility"
            value={
              <StatusBadge tone={eligibility.eligible ? "ok" : "critical"}>
                {eligibility.eligible ? "Eligible" : "Not eligible"}
              </StatusBadge>
            }
            hint="Demo coordination eligibility rules"
          />
          <Tile
            label="Reliability"
            value={outOf100(reliability.reliability_score)}
            hint={`${SCORE_BAND_LABEL[reliability.reliability_band]} · coordination track record`}
          />
          <Tile
            label="Response rate"
            value={response.response_rate === null ? "Insufficient data" : `${response.response_rate}%`}
            hint={
              response.data_sufficiency === "INSUFFICIENT_DATA"
                ? `Too little history for a rate (${response.total_interactions} interaction(s))`
                : `${response.total_responses} of ${response.total_interactions} messages answered`
            }
          />
          <Tile
            label="Coordination fatigue"
            value={outOf100(fatigue.fatigue_score)}
            hint={`${FATIGUE_BAND_LABEL[fatigue.fatigue_band]} · outreach load, not medical fatigue`}
          />
          <Tile
            label="Contact freshness"
            value={outOf100(freshness.contact_freshness_score)}
            hint={
              freshness.days_since_last_contact === null
                ? "No contact on record"
                : freshness.days_since_last_contact === 0
                  ? "Contacted today"
                  : `Last contact ${freshness.days_since_last_contact} day(s) ago`
            }
          />
        </dl>

        <div>
          <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">Eligibility checks</p>
          <ul className="mt-2 space-y-1.5">
            {eligibility.checks.map((check) => (
              <li key={check.rule} className="flex gap-2 text-sm text-slate-700">
                {check.passed ? (
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-label="Passed" />
                ) : (
                  <XCircle className="mt-0.5 size-4 shrink-0 text-red-600" aria-label="Failed" />
                )}
                {check.detail}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-slate-500">
            {eligibility.rule_set} — not a clinical eligibility determination.
          </p>
        </div>
      </CardBody>
    </Card>
  );
}
