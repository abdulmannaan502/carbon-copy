import { ArrowDown, Route, XCircle } from "lucide-react";
import { humanize } from "../../lib/format";
import type { CascadeWave, HealingDecision } from "../../types/cascade";
import type { RequestAutopsy } from "../../types/failureAutopsy";
import type { RecoveryPlan } from "../../types/selfHealing";
import { FailureAutopsyPanel } from "./FailureAutopsyPanel";
import { SelfHealingPanel } from "./SelfHealingPanel";

const CHANNEL_LABEL: Record<string, string> = { SIMULATED_CALL: "CALL", SIMULATED_SMS: "SMS", SIMULATED_APP: "APP" };

function Step() {
  return <ArrowDown className="size-5 text-slate-300" aria-hidden="true" />;
}

/** "CALL · 4 donors" — what the next wave looks like once the plan is applied. */
function nextWaveLabel(next: CascadeWave | null, healing: HealingDecision): string {
  if (next) {
    const channels = [...new Set(next.contacts.map((c) => CHANNEL_LABEL[c.channel] ?? c.channel))];
    return `${channels.join(" + ")} · ${next.wave_size} donors`;
  }
  const channel = healing.channel_override ? `${CHANNEL_LABEL[healing.channel_override]} · ` : "";
  return `${channel}${healing.next_wave_size ?? "?"} donors`;
}

interface Props {
  failureAutopsy: RequestAutopsy | null;
  healing: HealingDecision;
  plan: RecoveryPlan | null;
  nextWave: CascadeWave | null;
  terminal?: boolean;
}

/**
 * Between two waves, as four visibly separate steps:
 *   FAILURE → FAILURE AUTOPSY ("What happened?", recommends only)
 *           → SELF-HEALING ("What should change?", decides) → ACTION → NEXT WAVE.
 * Failure Autopsy explains; Self-Healing decides; the cascade applies the plan.
 */
export function HealingConnector({ failureAutopsy, healing, plan, nextWave, terminal }: Props) {
  return (
    <div className="relative mx-auto flex max-w-3xl flex-col items-center gap-3 py-2">
      <Step />
      <p className="flex items-center gap-2 text-sm font-semibold text-red-700">
        <XCircle className="size-4" aria-hidden="true" /> Failure — the requirement is still open
      </p>
      <Step />

      {failureAutopsy && (
        <div className="w-full">
          <p className="mb-1 text-xs text-slate-500">
            <span aria-hidden="true">🔍</span> Failure Autopsy — "What happened?"
          </p>
          <FailureAutopsyPanel autopsy={failureAutopsy} />
        </div>
      )}

      <Step />

      {plan ? (
        <div className="w-full">
          <p className="mb-1 text-xs text-slate-500">
            <span aria-hidden="true">🧠</span> Self-Healing — "What should change?"
          </p>
          <SelfHealingPanel plan={plan} />
        </div>
      ) : (
        <div className="w-full rounded-xl border border-brand-200 bg-brand-50 px-4 py-3">
          <p className="flex items-center gap-2 text-xs font-semibold tracking-wide text-brand-700 uppercase">
            <Route className="size-4" aria-hidden="true" /> Self-healing · {humanize(healing.action)}
          </p>
          <p className="mt-1.5 text-sm text-slate-800">{healing.rationale}</p>
        </div>
      )}

      {!terminal && (
        <>
          <Step />
          <p className="text-sm font-semibold text-brand-700">
            Action: {plan ? humanize(plan.primary_action) : humanize(healing.action)}
          </p>
          <Step />
          <p className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm text-slate-800">
            <span className="text-xs font-semibold tracking-wide text-slate-500 uppercase">Next wave</span>{" "}
            <span className="font-semibold">{nextWaveLabel(nextWave, healing)}</span>
          </p>
          <Step />
        </>
      )}
    </div>
  );
}
