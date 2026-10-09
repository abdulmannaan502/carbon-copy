import { Award } from "lucide-react";
import { Link } from "react-router";
import { cn } from "../../lib/cn";
import { formatBloodGroup } from "../../lib/format";
import type { DonorComparison } from "../../types/donorState";
import { Card, CardBody, CardHeader } from "../ui/Card";
import { StatusBadge } from "../ui/Status";
import { AVAILABILITY_DISPLAY, PRIORITY_DISPLAY } from "./display";

interface Props {
  comparison: DonorComparison;
  /** Donor to highlight, e.g. the donor whose page this is. */
  highlight?: string;
  /** Optional control rendered in the header (e.g. "add donor"). */
  action?: React.ReactNode;
}

/** Reusable side-by-side view of donor assessments for one request. Ranks the listed donors only. */
export function DonorComparisonTable({ comparison, highlight, action }: Props) {
  const evaluationLabel =
    comparison.evaluation_point === "REQUEST_START" ? "as of when coordination began" : "as of now";

  return (
    <Card>
      <CardHeader
        title={`Donor comparison · ${comparison.request.request_code}`}
        description={`${formatBloodGroup(comparison.request.blood_group)} request, ${comparison.request.urgency_level.toLowerCase()} urgency · assessed ${evaluationLabel}`}
        action={action}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-6 py-2.5 font-medium">Donor</th>
              <th className="px-3 py-2.5 text-right font-medium">Priority</th>
              <th className="px-3 py-2.5 text-right font-medium">Reliability</th>
              <th className="px-3 py-2.5 text-right font-medium">Response</th>
              <th className="px-3 py-2.5 text-right font-medium">Fatigue</th>
              <th className="px-3 py-2.5 text-right font-medium">Freshness</th>
              <th className="px-6 py-2.5 font-medium">Availability</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {comparison.candidates.map(({ state }) => {
              const code = state.donor.donor_code;
              const recommended = code === comparison.recommended_donor_code;
              const band = PRIORITY_DISPLAY[state.priority.priority_band];
              const availability = AVAILABILITY_DISPLAY[state.availability.availability_status];
              return (
                <tr key={code} className={cn(code === highlight && "bg-slate-50")}>
                  <td className="px-6 py-3">
                    <div className="flex items-center gap-2">
                      {recommended && <Award className="size-4 text-emerald-600" aria-label="Recommended" />}
                      <Link
                        to={`/donors/${code}?request=${comparison.request.request_code}`}
                        className="font-mono font-medium text-slate-900 hover:underline"
                      >
                        {code}
                      </Link>
                      <span className="text-slate-500">{formatBloodGroup(state.donor.blood_group)}</span>
                    </div>
                  </td>
                  <td className="px-3 py-3 text-right">
                    <span className="mr-2 font-semibold text-slate-900 tabular-nums">{state.priority.priority_score}</span>
                    <StatusBadge tone={band.tone}>{band.label}</StatusBadge>
                  </td>
                  <td className="px-3 py-3 text-right text-slate-700 tabular-nums">{state.reliability.reliability_score}</td>
                  <td className="px-3 py-3 text-right text-slate-700 tabular-nums">{state.response.response_score}</td>
                  <td className="px-3 py-3 text-right text-slate-700 tabular-nums">{state.fatigue.fatigue_score}</td>
                  <td className="px-3 py-3 text-right text-slate-700 tabular-nums">
                    {state.freshness.contact_freshness_score}
                  </td>
                  <td className="px-6 py-3 text-slate-700">{availability.label}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <CardBody className="border-t border-slate-100">
        {comparison.recommended_donor_code ? (
          <p className="text-sm text-slate-800">
            <span className="font-medium">Recommended among the listed donors: </span>
            <span className="font-mono font-medium">{comparison.recommended_donor_code}</span>
          </p>
        ) : (
          <p className="text-sm font-medium text-slate-800">No listed donor is eligible.</p>
        )}
        <p className="mt-1 text-sm text-slate-600">{comparison.recommendation_reason}</p>
        <p className="mt-2 text-xs text-slate-500">
          Response is the smoothed response score; fatigue is coordination fatigue (lower is better). {comparison.notice}
        </p>
      </CardBody>
    </Card>
  );
}
