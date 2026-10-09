import { ArrowRight, CheckCircle2, MinusCircle, XCircle } from "lucide-react";
import { Link } from "react-router";
import { formatBloodGroup } from "../../lib/format";
import type { Impact } from "../../types/donorState";
import type { MatchCandidate } from "../../types/matching";
import { Card, CardBody, CardHeader } from "../ui/Card";
import { StrategyBadge } from "./StrategyBadge";

const IMPACT: Record<Impact, { icon: typeof CheckCircle2; className: string; label: string }> = {
  POSITIVE: { icon: CheckCircle2, className: "text-emerald-600", label: "Supports" },
  NEUTRAL: { icon: MinusCircle, className: "text-slate-400", label: "Neutral" },
  NEGATIVE: { icon: XCircle, className: "text-amber-600", label: "Against" },
};

export function WhyCandidate({ candidate, requestCode }: { candidate: MatchCandidate; requestCode: string }) {
  const weighted = candidate.score_breakdown.reduce((sum, c) => sum + c.points, 0);

  return (
    <Card className="flex flex-col">
      <CardHeader
        title={`Why #${candidate.rank}?`}
        description={`${candidate.donor_code} · ${formatBloodGroup(candidate.blood_group)} · ${candidate.city}`}
        action={candidate.candidate_strategy && <StrategyBadge strategy={candidate.candidate_strategy} />}
      />
      <CardBody className="flex flex-col gap-5">
        <div className="flex items-baseline gap-2">
          <span className="text-4xl font-semibold tracking-tight text-slate-900 tabular-nums">{candidate.match_score}</span>
          <span className="text-slate-400">/ 100 match score</span>
        </div>

        <ul className="space-y-2" aria-label="Reasons">
          {candidate.reasons.map((reason) => {
            const { icon: Icon, className, label } = IMPACT[reason.impact];
            return (
              <li key={reason.text} className="flex gap-2.5 text-sm text-slate-800">
                <Icon className={`mt-0.5 size-4 shrink-0 ${className}`} aria-label={label} />
                {reason.text}
              </li>
            );
          })}
        </ul>

        {candidate.strategy_reason && (
          <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
            <span className="font-medium text-slate-700">Strategy: </span>
            {candidate.strategy_reason}.
          </p>
        )}

        <div className="border-t border-slate-100 pt-4">
          <div className="flex items-baseline justify-between">
            <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">Match score breakdown</p>
            <p className="text-xs text-slate-400">score × weight = points</p>
          </div>
          <table className="mt-2 w-full text-sm">
            <tbody>
              {candidate.score_breakdown.map((component) => (
                <tr key={component.key}>
                  <th scope="row" className="py-1 pr-3 text-left font-normal whitespace-nowrap text-slate-600">
                    {component.label} <span className="text-xs text-slate-400">{component.weight}%</span>
                  </th>
                  <td className="w-full py-1">
                    <div className="h-1.5 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
                      <div className="h-full rounded-full bg-slate-800" style={{ width: `${component.score}%` }} />
                    </div>
                  </td>
                  <td className="py-1 pl-3 text-right text-slate-700 tabular-nums">{component.score}</td>
                  <td className="py-1 pl-3 text-right text-slate-500 tabular-nums">+{component.points.toFixed(1)}</td>
                </tr>
              ))}
              {candidate.strategy_adjustment !== 0 && (
                <tr>
                  <th scope="row" colSpan={3} className="py-1 pr-3 text-left font-normal text-slate-600">
                    {candidate.strategy_adjustment > 0 ? "Exploration bonus" : "Urgent uncertainty discount"}
                  </th>
                  <td className="py-1 pl-3 text-right text-slate-500 tabular-nums">
                    {candidate.strategy_adjustment > 0 ? "+" : ""}
                    {candidate.strategy_adjustment.toFixed(1)}
                  </td>
                </tr>
              )}
              <tr className="border-t border-slate-200">
                <th scope="row" colSpan={3} className="pt-2 text-left font-medium text-slate-900">
                  Total
                </th>
                <td className="pt-2 pl-3 text-right font-semibold text-slate-900 tabular-nums">
                  {candidate.match_score}
                </td>
              </tr>
            </tbody>
          </table>
          <p className="mt-1 text-xs text-slate-400 tabular-nums">
            Weighted points {weighted.toFixed(1)}
            {candidate.strategy_adjustment !== 0 &&
              ` ${candidate.strategy_adjustment > 0 ? "+" : "−"} ${Math.abs(candidate.strategy_adjustment)}`}
            , rounded and capped at 0–100.
          </p>
        </div>

        <Link
          to={`/donors/${candidate.donor_code}?request=${requestCode}`}
          className="inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline"
        >
          Full donor state for this request <ArrowRight className="size-3.5" aria-hidden="true" />
        </Link>
      </CardBody>
    </Card>
  );
}
