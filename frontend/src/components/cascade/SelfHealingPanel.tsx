import { Brain, UserRound } from "lucide-react";
import { humanize } from "../../lib/format";
import type { RecoveryPlan } from "../../types/selfHealing";
import { StatusBadge } from "../ui/Status";

const CHANNEL_LABEL: Record<string, string> = { SIMULATED_CALL: "CALL", SIMULATED_SMS: "SMS", SIMULATED_APP: "APP" };

/** The settings the plan actually changes, in plain words (only applicable changes are listed). */
export function describeChanges(plan: RecoveryPlan): string[] {
  const { changes } = plan;
  const items: string[] = [];
  if (changes.channel) items.push(`Next wave will use ${CHANNEL_LABEL[changes.channel] ?? changes.channel}.`);
  if (changes.wave_size !== null) items.push(`Wave size ${plan.current_state.wave_size} → ${changes.wave_size}.`);
  if (changes.radius_label) items.push(`Search radius ${plan.current_state.radius_label} → ${changes.radius_label}.`);
  if (changes.bridge_priority === "BRIDGE_FIRST") items.push("Bridge-group donors are contacted first.");
  if (changes.bridge_priority === "NON_BRIDGE_FIRST") items.push("Donors outside the bridge group are contacted first.");
  if (items.length === 0 && !plan.requires_human_intervention) items.push("Matching is re-run without the donors already contacted.");
  return items;
}

/**
 * SELF-HEALING: "What should change?" — the decision, kept visibly separate from the Failure Autopsy
 * ("What happened?") above it. Shows the primary action, why, evidence, the exact changes, the expected
 * effect (never a promise), fallbacks and whether a person must take over.
 */
export function SelfHealingPanel({ plan }: { plan: RecoveryPlan }) {
  const human = plan.requires_human_intervention;
  const tone = human ? "border-red-200 bg-red-50" : "border-sky-200 bg-sky-50";
  return (
    <div className={`w-full rounded-xl border px-4 py-3 ${tone}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className={`flex items-center gap-2 text-xs font-semibold tracking-wide uppercase ${human ? "text-red-800" : "text-sky-800"}`}>
          <Brain className="size-4" aria-hidden="true" /> Self-healing decision
        </p>
        <StatusBadge tone={human ? "critical" : "ok"}>
          {human ? "Human intervention required" : "Automatic recovery available"}
        </StatusBadge>
      </div>
      <p className="mt-1 text-xs text-slate-600 italic">"What should change?" — decided by the Self-Healing Engine from the autopsy and the cascade state.</p>

      <dl className="mt-3 space-y-2.5 text-sm text-slate-800">
        <div>
          <dt className="text-xs font-semibold tracking-wide text-slate-500 uppercase">Primary action</dt>
          <dd className="font-semibold">
            {humanize(plan.primary_action)}{" "}
            <span className="font-normal text-slate-500">
              · rule {plan.rule_id} {plan.rule_name.toLowerCase()} · rule strength {plan.rule_strength.toFixed(2)}
            </span>
          </dd>
          {plan.autopsy_recommended && plan.autopsy_recommended !== plan.primary_action && (
            <dd className="text-xs text-slate-600">The autopsy recommended {humanize(plan.autopsy_recommended).toLowerCase()}; this engine decided independently.</dd>
          )}
        </div>
        <div>
          <dt className="text-xs font-semibold tracking-wide text-slate-500 uppercase">Why</dt>
          <dd>{plan.reason}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold tracking-wide text-slate-500 uppercase">Evidence</dt>
          <dd>
            <ul className="mt-0.5 space-y-0.5">
              {plan.evidence.map((item) => (
                <li key={item} className="flex gap-2">
                  <span className="mt-2 size-1 shrink-0 rounded-full bg-slate-400" aria-hidden="true" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold tracking-wide text-slate-500 uppercase">What will change</dt>
          <dd>{human ? "Nothing automatic: outreach stops here." : describeChanges(plan).join(" ")}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold tracking-wide text-slate-500 uppercase">Expected effect</dt>
          <dd>{plan.expected_effect}</dd>
        </div>
        {plan.fallback_actions.length > 0 && (
          <div>
            <dt className="text-xs font-semibold tracking-wide text-slate-500 uppercase">Fallback</dt>
            <dd>{plan.fallback_actions.map((a) => humanize(a)).join(" → ")}</dd>
          </div>
        )}
      </dl>

      {plan.escalation && (
        <div className="mt-3 rounded-lg border border-red-200 bg-white px-3 py-2.5 text-sm text-slate-800">
          <p className="flex items-center gap-2 font-semibold text-red-800">
            <UserRound className="size-4" aria-hidden="true" /> Automation stopped — {humanize(plan.escalation.escalation_type)}
          </p>
          <p className="mt-1">{plan.escalation.why_automation_stopped}</p>
          <p className="mt-1 text-slate-600">
            Attempted: {plan.escalation.actions_attempted.map((a) => humanize(a)).join(", ")} ·{" "}
            {plan.escalation.donors_contacted} donors contacted ·{" "}
            {Object.entries(plan.escalation.failures).map(([k, v]) => `${v} ${humanize(k).toLowerCase()}`).join(", ") || "no failures recorded"}
          </p>
          <p className="mt-1 font-medium">Recommended human action: {plan.escalation.recommended_human_action}</p>
        </div>
      )}
      <p className="mt-2 text-[11px] text-slate-500">{plan.notice}</p>
    </div>
  );
}
