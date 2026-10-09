import { CheckCircle2, MinusCircle, XCircle } from "lucide-react";
import type { Impact, PriorityAssessment } from "../../types/donorState";
import { humanize } from "../../lib/format";
import { Card, CardBody, CardHeader } from "../ui/Card";

const IMPACT_ICON: Record<Impact, { icon: typeof CheckCircle2; className: string; label: string }> = {
  POSITIVE: { icon: CheckCircle2, className: "text-emerald-600", label: "Supports" },
  NEUTRAL: { icon: MinusCircle, className: "text-slate-400", label: "Neutral" },
  NEGATIVE: { icon: XCircle, className: "text-amber-600", label: "Against" },
};

export function WhyThisDonor({ priority }: { priority: PriorityAssessment }) {
  return (
    <Card className="flex flex-col">
      <CardHeader
        title="Why this donor?"
        description={`Explanation of the operational priority · ${humanize(priority.weight_profile)} weighting`}
      />
      <CardBody className="flex flex-1 flex-col gap-5">
        <ul className="space-y-2">
          {priority.priority_reasons.map((reason) => {
            const { icon: Icon, className, label } = IMPACT_ICON[reason.impact];
            return (
              <li key={reason.text} className="flex gap-2.5 text-sm text-slate-800">
                <Icon className={`mt-0.5 size-4 shrink-0 ${className}`} aria-label={label} />
                {reason.text}
              </li>
            );
          })}
        </ul>

        <div className="mt-auto border-t border-slate-100 pt-4">
          <div className="flex items-baseline justify-between">
            <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">Priority factors</p>
            <p className="text-xs text-slate-400">score × weight = points</p>
          </div>
          <table className="mt-2 w-full text-sm">
            <tbody>
              {priority.priority_factors.map((factor) => (
                <tr key={factor.key}>
                  <th scope="row" className="py-1 pr-3 text-left font-normal whitespace-nowrap text-slate-600">
                    {factor.label} <span className="text-xs text-slate-400">{factor.weight}%</span>
                  </th>
                  <td className="w-full py-1">
                    <div className="h-1.5 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
                      <div className="h-full rounded-full bg-slate-800" style={{ width: `${factor.score}%` }} />
                    </div>
                  </td>
                  <td className="py-1 pl-3 text-right text-slate-700 tabular-nums">{factor.score}</td>
                  <td className="py-1 pl-3 text-right whitespace-nowrap text-slate-500 tabular-nums">
                    +{factor.contribution.toFixed(1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {priority.gated && (
            <p className="mt-2 text-xs text-red-700">An eligibility rule failed, so the priority score is 0.</p>
          )}
          <p className="mt-2 text-xs text-slate-500">Operational ranking score — not a clinical recommendation.</p>
        </div>
      </CardBody>
    </Card>
  );
}
