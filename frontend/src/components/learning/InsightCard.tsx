import { AlertTriangle, Lightbulb } from "lucide-react";
import { formatDateTime, humanize } from "../../lib/format";
import type { EvidenceStrength, Insight, InsightGroup, Recommendation, TimeWindow } from "../../types/learning";
import { StatusBadge, type StatusTone } from "../ui/Status";

export const STRENGTH_TONE: Record<EvidenceStrength, StatusTone> = {
  HIGH: "ok",
  MODERATE: "pending",
  LOW: "warning",
  INSUFFICIENT_DATA: "neutral",
};

export function StrengthBadge({ strength }: { strength: EvidenceStrength }) {
  return <StatusBadge tone={STRENGTH_TONE[strength]}>{strength === "INSUFFICIENT_DATA" ? "Insufficient data" : `${humanize(strength)} evidence`}</StatusBadge>;
}

function windowText(window: TimeWindow): string {
  if (!window.start || !window.end) return "no time window";
  return `${formatDateTime(window.start)} → ${formatDateTime(window.end)} UTC`;
}

function GroupRow({ group }: { group: InsightGroup }) {
  const percent = group.rate === null ? null : Math.round(group.rate * 100);
  return (
    <li className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-3 text-sm">
      <span className="truncate text-slate-700" title={group.label}>
        {group.label}
      </span>
      {percent !== null ? (
        <span className="h-2 overflow-hidden rounded-full bg-slate-100" role="img" aria-label={`${group.label}: ${percent}%`}>
          <span className="block h-full rounded-full bg-slate-500" style={{ width: `${percent}%` }} />
        </span>
      ) : (
        <span />
      )}
      <span className="text-right text-xs text-slate-600 tabular-nums">
        {percent !== null
          ? `${percent}% · ${group.numerator}/${group.denominator}`
          : group.value !== null
            ? `${group.value} ${group.unit ?? ""} · n=${group.denominator}`
            : "—"}
      </span>
    </li>
  );
}

/** One insight: the finding with its numbers, sample size, evidence strength, reasoning and limits. */
export function InsightCard({ insight }: { insight: Insight }) {
  const insufficient = insight.strength === "INSUFFICIENT_DATA";
  return (
    <article className="rounded-xl border border-slate-200 bg-white px-5 py-4" aria-label={insight.title}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">{insight.title}</h3>
        <StrengthBadge strength={insight.strength} />
      </div>
      <p className="mt-2 text-sm text-slate-700">{insight.finding}</p>
      {insufficient && (
        <p className="mt-2 flex items-center gap-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <AlertTriangle className="size-4 shrink-0" aria-hidden="true" /> Insufficient data: no conclusion is drawn from this sample.
        </p>
      )}
      {insight.groups.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {insight.groups.map((group) => (
            <GroupRow key={group.label} group={group} />
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-slate-500 tabular-nums">
        Sample size {insight.sample_size}
        {insight.numerator !== null && insight.denominator !== null && ` · ${insight.numerator} of ${insight.denominator}`} ·{" "}
        {windowText(insight.time_window)}
      </p>
      <p className="mt-2 text-xs text-slate-700">
        <span className="font-semibold">Consideration (not an implemented change): </span>
        {insight.consideration}
      </p>
      <details className="mt-2 text-xs text-slate-600">
        <summary className="cursor-pointer font-medium text-slate-700">Why this conclusion, and its limits</summary>
        <p className="mt-1.5">
          <span className="font-semibold">Evidence strength: </span>
          {insight.strength_reason}
        </p>
        <p className="mt-1.5">
          <span className="font-semibold">Reason: </span>
          {insight.reason}
        </p>
        <ul className="mt-1.5 list-disc space-y-0.5 pl-4">
          {insight.limitations.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
        <p className="mt-1.5 text-slate-500">{insight.provenance}</p>
      </details>
    </article>
  );
}

export function RecommendationList({ items, adjustmentsEnabled }: { items: Recommendation[]; adjustmentsEnabled: boolean }) {
  if (items.length === 0) return <p className="text-sm text-slate-500">No recommendations: nothing in this evidence supports a change.</p>;
  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <li key={item.recommendation_id} className="flex gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-800">
          <Lightbulb className="mt-0.5 size-4 shrink-0 text-amber-600" aria-hidden="true" />
          <div className="min-w-0">
            <p>{item.text}</p>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <span className="font-medium text-slate-700">Recommendation only</span>
              <StatusBadge tone="neutral">Not implemented</StatusBadge>
              <StrengthBadge strength={item.strength} />
              {item.adjustment && (
                <span>
                  Bounded proposal {item.adjustment.target} ±{item.adjustment.value} (limit {item.adjustment.bound}), not applied
                </span>
              )}
              {!item.adjustment && !adjustmentsEnabled && item.strength !== "INSUFFICIENT_DATA" && <span>Adjustments are disabled</span>}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}
