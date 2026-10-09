import { MapPin, Users } from "lucide-react";
import { formatBloodGroup, formatDateTime } from "../../lib/format";
import type { DonorStateAssessment } from "../../types/donorState";
import { Card } from "../ui/Card";
import { StatusBadge } from "../ui/Status";
import { PRIORITY_DISPLAY } from "./display";

interface Props {
  state: DonorStateAssessment;
  /** Shown under the priority score, e.g. "for DEMO-REQUEST-001". */
  priorityContext: string;
}

export function DonorStateHeader({ state, priorityContext }: Props) {
  const { donor, priority } = state;
  const band = PRIORITY_DISPLAY[priority.priority_band];

  return (
    <Card>
      <div className="flex flex-col gap-6 px-6 py-6 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold tracking-[0.2em] text-brand-600">DONOR STATE INTELLIGENCE</p>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
            <h1 className="text-3xl font-semibold tracking-tight text-slate-900 sm:text-4xl">{donor.display_name}</h1>
            <span className="grid h-10 min-w-12 place-items-center rounded-lg bg-brand-600 px-2.5 text-lg font-semibold text-white">
              {formatBloodGroup(donor.blood_group)}
            </span>
            {!donor.active && <StatusBadge tone="neutral">Inactive record</StatusBadge>}
          </div>
          <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm text-slate-600">
            <div>
              <dt className="sr-only">Donor code</dt>
              <dd className="font-mono text-slate-800">{donor.donor_code}</dd>
            </div>
            <div className="flex items-center gap-1.5">
              <MapPin className="size-4 text-slate-400" aria-hidden="true" />
              <dt className="sr-only">Location</dt>
              <dd>
                {donor.city}, {donor.state}
              </dd>
            </div>
            {donor.bridge_group_code && (
              <div className="flex items-center gap-1.5">
                <Users className="size-4 text-slate-400" aria-hidden="true" />
                <dt className="sr-only">Bridge group</dt>
                <dd>Bridge group {donor.bridge_group_code}</dd>
              </div>
            )}
          </dl>
        </div>

        <div className="flex shrink-0 flex-col gap-2 lg:items-end">
          <span className="text-xs font-medium tracking-wide text-slate-500 uppercase">Operational priority</span>
          <div className="flex items-baseline gap-3">
            <span className="text-5xl font-semibold tracking-tight text-slate-900 tabular-nums">
              {priority.priority_score}
            </span>
            <span className="text-lg text-slate-400">/ 100</span>
          </div>
          <StatusBadge tone={band.tone}>{band.label} priority</StatusBadge>
          <p className="text-xs text-slate-500 lg:text-right">{priorityContext}</p>
          <p className="text-xs text-slate-400 tabular-nums lg:text-right">
            Assessed as of {formatDateTime(state.assessed_at)} UTC
            {state.evaluation_point === "REQUEST_START" ? " · request start" : ""}
          </p>
        </div>
      </div>
    </Card>
  );
}
