import {
  Activity,
  ClipboardList,
  ListOrdered,
  Microscope,
  RotateCcw,
  Route,
  Split,
  TrendingUp,
  Users,
  type LucideIcon,
} from "lucide-react";
import { cn } from "../../lib/cn";
import { Card, CardBody, CardHeader } from "../ui/Card";

interface LoopStage {
  title: string;
  description: string;
  icon: LucideIcon;
  coreInnovation?: boolean;
}

const STAGES: LoopStage[] = [
  { title: "Patient Requirement", description: "A recurring transfusion need is registered.", icon: ClipboardList },
  { title: "Living Digital Twin", description: "A dynamic model of the patient's coordination needs.", icon: Activity },
  { title: "Donor State Intelligence", description: "Availability, eligibility, reliability and fatigue.", icon: Users },
  { title: "Adaptive Cascade", description: "Suitable donors are prioritised and contacted in sequence.", icon: ListOrdered },
  { title: "Outcome", description: "Success is recorded. Failure triggers an autopsy.", icon: Split },
  {
    title: "Failure Autopsy",
    description: "Why the attempt failed, captured as structured data.",
    icon: Microscope,
    coreInnovation: true,
  },
  {
    title: "Self-Healing Pathway",
    description: "An alternative coordination route is selected.",
    icon: Route,
    coreInnovation: true,
  },
  { title: "Learning", description: "Outcomes are analysed into advisory insights; nothing is applied automatically.", icon: TrendingUp },
];

export function CoordinationLoop() {
  return (
    <Card>
      <CardHeader
        title="Closed-loop coordination"
        description="When outreach fails, Carbon Copy adapts the pathway instead of restarting the search."
        action={
          <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium whitespace-nowrap text-slate-600">
            Architecture preview
          </span>
        }
      />
      <CardBody>
        <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {STAGES.map(({ title, description, icon: Icon, coreInnovation }, index) => (
            <li
              key={title}
              className={cn(
                "rounded-lg border p-4",
                coreInnovation ? "border-brand-200 bg-brand-50" : "border-slate-200 bg-slate-50/60",
              )}
            >
              <div className="flex items-center justify-between">
                <span
                  className={cn(
                    "grid size-9 place-items-center rounded-md",
                    coreInnovation ? "bg-brand-600 text-white" : "bg-white text-slate-700 ring-1 ring-slate-200",
                  )}
                >
                  <Icon className="size-[18px]" aria-hidden="true" />
                </span>
                <span className="font-mono text-xs text-slate-400 tabular-nums">
                  {String(index + 1).padStart(2, "0")}
                </span>
              </div>
              <h3 className="mt-3 text-sm font-semibold text-slate-900">{title}</h3>
              <p className="mt-1 text-sm leading-snug text-slate-600">{description}</p>
              {coreInnovation && (
                <p className="mt-2 text-xs font-medium tracking-wide text-brand-700 uppercase">Core innovation</p>
              )}
            </li>
          ))}
        </ol>
        <p className="mt-4 flex items-center gap-2 text-sm text-slate-500">
          <RotateCcw className="size-4" aria-hidden="true" />
          Learning insights are advisory: they are shown for review and do not change matching or recovery decisions.
        </p>
      </CardBody>
    </Card>
  );
}
