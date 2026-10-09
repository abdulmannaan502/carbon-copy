import { Cpu, Database, FlaskConical, RefreshCw, Server, type LucideIcon } from "lucide-react";
import type { SystemHealth } from "../../hooks/useSystemHealth";
import { config } from "../../lib/config";
import { Card, CardBody, CardHeader } from "../ui/Card";
import { StatusBadge, StatusDot, type StatusTone } from "../ui/Status";
import { CONNECTION_DISPLAY } from "./connectionDisplay";

interface StatusRowProps {
  icon: LucideIcon;
  label: string;
  value: string;
  tone: StatusTone;
  detail?: string;
}

function StatusRow({ icon: Icon, label, value, tone, detail }: StatusRowProps) {
  return (
    <div className="flex items-center justify-between gap-4 py-3">
      <dt className="flex items-center gap-3 text-sm text-slate-600">
        <Icon className="size-4 text-slate-400" aria-hidden="true" />
        {label}
      </dt>
      <dd className="flex items-center gap-2 text-sm font-medium text-slate-900">
        <StatusDot tone={tone} />
        {value}
        {detail && <span className="font-normal text-slate-500 tabular-nums">{detail}</span>}
      </dd>
    </div>
  );
}

export function SystemStatusCard({ health }: { health: SystemHealth }) {
  const display = CONNECTION_DISPLAY[health.state];
  const isOnline = health.state === "online" || health.state === "degraded";
  const database = health.status?.database ?? health.health?.database;
  const ai = health.status?.ai;

  return (
    <Card>
      <CardHeader
        title="System status"
        description="Live connection to the Carbon Copy API"
        action={
          <button
            type="button"
            onClick={health.refresh}
            className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
            aria-label="Re-check system status"
          >
            <RefreshCw className="size-4" aria-hidden="true" />
          </button>
        }
      />
      <CardBody>
        <div aria-live="polite">
          <StatusBadge tone={display.tone}>{display.system}</StatusBadge>
        </div>

        <dl className="mt-4 divide-y divide-slate-100">
          <StatusRow
            icon={Server}
            label="Backend API"
            value={display.backend}
            tone={display.tone}
            detail={health.latencyMs !== null ? `${health.latencyMs} ms` : undefined}
          />
          <StatusRow
            icon={Database}
            label="Database"
            value={database === "connected" ? "Connected" : database === "unavailable" ? "Unavailable" : "Unknown"}
            tone={database === "connected" ? "ok" : database === "unavailable" ? "critical" : "neutral"}
          />
          <StatusRow
            icon={Cpu}
            label="AI assistance"
            value={ai ? (ai.enabled ? "Enabled" : "Not configured") : "Unknown"}
            tone={ai?.enabled ? "ok" : "neutral"}
          />
          <StatusRow icon={FlaskConical} label="Data mode" value="Synthetic demo" tone="neutral" />
        </dl>

        {health.state === "offline" && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            <p>{health.error}</p>
            <p className="mt-1 text-red-700">
              Start the backend, then it will reconnect automatically ({config.apiBaseUrl}).
            </p>
          </div>
        )}

        <p className="mt-4 text-xs text-slate-500 tabular-nums">
          {health.lastCheckedAt ? `Last checked ${health.lastCheckedAt.toLocaleTimeString()}` : "Checking..."}
          {isOnline && health.status && ` · API v${health.status.version} · ${health.status.environment}`}
        </p>
      </CardBody>
    </Card>
  );
}
