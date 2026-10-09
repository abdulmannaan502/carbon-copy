import { Compass, Scale, ShieldCheck } from "lucide-react";
import type { CandidateStrategy } from "../../types/matching";

// Strategy is a category, not a status, so it uses neutral styling with an icon rather than status colours.
const STRATEGY: Record<CandidateStrategy, { label: string; icon: typeof Compass }> = {
  RELIABLE: { label: "Reliable", icon: ShieldCheck },
  BALANCED: { label: "Balanced", icon: Scale },
  EXPLORATION: { label: "Exploration", icon: Compass },
};

export function StrategyBadge({ strategy }: { strategy: CandidateStrategy }) {
  const { label, icon: Icon } = STRATEGY[strategy];
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 py-0.5 text-xs font-medium whitespace-nowrap text-slate-700">
      <Icon className="size-3.5 text-slate-500" aria-hidden="true" />
      {label}
    </span>
  );
}

export const STRATEGY_LABELS: Record<CandidateStrategy, string> = {
  RELIABLE: "Reliable",
  BALANCED: "Balanced",
  EXPLORATION: "Exploration",
};
