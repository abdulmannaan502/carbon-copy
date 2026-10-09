import { FlaskConical } from "lucide-react";
import type { DatasetStats } from "../../types/api";
import { Card, CardBody, CardHeader } from "../ui/Card";

const PRIMARY: Array<{ key: keyof DatasetStats; label: string }> = [
  { key: "patients", label: "Patients" },
  { key: "donors", label: "Donors" },
  { key: "bridge_groups", label: "Bridge groups" },
  { key: "blood_requests", label: "Requests" },
  { key: "donor_interactions", label: "Interactions" },
];

const SECONDARY: Array<{ key: keyof DatasetStats; label: string }> = [
  { key: "coordination_attempts", label: "coordination attempts" },
  { key: "failures", label: "failures" },
  { key: "recovery_actions", label: "recovery actions" },
  { key: "learning_events", label: "learning events" },
];

const format = (value: number) => value.toLocaleString("en-US");

export function DatasetStatusCard({ stats }: { stats: DatasetStats | null }) {
  return (
    <Card>
      <CardHeader
        title="Dataset status"
        description={stats?.data_notice ?? "Synthetic demonstration data — not for clinical use."}
        action={<FlaskConical className="size-4 text-slate-400" aria-hidden="true" />}
      />
      <CardBody>
        {stats === null ? (
          <p className="text-sm text-slate-500">Dataset counts are shown once the backend is connected.</p>
        ) : !stats.seeded ? (
          <p className="text-sm text-slate-600">
            No data loaded yet. From <code className="font-mono text-slate-800">backend/</code>, run{" "}
            <code className="font-mono text-slate-800">python -m app.db.seed</code>.
          </p>
        ) : (
          <>
            <dl className="grid grid-cols-2 gap-4 sm:grid-cols-5">
              {PRIMARY.map(({ key, label }) => (
                <div key={key}>
                  <dt className="text-sm text-slate-500">{label}</dt>
                  <dd className="mt-1 text-2xl font-semibold text-slate-900 tabular-nums">
                    {format(stats[key] as number)}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="mt-4 border-t border-slate-100 pt-3 text-sm text-slate-500 tabular-nums">
              {SECONDARY.map(({ key, label }) => `${format(stats[key] as number)} ${label}`).join(" · ")}
            </p>
          </>
        )}
      </CardBody>
    </Card>
  );
}
