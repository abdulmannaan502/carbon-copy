import {
  CheckCircle2,
  Circle,
  Clock,
  FilePlus2,
  Megaphone,
  PhoneOutgoing,
  Route,
  SearchX,
  ShieldCheck,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { Fragment } from "react";
import { Link } from "react-router";
import { cn } from "../../lib/cn";
import { formatDateTime } from "../../lib/format";
import type { RecentActivity, TimelineEventKind, TimelineTone } from "../../types/twin";
import { Card, CardBody, CardHeader } from "../ui/Card";

const KIND_ICONS: Record<TimelineEventKind, LucideIcon> = {
  REQUEST_CREATED: FilePlus2,
  AVAILABILITY_CHECKS: Megaphone,
  DONOR_CONTACTED: PhoneOutgoing,
  DONOR_ACCEPTED: CheckCircle2,
  ATTEMPT_FAILED: XCircle,
  FAILURE_DETECTED: SearchX,
  RECOVERY_INITIATED: Route,
  AWAITING_RESPONSE: Clock,
  REQUEST_FULFILLED: ShieldCheck,
  REQUEST_CANCELLED: Circle,
};

const TONE_STYLES: Record<TimelineTone, string> = {
  NEUTRAL: "bg-white text-slate-600 ring-slate-200",
  POSITIVE: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  NEGATIVE: "bg-amber-50 text-amber-700 ring-amber-200",
  PENDING: "bg-slate-50 text-slate-500 ring-slate-300",
};

/** Turns donor codes in a timeline title into links to that donor's state for the request. */
function linkDonorCodes(text: string, requestCode: string | null) {
  return text.split(/(DON-\d{5})/).map((part, index) =>
    /^DON-\d{5}$/.test(part) ? (
      <Link
        key={index}
        to={`/donors/${part}${requestCode ? `?request=${requestCode}` : ""}`}
        className="font-mono underline decoration-slate-300 underline-offset-2 hover:decoration-slate-500"
      >
        {part}
      </Link>
    ) : (
      <Fragment key={index}>{part}</Fragment>
    ),
  );
}

export function ActivityTimeline({ activity }: { activity: RecentActivity }) {
  return (
    <Card>
      <CardHeader
        title="Recent activity"
        description={
          activity.focus_request_code
            ? `Coordination timeline for ${activity.focus_request_code}`
            : "No coordination activity recorded"
        }
      />
      <CardBody>
        <dl className="mb-5 flex flex-wrap gap-x-6 gap-y-1 text-sm text-slate-600">
          <div className="flex gap-1.5">
            <dt>Interactions</dt>
            <dd className="font-medium text-slate-900 tabular-nums">{activity.recent_interaction_count}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt>Successes</dt>
            <dd className="font-medium text-slate-900 tabular-nums">{activity.recent_success_count}</dd>
          </div>
          <div className="flex gap-1.5">
            <dt>Failures</dt>
            <dd className="font-medium text-slate-900 tabular-nums">{activity.recent_failure_count}</dd>
          </div>
          <span className="text-slate-400">last {activity.window_days} days</span>
        </dl>

        {activity.timeline.length === 0 ? (
          <p className="text-sm text-slate-500">No events to show.</p>
        ) : (
          <ol className="relative">
            {activity.timeline.map((event, index) => {
              const Icon = KIND_ICONS[event.kind];
              const last = index === activity.timeline.length - 1;
              return (
                <li key={`${event.at}-${index}`} className="relative flex gap-4 pb-5 last:pb-0">
                  {!last && <span className="absolute top-9 bottom-0 left-[17px] w-px bg-slate-200" aria-hidden="true" />}
                  <span
                    className={cn(
                      "relative z-10 grid size-9 shrink-0 place-items-center rounded-full ring-1",
                      TONE_STYLES[event.tone],
                    )}
                  >
                    <Icon className="size-4" aria-hidden="true" />
                  </span>
                  <div className="min-w-0 pt-1.5">
                    <div className="flex flex-wrap items-baseline gap-x-3">
                      <p className="text-sm font-medium text-slate-900">
                        {linkDonorCodes(event.title, activity.focus_request_code)}
                      </p>
                      <time className="text-xs text-slate-500 tabular-nums" dateTime={`${event.at}Z`}>
                        {formatDateTime(event.at)}
                      </time>
                    </div>
                    {event.detail && <p className="mt-0.5 text-sm text-slate-600">{event.detail}</p>}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
        <p className="mt-5 text-xs text-slate-400">Times in UTC. All outreach is simulated.</p>
      </CardBody>
    </Card>
  );
}
