import type { ReactNode } from "react";
import { cn } from "../../lib/cn";

interface MetricProps {
  label: string;
  value: ReactNode;
  hint?: string;
  size?: "md" | "lg";
  className?: string;
}

export function Metric({ label, value, hint, size = "md", className }: MetricProps) {
  return (
    <div className={className}>
      <dt className="text-xs font-medium tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd
        className={cn(
          "mt-1 font-semibold text-slate-900 tabular-nums",
          size === "lg" ? "text-3xl tracking-tight" : "text-xl",
        )}
      >
        {value}
      </dd>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}
