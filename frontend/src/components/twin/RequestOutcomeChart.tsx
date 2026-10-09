import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatShortDate, humanize } from "../../lib/format";
import type { RequestOutcomeSummary } from "../../types/twin";
import { OUTCOME_COLORS } from "./display";

interface ChartRow {
  label: string;
  code: string;
  status: string;
  failed: number;
  successful: number;
}

const SERIES = [
  { key: "failed", label: "Failed attempts", color: OUTCOME_COLORS.failed },
  { key: "successful", label: "Successful attempts", color: OUTCOME_COLORS.successful },
] as const;

interface TooltipProps {
  active?: boolean;
  payload?: Array<{ payload: ChartRow }>;
}

function OutcomeTooltip({ active, payload }: TooltipProps) {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-sm">
      <p className="font-mono font-medium text-slate-900">{row.code}</p>
      <p className="text-slate-500">
        {row.label} · {humanize(row.status)}
      </p>
      {SERIES.map((s) => (
        <p key={s.key} className="mt-1 flex items-center gap-2 text-slate-700">
          <span className="inline-block size-2 rounded-sm" style={{ background: s.color }} aria-hidden="true" />
          {s.label}: <span className="font-medium tabular-nums">{row[s.key]}</span>
        </p>
      ))}
    </div>
  );
}

/** Attempts per request, oldest first: how many failed before (or without) success. */
export function RequestOutcomeChart({ requests }: { requests: RequestOutcomeSummary[] }) {
  const rows: ChartRow[] = requests.map((r) => ({
    label: formatShortDate(r.requested_at),
    code: r.request_code,
    status: r.status,
    failed: r.failed_attempts,
    successful: r.successful_attempts,
  }));

  return (
    <figure>
      <figcaption className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-medium tracking-wide text-slate-500 uppercase">Attempts per request</span>
        <span className="flex gap-3 text-xs text-slate-600">
          {SERIES.map((s) => (
            <span key={s.key} className="flex items-center gap-1.5">
              <span className="inline-block size-2.5 rounded-sm" style={{ background: s.color }} aria-hidden="true" />
              {s.label}
            </span>
          ))}
        </span>
      </figcaption>
      <div className="mt-2 h-40" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: -24 }} barCategoryGap="30%">
            <CartesianGrid vertical={false} stroke="#e2e8f0" />
            <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: "#cbd5e1" }} tick={{ fontSize: 12, fill: "#64748b" }} />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "#64748b" }} />
            <Tooltip content={<OutcomeTooltip />} cursor={{ fill: "#f1f5f9" }} />
            <Bar
              dataKey="failed"
              stackId="attempts"
              fill={OUTCOME_COLORS.failed}
              stroke="#ffffff"
              strokeWidth={2}
              isAnimationActive={false}
            />
            <Bar
              dataKey="successful"
              stackId="attempts"
              fill={OUTCOME_COLORS.successful}
              stroke="#ffffff"
              strokeWidth={2}
              radius={[4, 4, 0, 0]}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      {/* Tables ignore sr-only sizing, so the wrapper is what hides it. */}
      <div className="sr-only">
        <table>
          <caption>Coordination attempts per request</caption>
          <thead>
            <tr>
              <th>Request</th>
              <th>Requested</th>
              <th>Status</th>
              <th>Failed attempts</th>
              <th>Successful attempts</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.code}>
                <td>{row.code}</td>
                <td>{row.label}</td>
                <td>{humanize(row.status)}</td>
                <td>{row.failed}</td>
                <td>{row.successful}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  );
}
