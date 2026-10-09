import { ArrowRight, CalendarClock } from "lucide-react";
import { Link } from "react-router";
import { formatDate, formatShortDate, humanize, plural } from "../../lib/format";
import type { RequirementState, TransfusionProfile } from "../../types/twin";
import { Card, CardBody, CardHeader } from "../ui/Card";
import { Metric } from "../ui/Metric";
import { StatusBadge } from "../ui/Status";
import { RECURRENCE_DISPLAY, REQUEST_STATUS_TONE } from "./display";

function expectedIn(days: number | null): string {
  if (days === null) return "Unknown";
  if (days === 0) return "Today";
  if (days < 0) return `${plural(-days, "day")} ago`;
  return plural(days, "day");
}

export function RequirementCard({ profile, requirement }: { profile: TransfusionProfile; requirement: RequirementState }) {
  const recurrence = RECURRENCE_DISPLAY[profile.recurrence_status];

  return (
    <Card className="flex flex-col">
      <CardHeader
        title="Requirement"
        description="Recurring cadence and the current request"
        action={<CalendarClock className="size-4 text-slate-400" aria-hidden="true" />}
      />
      <CardBody className="flex flex-1 flex-col gap-5">
        <div className="flex items-end justify-between gap-4">
          <Metric
            size="lg"
            label="Expected requirement"
            value={expectedIn(profile.days_until_expected_requirement)}
            hint={profile.next_expected_requirement ? formatDate(profile.next_expected_requirement) : undefined}
          />
          <StatusBadge tone={recurrence.tone}>{recurrence.label}</StatusBadge>
        </div>

        <dl className="grid grid-cols-3 gap-4 border-t border-slate-100 pt-4">
          <Metric
            label="Frequency"
            value={profile.transfusion_frequency_days ? `${profile.transfusion_frequency_days} days` : "—"}
          />
          <Metric label="Units" value={requirement.units_required ?? "—"} />
          <Metric label="Urgency" value={requirement.request_urgency ? humanize(requirement.request_urgency) : "—"} />
        </dl>

        <div className="mt-auto rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
          {requirement.current_request_code ? (
            <>
              <div className="flex items-center justify-between gap-3">
                <span className="font-mono text-sm font-medium text-slate-900">{requirement.current_request_code}</span>
                {requirement.request_status && (
                  <StatusBadge tone={REQUEST_STATUS_TONE[requirement.request_status]}>
                    {humanize(requirement.request_status)}
                  </StatusBadge>
                )}
              </div>
              <p className="mt-2 text-sm text-slate-600">
                {requirement.requirement_covered
                  ? `Donor confirmed for ${formatShortDate(requirement.required_by)}.`
                  : `Active request, required by ${formatShortDate(requirement.required_by)}.`}{" "}
                {plural(requirement.attempts_made, "attempt")}
                {requirement.failed_attempts > 0 && `, ${requirement.failed_attempts} unsuccessful`}.
                {requirement.pending_recovery_action &&
                  ` Recovery in progress: ${humanize(requirement.pending_recovery_action).toLowerCase()}.`}
              </p>
            </>
          ) : (
            <p className="text-sm text-slate-600">No request raised yet for the next requirement.</p>
          )}
          <p className="mt-1 text-xs text-slate-500">Last transfusion {formatDate(profile.last_transfusion_date)}</p>
          {requirement.current_request_code && (
            <Link
              to={`/requests/${requirement.current_request_code}/matching`}
              className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline"
            >
              Candidate matching <ArrowRight className="size-3.5" aria-hidden="true" />
            </Link>
          )}
        </div>
      </CardBody>
    </Card>
  );
}
