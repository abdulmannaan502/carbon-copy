import { ChevronDown } from "lucide-react";
import { Link } from "react-router";
import { formatBloodGroup } from "../../lib/format";
import type { MatchingResult } from "../../types/matching";
import { Card } from "../ui/Card";

export function ExcludedSection({ result }: { result: MatchingResult }) {
  const reasons = result.matching_summary.top_exclusion_reasons;
  const gate = reasons.filter((r) => r.stage === "gate");
  const discovery = reasons.filter((r) => r.stage === "discovery");

  return (
    <Card>
      <details className="group">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-6 py-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              Excluded candidates: {result.excluded_candidate_count.toLocaleString("en-US")}
            </h2>
            <p className="mt-0.5 text-sm text-slate-500">
              Every donor not ranked is accounted for, with the rule that removed them.
            </p>
          </div>
          <ChevronDown className="size-5 text-slate-400 transition-transform group-open:rotate-180" aria-hidden="true" />
        </summary>

        <div className="grid gap-6 border-t border-slate-100 px-6 py-5 text-sm lg:grid-cols-2">
          <div>
            <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">
              Failed eligibility gate (in the candidate pool)
            </p>
            <dl className="mt-2 divide-y divide-slate-100">
              {gate.length === 0 && <p className="py-1.5 text-slate-500">None.</p>}
              {gate.map((r) => (
                <div key={r.reason} className="flex justify-between gap-4 py-1.5">
                  <dt className="text-slate-700">{r.reason}</dt>
                  <dd className="font-medium text-slate-900 tabular-nums">{r.count}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div>
            <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">
              Filtered during discovery (never loaded)
            </p>
            <dl className="mt-2 divide-y divide-slate-100">
              {discovery.map((r) => (
                <div key={r.reason} className="flex justify-between gap-4 py-1.5">
                  <dt className="text-slate-700">{r.reason}</dt>
                  <dd className="font-medium text-slate-900 tabular-nums">{r.count.toLocaleString("en-US")}</dd>
                </div>
              ))}
            </dl>
          </div>

          {result.excluded.length > 0 && (
            <div className="lg:col-span-2">
              <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">
                Nearest excluded donors ({result.excluded.length} shown)
              </p>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-xs tracking-wide text-slate-500 uppercase">
                    <tr>
                      <th className="py-1.5 pr-3 font-medium">Donor</th>
                      <th className="px-3 py-1.5 text-right font-medium">Distance</th>
                      <th className="py-1.5 pl-3 font-medium">Reason</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {result.excluded.map((c) => (
                      <tr key={c.donor_code}>
                        <td className="py-2 pr-3 whitespace-nowrap">
                          <Link
                            to={`/donors/${c.donor_code}?request=${result.request.request_code}`}
                            className="font-mono text-slate-900 hover:underline"
                          >
                            {c.donor_code}
                          </Link>{" "}
                          <span className="text-slate-500">{formatBloodGroup(c.blood_group)}</span>
                        </td>
                        <td className="px-3 py-2 text-right whitespace-nowrap text-slate-700 tabular-nums">
                          {c.distance_km === null ? "—" : `${c.distance_km.toFixed(1)} km`}
                        </td>
                        <td className="py-2 pl-3 text-slate-700">{c.exclusion_reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </details>
    </Card>
  );
}
