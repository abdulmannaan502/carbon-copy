import { CheckCircle2, MinusCircle, Search, XCircle } from "lucide-react";
import { Link } from "react-router";
import { humanize } from "../../lib/format";
import type { EvidenceItem, FailureSource, IndividualFailureAutopsy, RequestAutopsy } from "../../types/failureAutopsy";
import { StatusBadge, type StatusTone } from "../ui/Status";

const SEVERITY_TONE: Record<string, StatusTone> = { LOW: "neutral", MEDIUM: "warning", HIGH: "warning", CRITICAL: "critical" };
const SOURCE_LABEL: Record<FailureSource, { label: string; tone: StatusTone }> = {
  RECORDED: { label: "Recorded — what actually happened", tone: "neutral" },
  SIMULATED: { label: "Simulated cascade", tone: "pending" },
};

function Evidence({ items, requestCode }: { items: EvidenceItem[]; requestCode: string }) {
  return (
    <ul className="mt-1.5 space-y-1 text-sm text-slate-700">
      {items.map((item, index) => (
        <li key={index} className="flex gap-2">
          <span className="mt-1.5 size-1 shrink-0 rounded-full bg-slate-400" aria-hidden="true" />
          <span>
            {item.description}
            {item.reference && /^DON-\d{5}$/.test(item.reference) && (
              <>
                {" "}
                (
                <Link to={`/donors/${item.reference}?request=${requestCode}`} className="font-mono underline decoration-slate-300 underline-offset-2">
                  {item.reference}
                </Link>
                )
              </>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}

function IndividualFailureRow({ failure, requestCode }: { failure: IndividualFailureAutopsy; requestCode: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-slate-900">
          <Link to={`/donors/${failure.affected_donor}?request=${requestCode}`} className="font-mono hover:underline">
            {failure.affected_donor}
          </Link>{" "}
          <span className="font-normal text-slate-500">
            {humanize(failure.failure_type)}
            {failure.affected_channel && ` · ${humanize(failure.affected_channel)}`}
          </span>
        </p>
        <StatusBadge tone={SEVERITY_TONE[failure.severity]}>{humanize(failure.severity)}</StatusBadge>
      </div>
      <p className="mt-1 text-sm text-slate-700">{failure.summary}</p>
      <p className="mt-1 flex flex-wrap gap-x-3 text-xs text-slate-500">
        {failure.donor_specific && <span>donor-specific</span>}
        {failure.channel_specific && <span>channel-specific</span>}
        {failure.timing_related && <span>timing-related</span>}
        {failure.network_related && <span>network/context-related</span>}
        <span className="tabular-nums">rule confidence {Math.round(failure.rule_confidence * 100)}%</span>
      </p>
      <Evidence items={failure.evidence} requestCode={requestCode} />
    </div>
  );
}

/**
 * FAILURE AUTOPSY: "what happened, and why?" — a deterministic, evidence-based explanation.
 * It only recommends; it never decides or performs recovery. Self-Healing (rendered separately,
 * right after this panel) is what decides what the system actually does next.
 */
export function FailureAutopsyPanel({ autopsy }: { autopsy: RequestAutopsy }) {
  const source = SOURCE_LABEL[autopsy.source];
  const dominant = autopsy.dominant_pattern;

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-xs font-semibold tracking-wide text-amber-800 uppercase">
          <Search className="size-4" aria-hidden="true" /> Failure autopsy · {autopsy.failures_analyzed} failure
          {autopsy.failures_analyzed === 1 ? "" : "s"} analysed
        </p>
        <StatusBadge tone={source.tone}>{source.label}</StatusBadge>
      </div>

      {dominant && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="rounded-md bg-white px-2 py-1 font-mono text-xs font-medium text-slate-800 ring-1 ring-slate-200">
            Pattern: {dominant.pattern_type}
          </span>
          <StatusBadge tone={SEVERITY_TONE[dominant.severity]}>{humanize(dominant.severity)} severity</StatusBadge>
          <span className="text-xs text-slate-600 tabular-nums">
            rule confidence {Math.round(dominant.rule_confidence * 100)}%
          </span>
          {autopsy.pattern_detected ? (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-800">
              <CheckCircle2 className="size-3.5" aria-hidden="true" /> pattern detected
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-xs text-slate-500">
              <MinusCircle className="size-3.5" aria-hidden="true" /> no pattern forced
            </span>
          )}
        </div>
      )}

      {dominant && (
        <div className="mt-2">
          <p className="text-sm text-amber-900 italic">"{dominant.interpretation}"</p>
          <Evidence items={dominant.evidence} requestCode={autopsy.request_code} />
        </div>
      )}

      {autopsy.recommended_action && (
        <p className="mt-3 text-sm text-slate-800">
          <span className="font-medium">Recommended to consider: </span>
          <span className="font-mono">{autopsy.recommended_action}</span>
        </p>
      )}

      {autopsy.individual_failures.length > 0 && (
        <details className="mt-3 group">
          <summary className="cursor-pointer text-xs font-medium text-amber-800 select-none">
            Individual failures ({autopsy.individual_failures.length})
          </summary>
          <div className="mt-2 space-y-2">
            {autopsy.individual_failures.map((failure, index) => (
              <IndividualFailureRow key={`${failure.affected_donor}-${index}`} failure={failure} requestCode={autopsy.request_code} />
            ))}
          </div>
        </details>
      )}

      {autopsy.individual_failures.length === 0 && (
        <p className="mt-2 flex items-center gap-1.5 text-sm text-slate-600">
          <XCircle className="size-4 text-slate-400" aria-hidden="true" /> No failures recorded for this request.
        </p>
      )}

      <p className="mt-3 text-xs text-slate-600">
        Deterministic operational coordination analysis — not a medical diagnosis. The Failure Autopsy Engine
        recommends; it does not act. {autopsy.data_notice}
      </p>
    </div>
  );
}
