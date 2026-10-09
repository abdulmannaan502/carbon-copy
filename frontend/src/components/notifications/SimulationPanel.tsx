import { FlaskConical, Loader2 } from "lucide-react";
import { useState } from "react";
import { Card, CardBody, CardHeader } from "../ui/Card";
import { ApiError } from "../../services/apiClient";
import { notificationService } from "../../services/notificationService";
import { RequestFinder } from "./RequestFinder";
import { humanize } from "../../lib/format";
import type { NotificationDispatchReport, RequestListItem, SimulationSettings } from "../../types/notifications";

const STRESS: Array<{ value: SimulationSettings["stress"]; label: string }> = [
  { value: "none", label: "None (calibrated)" },
  { value: "moderate", label: "Moderate (replies ×0.75)" },
  { value: "severe", label: "Severe (replies ×0.5)" },
];

type Run = { state: "idle" } | { state: "running" } | { state: "done"; report: NotificationDispatchReport } | { state: "error"; message: string };

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return error.detail ?? "That request was not found.";
    if (error.status === 422) return `The simulation settings were rejected: ${error.detail ?? "invalid values"}.`;
    if (error.status !== null && error.status >= 500) return "The server hit an error while running the simulation. No result was returned; try again.";
    return error.detail ?? error.message;
  }
  return "Unexpected error while running the simulation.";
}

/** Groups backend dispatch items as "Donor outreach → donor: 7 recorded". */
function summarise(report: NotificationDispatchReport): Array<{ key: string; label: string; counts: string }> {
  const groups = new Map<string, Record<string, number>>();
  for (const item of report.items) {
    const key = `${humanize(item.event_type)} → ${item.recipient_role.toLowerCase()}`;
    const counts = groups.get(key) ?? {};
    counts[item.outcome] = (counts[item.outcome] ?? 0) + 1;
    groups.set(key, counts);
  }
  return [...groups].map(([key, counts]) => ({
    key,
    label: key,
    counts: Object.entries(counts).map(([outcome, n]) => `${n} ${outcome.toLowerCase()}`).join(", "),
  }));
}

export function SimulationPanel({ onRecorded }: { onRecorded: () => void }) {
  const [selected, setSelected] = useState<RequestListItem | null>(null);
  const [settings, setSettings] = useState<Omit<SimulationSettings, "requestCode">>({
    seed: 25, stress: "none", maxWaves: 5, waveSize: null,
  });
  const [run, setRun] = useState<Run>({ state: "idle" });

  const set = <K extends keyof typeof settings>(key: K, value: (typeof settings)[K]) => {
    setSettings((s) => ({ ...s, [key]: value }));
    setRun({ state: "idle" });
  };
  const running = run.state === "running";
  const field = "rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 disabled:opacity-60";

  const start = async () => {
    if (running || selected === null) return;
    setRun({ state: "running" });
    try {
      const report = await notificationService.recordSimulation({ ...settings, requestCode: selected.request_code });
      setRun({ state: "done", report });
      onRecorded();
    } catch (error) {
      setRun({ state: "error", message: describeError(error) });
    }
  };

  return (
    <Card className="border-sky-200">
      <CardHeader
        title="Demo action: record simulated notifications"
        description="Nothing is created until you press the button"
        action={<FlaskConical className="size-5 text-sky-600" aria-hidden="true" />}
      />
      <CardBody className="space-y-4">
        <p className="text-sm text-slate-700">
          This runs a <span className="font-medium">deterministic cascade simulation</span> for the selected request and records its
          events (donor outreach, wave failures, recovery decisions, escalation, outcome) as <span className="font-medium">simulated demo
          notification records</span>. Nobody is contacted and no message is sent. Repeating the same settings creates nothing new.
        </p>
        <RequestFinder
          selected={selected}
          onSelect={(request) => {
            setSelected(request);
            setRun({ state: "idle" });
          }}
          disabled={running}
        />
        <form
          className="flex flex-wrap items-end gap-x-5 gap-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            void start();
          }}
        >
          <label className="flex flex-col gap-1 text-xs text-slate-500">
            Scenario seed
            <input
              type="number"
              min={0}
              value={settings.seed}
              disabled={running}
              onChange={(e) => e.target.value !== "" && set("seed", Number(e.target.value))}
              className={`${field} w-28 font-mono`}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-500">
            Response stress
            <select value={settings.stress} disabled={running} onChange={(e) => set("stress", e.target.value as SimulationSettings["stress"])} className={field}>
              {STRESS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-500">
            Max waves
            <select value={settings.maxWaves} disabled={running} onChange={(e) => set("maxWaves", Number(e.target.value))} className={field}>
              {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-500">
            Wave size
            <select
              value={settings.waveSize ?? ""}
              disabled={running}
              onChange={(e) => set("waveSize", e.target.value === "" ? null : Number(e.target.value))}
              className={field}
            >
              <option value="">Automatic</option>
              {[1, 2, 3, 4, 5, 6].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            disabled={running || selected === null}
            aria-busy={running}
            className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {running && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
            {running ? "Running simulation…" : "Run simulation and record notifications"}
          </button>
        </form>
        <p className="text-xs text-slate-500" data-testid="selected-settings">
          Selected: <span className="font-mono">{selected?.request_code ?? "none"}</span> · seed <span className="font-mono">{settings.seed}</span> · response
          stress {settings.stress} · up to {settings.maxWaves} wave(s) · wave size {settings.waveSize ?? "automatic"} · evaluated as of the
          dataset clock (auto)
        </p>

        <div aria-live="polite">
          {run.state === "error" && (
            <p role="alert" className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              {run.message}
            </p>
          )}
          {run.state === "done" && <Result report={run.report} />}
        </div>
      </CardBody>
    </Card>
  );
}

function Result({ report }: { report: NotificationDispatchReport }) {
  const groups = summarise(report);
  const rejected = report.items.filter((i) => i.outcome === "REJECTED");
  return (
    <div className="space-y-3 rounded-md border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-950">
      <p className="font-semibold">
        {report.created > 0
          ? `Recorded ${report.created} simulated notification${report.created === 1 ? "" : "s"} for ${report.request_code}.`
          : `Nothing new was recorded: all ${report.duplicates} notification${report.duplicates === 1 ? "" : "s"} for this simulation already existed.`}
      </p>
      <p className="text-xs">
        Simulation <span className="font-mono">{report.simulation_id}</span> · {report.mode} mode · cascade outcome{" "}
        {humanize(report.cascade_outcome)} · {report.created} created, {report.duplicates} duplicate, {report.rejected} rejected
      </p>
      <ul className="grid gap-x-6 gap-y-0.5 text-xs sm:grid-cols-2">
        {groups.map((g) => (
          <li key={g.key} className="flex justify-between gap-3 border-b border-sky-100 py-0.5">
            <span>{g.label}</span>
            <span className="tabular-nums">{g.counts}</span>
          </li>
        ))}
      </ul>
      {rejected.length > 0 && (
        <ul role="alert" className="list-disc pl-5 text-xs text-red-800">
          {rejected.map((item, index) => (
            <li key={index}>
              {humanize(item.event_type)} → {item.recipient_role.toLowerCase()}: {item.error}
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs">{report.notice}</p>
    </div>
  );
}
