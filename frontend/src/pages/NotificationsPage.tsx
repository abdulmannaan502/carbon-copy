import { Bell, ChevronLeft, ChevronRight, Loader2, RefreshCw, ShieldAlert } from "lucide-react";
import { useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { NotificationRow } from "../components/notifications/NotificationRow";
import { SimulationPanel } from "../components/notifications/SimulationPanel";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { Metric } from "../components/ui/Metric";
import { useApiQuery, type QueryState } from "../hooks/useApiQuery";
import { plural } from "../lib/format";
import { ApiError } from "../services/apiClient";
import { notificationService } from "../services/notificationService";
import type {
  NotificationChannel,
  NotificationFilters,
  NotificationRecipientRole,
  NotificationStatus,
  NotificationSummary,
} from "../types/notifications";

const PAGE_SIZE = 10;
const ROLES: NotificationRecipientRole[] = ["DONOR", "PATIENT", "COORDINATOR", "SYSTEM"];
const STATUSES: NotificationStatus[] = ["QUEUED", "SIMULATED", "SENT", "DELIVERED", "FAILED", "UNCERTAIN", "CANCELLED"];
const CHANNELS: NotificationChannel[] = ["IN_APP", "SMS", "WHATSAPP"];

const pick = <T extends string>(value: string | null, allowed: readonly T[]): T | "" =>
  allowed.includes(value as T) ? (value as T) : "";

function readFilters(params: URLSearchParams): NotificationFilters {
  return {
    recipientRole: pick(params.get("role"), ROLES),
    status: pick(params.get("status"), STATUSES),
    channel: pick(params.get("channel"), CHANNELS),
    requestCode: (params.get("request") ?? "").slice(0, 24),
    unreadOnly: params.get("unread") === "1",
  };
}

/** Keeps showing the last good data while a refresh is in flight, so the page does not blank out. */
function useLatest<T>(state: QueryState<T>): T | null {
  const last = useRef<T | null>(null);
  if (state.status === "success") last.current = state.data;
  return last.current;
}

const errorText = (error: ApiError) => error.detail ?? error.message;

function SummaryCards({ summary }: { summary: NotificationSummary }) {
  // Derived only from the backend's status counts; nothing is hardcoded.
  const live = summary.by_mode.LIVE > 0;
  return (
    <dl className="grid grid-cols-2 gap-3 lg:grid-cols-6" aria-label="Notification summary">
      <Card className="px-4 py-3">
        <Metric label="Total" value={summary.total} hint="All notification records" />
      </Card>
      <Card className="px-4 py-3">
        <Metric label="Unread" value={summary.unread_in_app} hint="In-app only" />
      </Card>
      <Card className="px-4 py-3">
        <Metric label="Simulated" value={summary.by_status.SIMULATED} hint="Recorded, not sent" />
      </Card>
      <Card className="px-4 py-3">
        <Metric label="Queued" value={summary.by_status.QUEUED} hint="Waiting, not sent" />
      </Card>
      <Card className="px-4 py-3">
        <Metric
          label="Sent (accepted)"
          value={summary.by_status.SENT}
          hint={live ? "Provider accepted; not a delivery confirmation" : "Demo mode: nothing is sent"}
        />
      </Card>
      <Card className="px-4 py-3">
        <Metric
          label="Delivered"
          value={summary.by_status.DELIVERED}
          hint={live ? "Only with trusted provider evidence" : "Demo mode: nothing is delivered"}
        />
      </Card>
    </dl>
  );
}

export function NotificationsPage() {
  const [params, setParams] = useSearchParams();
  const filters = readFilters(params);
  const page = Math.max(1, Number(params.get("page")) || 1);
  const [refreshToken, setRefreshToken] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [marking, setMarking] = useState<string | null>(null);
  const [markError, setMarkError] = useState<{ id: string; message: string } | null>(null);
  const refresh = () => setRefreshToken((n) => n + 1);

  const listKey = `${JSON.stringify(filters)}:${page}:${refreshToken}`;
  const list = useApiQuery((signal) => notificationService.list(filters, page, PAGE_SIZE, signal), `notifications:list:${listKey}`);
  const summary = useApiQuery((signal) => notificationService.summary(EMPTY_FILTERS, signal), `notifications:summary:${refreshToken}`);
  const lastList = useLatest(list);
  const lastSummary = useLatest(summary);

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
    setExpanded(null);
  };
  const hasFilters = Boolean(filters.recipientRole || filters.status || filters.channel || filters.requestCode || filters.unreadOnly);

  const markRead = async (id: string) => {
    setMarking(id);
    setMarkError(null);
    try {
      await notificationService.markRead(id);
      refresh(); // reconcile the list and the summary with what the backend now says
    } catch (error) {
      setMarkError({ id, message: error instanceof ApiError ? errorText(error) : "Could not mark the notification as read." });
    } finally {
      setMarking(null);
    }
  };

  const select = "rounded-md border border-slate-300 bg-white py-1.5 pr-8 pl-2.5 text-sm text-slate-900";
  const refreshing = list.status === "loading" && lastList !== null;
  const pages = lastList?.pages ?? 0;

  return (
    <div className="space-y-6">
      <Card>
        <div className="flex flex-col gap-4 px-6 py-6 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-semibold tracking-[0.2em] text-brand-600">NOTIFICATION CENTER</p>
            <h1 className="mt-3 flex items-center gap-3 text-2xl font-semibold tracking-tight text-slate-900">
              <Bell className="size-6 text-slate-500" aria-hidden="true" /> Notifications
            </h1>
            <p className="mt-2 max-w-3xl text-sm text-slate-600">
              Messages the coordination system would send to donors, patients and coordinators, as recorded by the demo messaging provider.
            </p>
          </div>
          <button
            type="button"
            onClick={refresh}
            disabled={refreshing}
            className="inline-flex shrink-0 items-center gap-2 self-start rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          >
            <RefreshCw className={`size-4 ${refreshing ? "animate-spin" : ""}`} aria-hidden="true" /> Refresh
          </button>
        </div>
      </Card>

      <div role="note" className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900">
        <ShieldAlert className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
        <p>
          <span className="font-semibold">Synthetic demonstration data — not for clinical use.</span> DEMO notifications are{" "}
          <span className="font-semibold">records with status SIMULATED</span>: no real SMS, WhatsApp message or phone notification was
          sent for them, and a successful request to this application is not evidence of delivery.
          {lastSummary && lastSummary.by_mode.LIVE > 0 && (
            <>
              {" "}
              <span className="font-semibold">
                {lastSummary.by_mode.LIVE} LIVE record{lastSummary.by_mode.LIVE === 1 ? "" : "s"} exist{lastSummary.by_mode.LIVE === 1 ? "s" : ""}:
              </span>{" "}
              SENT means the SMS provider accepted the request, not that the message reached a phone; UNCERTAIN means the outcome is unknown
              and it was not resent.
            </>
          )}
        </p>
      </div>

      {summary.status === "error" && lastSummary === null ? (
        <p role="alert" className="rounded-xl border border-red-200 bg-red-50 px-5 py-3 text-sm text-red-800">
          Summary unavailable: {errorText(summary.error)}
        </p>
      ) : lastSummary ? (
        <SummaryCards summary={lastSummary} />
      ) : (
        <p className="text-sm text-slate-500">Loading summary…</p>
      )}

      <SimulationPanel onRecorded={refresh} />

      <Card>
        <CardHeader
          title="Inbox"
          description={lastList ? `${plural(lastList.total, "notification")}${hasFilters ? " match the filters" : ""}` : "Loading notifications…"}
        />
        <CardBody className="space-y-4">
          <form className="flex flex-wrap items-end gap-x-5 gap-y-3" aria-label="Filters" onSubmit={(e) => e.preventDefault()}>
            <label className="flex flex-col gap-1 text-xs text-slate-500">
              Recipient role
              <select value={filters.recipientRole} onChange={(e) => setParam("role", e.target.value)} className={select}>
                <option value="">All roles</option>
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r.charAt(0) + r.slice(1).toLowerCase()}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-500">
              Status
              <select value={filters.status} onChange={(e) => setParam("status", e.target.value)} className={select}>
                <option value="">All statuses</option>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-500">
              Channel
              <select value={filters.channel} onChange={(e) => setParam("channel", e.target.value)} className={select}>
                <option value="">All channels</option>
                {CHANNELS.map((c) => (
                  <option key={c} value={c}>
                    {c === "IN_APP" ? "In-app" : c}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-500">
              Request code
              <input
                key={filters.requestCode}
                defaultValue={filters.requestCode}
                maxLength={24}
                placeholder="e.g. DEMO-REQUEST-001"
                onBlur={(e) => e.target.value.trim() !== filters.requestCode && setParam("request", e.target.value.trim())}
                onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
                className="w-52 rounded-md border border-slate-300 px-2.5 py-1.5 font-mono text-sm text-slate-900"
              />
            </label>
            <label className="flex items-center gap-2 pb-2 text-sm text-slate-700">
              <input type="checkbox" checked={filters.unreadOnly} onChange={(e) => setParam("unread", e.target.checked ? "1" : "")} className="size-4" />
              Unread only
            </label>
            {hasFilters && (
              <button type="button" onClick={() => { setParams(new URLSearchParams()); setExpanded(null); }} className="pb-2 text-sm font-medium text-brand-700 hover:underline">
                Reset filters
              </button>
            )}
          </form>

          <div aria-live="polite" className="min-h-6">
            {refreshing && (
              <p className="flex items-center gap-2 text-xs text-slate-500">
                <Loader2 className="size-3.5 animate-spin" aria-hidden="true" /> Updating…
              </p>
            )}
          </div>

          {list.status === "error" && (
            <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-800">
              <p className="font-medium">Notifications could not be loaded.</p>
              <p className="mt-1">{errorText(list.error)}</p>
              <button type="button" onClick={refresh} className="mt-3 rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-800 hover:bg-red-100">
                Retry
              </button>
            </div>
          )}
          {list.status === "loading" && lastList === null && <p className="py-10 text-center text-sm text-slate-500">Loading notifications…</p>}

          {lastList && list.status !== "error" && (
            lastList.items.length === 0 ? (
              <div className="rounded-lg border border-dashed border-slate-300 px-4 py-10 text-center text-sm text-slate-600">
                <p className="font-medium text-slate-800">{hasFilters ? "No notifications match these filters." : "There are no notifications yet."}</p>
                <p className="mt-1">
                  {hasFilters
                    ? "Try different filters or reset them."
                    : "Use the demo action above to run a simulation and record simulated notifications."}
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-slate-200 overflow-hidden rounded-lg border border-slate-200" aria-label="Notifications">
                {lastList.items.map((item) => (
                  <NotificationRow
                    key={item.notification_id}
                    item={item}
                    expanded={expanded === item.notification_id}
                    onToggle={() => setExpanded(expanded === item.notification_id ? null : item.notification_id)}
                    onMarkRead={() => void markRead(item.notification_id)}
                    marking={marking === item.notification_id}
                    markError={markError?.id === item.notification_id ? markError.message : null}
                  />
                ))}
              </ul>
            )
          )}

          {lastList && lastList.total > 0 && (
            <nav aria-label="Pagination" className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-600">
              <span className="tabular-nums">
                Page {lastList.page} of {Math.max(pages, 1)} · {plural(lastList.total, "notification")}
              </span>
              <span className="flex gap-2">
                <button
                  type="button"
                  disabled={page <= 1 || refreshing}
                  onClick={() => setParam("page", String(page - 1))}
                  className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  <ChevronLeft className="size-4" aria-hidden="true" /> Previous
                </button>
                <button
                  type="button"
                  disabled={page >= pages || refreshing}
                  onClick={() => setParam("page", String(page + 1))}
                  className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  Next <ChevronRight className="size-4" aria-hidden="true" />
                </button>
              </span>
            </nav>
          )}
        </CardBody>
      </Card>

      <p className="text-center text-xs text-slate-500">
        Synthetic demonstration data — not for clinical use. Demo-only: this prototype has no authentication, and nothing here is sent
        to a real recipient.
      </p>
    </div>
  );
}

const EMPTY_FILTERS: NotificationFilters = { recipientRole: "", status: "", channel: "", requestCode: "", unreadOnly: false };
