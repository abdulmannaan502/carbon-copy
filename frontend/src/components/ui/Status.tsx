import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

export type StatusTone = "ok" | "warning" | "critical" | "neutral" | "pending";

const DOT_TONES: Record<StatusTone, string> = {
  ok: "bg-emerald-500",
  warning: "bg-amber-500",
  critical: "bg-red-600",
  neutral: "bg-slate-400",
  pending: "bg-slate-300 animate-pulse",
};

const BADGE_TONES: Record<StatusTone, string> = {
  ok: "bg-emerald-50 text-emerald-800 ring-emerald-600/20",
  warning: "bg-amber-50 text-amber-800 ring-amber-600/25",
  critical: "bg-red-50 text-red-800 ring-red-600/20",
  neutral: "bg-slate-100 text-slate-700 ring-slate-500/20",
  pending: "bg-slate-100 text-slate-600 ring-slate-500/20",
};

export function StatusDot({ tone, className }: { tone: StatusTone; className?: string }) {
  return <span aria-hidden="true" className={cn("inline-block size-2.5 shrink-0 rounded-full", DOT_TONES[tone], className)} />;
}

export function StatusBadge({ tone, children }: { tone: StatusTone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-medium whitespace-nowrap ring-1 ring-inset",
        BADGE_TONES[tone],
      )}
    >
      <StatusDot tone={tone} />
      {children}
    </span>
  );
}
