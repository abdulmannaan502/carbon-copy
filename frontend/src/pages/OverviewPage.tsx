import { ArrowRight } from "lucide-react";
import { Link } from "react-router";
import { CoordinationLoop } from "../components/overview/CoordinationLoop";
import { DatasetStatusCard } from "../components/system/DatasetStatusCard";
import { SystemStatusCard } from "../components/system/SystemStatusCard";
import { useDatasetStats } from "../hooks/useDatasetStats";
import { useLayoutHealth } from "../hooks/useSystemHealth";

export function OverviewPage() {
  const health = useLayoutHealth();
  const datasetStats = useDatasetStats(health.state === "online" || health.state === "degraded");

  return (
    <div className="space-y-8">
      <div className="grid items-start gap-8 lg:grid-cols-3">
        <section className="lg:col-span-2 lg:pt-4">
          <p className="text-sm font-semibold tracking-[0.2em] text-brand-600">CARBON COPY</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight text-balance text-slate-900 sm:text-5xl">
            Living Digital Twin for Inclusive Blood Coordination
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-slate-600">
            Coordination for patients who depend on recurring transfusions. Every outreach attempt is tracked, every
            failure is analysed, and the next pathway is chosen by transparent, deterministic rules.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link
              to="/patients/PAT-0001/digital-twin"
              className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-700"
            >
              Open Living Digital Twin · PAT-0001
              <ArrowRight className="size-4" aria-hidden="true" />
            </Link>
            <Link
              to="/patients"
              className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Browse patients
            </Link>
          </div>
        </section>
        <SystemStatusCard health={health} />
      </div>

      <DatasetStatusCard stats={datasetStats} />

      <CoordinationLoop />
    </div>
  );
}
