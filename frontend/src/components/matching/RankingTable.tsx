import { cn } from "../../lib/cn";
import { formatBloodGroup } from "../../lib/format";
import type { MatchCandidate } from "../../types/matching";
import { Card, CardHeader } from "../ui/Card";
import { StrategyBadge } from "./StrategyBadge";

interface Props {
  candidates: MatchCandidate[];
  eligibleCount: number;
  selected: string | null;
  onSelect: (donorCode: string) => void;
  limitControl: React.ReactNode;
}

function ScoreBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-7 text-right font-semibold text-slate-900 tabular-nums">{value}</span>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
        <div className="h-full rounded-full bg-slate-800" style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

export function RankingTable({ candidates, eligibleCount, selected, onSelect, limitControl }: Props) {
  return (
    <Card>
      <CardHeader
        title="Ranked candidates"
        description={`Top ${candidates.length} of ${eligibleCount} eligible donors · select a row to see why`}
        action={limitControl}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="py-2.5 pr-2 pl-6 font-medium">Rank</th>
              <th className="px-3 py-2.5 font-medium">Donor</th>
              <th className="px-3 py-2.5 font-medium">Match</th>
              <th className="px-3 py-2.5 text-right font-medium">Distance</th>
              <th className="px-3 py-2.5 text-right font-medium">Reliability</th>
              <th className="px-3 py-2.5 text-right font-medium">Response</th>
              <th className="px-3 py-2.5 text-right font-medium">Fatigue</th>
              <th className="py-2.5 pr-6 pl-3 font-medium">Strategy</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {candidates.map((c) => {
              const isSelected = c.donor_code === selected;
              return (
                <tr
                  key={c.donor_code}
                  onClick={() => onSelect(c.donor_code)}
                  className={cn(
                    "cursor-pointer transition-colors",
                    isSelected ? "bg-brand-50/70" : "hover:bg-slate-50",
                  )}
                  aria-selected={isSelected}
                >
                  <td className="py-3 pr-2 pl-6">
                    <span
                      className={cn(
                        "grid size-7 place-items-center rounded-md text-xs font-semibold tabular-nums",
                        c.rank === 1 ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700",
                      )}
                    >
                      {c.rank}
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <button
                      type="button"
                      onClick={() => onSelect(c.donor_code)}
                      className="text-left focus-visible:outline-2"
                      aria-label={`Explain ${c.donor_code}`}
                    >
                      <span className="font-mono font-medium text-slate-900">{c.donor_code}</span>{" "}
                      <span className="text-slate-500">{formatBloodGroup(c.blood_group)}</span>
                      <span className="block text-xs text-slate-500">
                        {c.display_name} · {c.city}
                      </span>
                    </button>
                  </td>
                  <td className="px-3 py-3">
                    <ScoreBar value={c.match_score} />
                  </td>
                  <td className="px-3 py-3 text-right text-slate-700 tabular-nums">
                    {c.distance_km === null ? "—" : `${c.distance_km.toFixed(1)} km`}
                  </td>
                  <td className="px-3 py-3 text-right text-slate-700 tabular-nums">{c.reliability_score}</td>
                  <td className="px-3 py-3 text-right text-slate-700 tabular-nums">
                    {c.response_rate === null ? (
                      <span className="text-xs text-slate-500">Insufficient</span>
                    ) : (
                      `${c.response_rate}%`
                    )}
                  </td>
                  <td className="px-3 py-3 text-right text-slate-700 tabular-nums">{c.fatigue_score}</td>
                  <td className="py-3 pr-6 pl-3">{c.candidate_strategy && <StrategyBadge strategy={c.candidate_strategy} />}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
