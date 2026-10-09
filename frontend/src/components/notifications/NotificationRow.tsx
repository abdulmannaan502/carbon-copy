import { ChevronDown, ChevronRight, CircleDot, Loader2 } from "lucide-react";
import { cn } from "../../lib/cn";
import { formatDateTime, humanize } from "../../lib/format";
import type { NotificationItem, NotificationStatus } from "../../types/notifications";

const STATUS_CLASS: Record<NotificationStatus, string> = {
  SIMULATED: "bg-sky-50 text-sky-800 ring-sky-600/20",
  QUEUED: "bg-slate-100 text-slate-700 ring-slate-500/20",
  SENT: "bg-emerald-50 text-emerald-800 ring-emerald-600/20",
  DELIVERED: "bg-emerald-50 text-emerald-800 ring-emerald-600/20",
  FAILED: "bg-red-50 text-red-800 ring-red-600/20",
  UNCERTAIN: "bg-amber-50 text-amber-900 ring-amber-600/30",
  CANCELLED: "bg-slate-100 text-slate-600 ring-slate-500/20",
};

export function Chip({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset", className)}>
      {children}
    </span>
  );
}

/** Only in-app notifications have a read state; SMS/WhatsApp records are never "unread". */
export const isUnread = (item: NotificationItem) => item.channel === "IN_APP" && !item.read && item.status !== "CANCELLED";

/** The API value, plus "(simulated)" for a demo channel so it never reads as a real SMS or WhatsApp message. */
const channelLabel = (item: NotificationItem) =>
  `${item.channel === "IN_APP" ? "In-app" : humanize(item.channel).toUpperCase()}${item.mode === "DEMO" ? " (simulated)" : ""}`;

interface Props {
  item: NotificationItem;
  expanded: boolean;
  onToggle: () => void;
  onMarkRead: () => void;
  marking: boolean;
  markError: string | null;
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className="mt-0.5 text-sm break-words text-slate-800">{children}</dd>
    </div>
  );
}

export function NotificationRow({ item, expanded, onToggle, onMarkRead, marking, markError }: Props) {
  const unread = isUnread(item);
  const panelId = `notification-${item.notification_id}`;
  return (
    <li className={cn("border-l-4", unread ? "border-l-brand-600 bg-white" : "border-l-transparent bg-slate-50/60")}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={panelId}
        className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-slate-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-600 sm:px-5"
      >
        <span className="mt-1 shrink-0 text-slate-400" aria-hidden="true">
          {expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-start gap-2">
            {unread && <CircleDot className="mt-0.5 size-4 shrink-0 text-brand-600" aria-hidden="true" />}
            <span className={cn("text-sm text-slate-900", unread ? "font-semibold" : "font-medium")}>
              {unread && <span className="sr-only">Unread: </span>}
              {item.title}
            </span>
          </span>
          <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Chip className={STATUS_CLASS[item.status]}>{item.status}</Chip>
            <Chip className={item.mode === "LIVE" ? "bg-rose-50 text-rose-800 ring-rose-600/25" : "bg-amber-50 text-amber-800 ring-amber-600/25"}>{item.mode}</Chip>
            <Chip className="bg-white text-slate-700 ring-slate-500/25">{humanize(item.event_type)}</Chip>
            <Chip className="bg-white text-slate-700 ring-slate-500/25">To {item.recipient_role.toLowerCase()}</Chip>
            <Chip className="bg-white text-slate-700 ring-slate-500/25">{channelLabel(item)}</Chip>
          </span>
          <span className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-slate-500 tabular-nums">
            {item.blood_request_code && <span className="font-mono">{item.blood_request_code}</span>}
            <span>{formatDateTime(item.created_at)} UTC</span>
            {item.channel === "IN_APP" && <span>{item.read ? "Read" : "Unread"}</span>}
          </span>
        </span>
      </button>

      {expanded && (
        <div id={panelId} className="border-t border-slate-100 bg-white px-4 py-4 sm:pl-12">
          <h3 className="text-sm font-semibold text-slate-900">{item.title}</h3>
          <p className="mt-1.5 text-sm text-slate-700">{item.body}</p>
          <p className="mt-3 rounded-md bg-sky-50 px-3 py-2 text-sm text-sky-900">
            <span className="font-semibold">What this status means: </span>
            {item.delivery_note}
            {item.mode === "DEMO" && " No real SMS, WhatsApp message or phone notification was sent."}
          </p>
          <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Detail label="Notification">
              <span className="font-mono">{item.notification_id}</span>
            </Detail>
            <Detail label="Recipient">
              {humanize(item.recipient_role)}
              {item.recipient_ref && <span className="font-mono"> · {item.recipient_ref}</span>}
            </Detail>
            <Detail label="Request">{item.blood_request_code ? <span className="font-mono">{item.blood_request_code}</span> : "—"}</Detail>
            <Detail label="Created">{formatDateTime(item.created_at)} UTC</Detail>
            <Detail label="Last updated">{formatDateTime(item.updated_at)} UTC</Detail>
            {item.channel === "IN_APP" && <Detail label="Read at">{item.read_at ? `${formatDateTime(item.read_at)} UTC` : "Not read yet"}</Detail>}
            {item.provider_message_id && (
              <Detail label="Provider message id">
                <span className="font-mono">{item.provider_message_id}</span>
              </Detail>
            )}
            {(item.failure_code || item.failure_message) && (
              <Detail label="Failure">
                {item.failure_code && <span className="font-mono">{item.failure_code}</span>} {item.failure_message}
              </Detail>
            )}
            {item.idempotency_key && (
              <Detail label="Idempotency key">
                <span className="font-mono text-xs">{item.idempotency_key}</span>
              </Detail>
            )}
          </dl>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            {item.channel === "IN_APP" && item.status !== "CANCELLED" && !item.read && (
              <button
                type="button"
                onClick={onMarkRead}
                disabled={marking}
                className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {marking && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
                {marking ? "Marking as read…" : "Mark as read"}
              </button>
            )}
            {item.channel !== "IN_APP" && <p className="text-xs text-slate-500">Only in-app notifications have a read state.</p>}
            {markError && (
              <p role="alert" className="text-sm text-red-700">
                {markError}
              </p>
            )}
          </div>
        </div>
      )}
    </li>
  );
}
