import { Link, useParams } from "react-router";
import { ActivityTimeline } from "../components/twin/ActivityTimeline";
import { HistoryCard } from "../components/twin/HistoryCard";
import { NetworkCard } from "../components/twin/NetworkCard";
import { RequirementCard } from "../components/twin/RequirementCard";
import { SummaryCard } from "../components/twin/SummaryCard";
import { TwinHeader } from "../components/twin/TwinHeader";
import { Card, CardBody } from "../components/ui/Card";
import { useApiQuery } from "../hooks/useApiQuery";
import { patientService } from "../services/patientService";

export const DEMO_PATIENT_CODE = "PAT-0001";

function Message({ title, body }: { title: string; body: string }) {
  return (
    <Card className="mx-auto max-w-lg text-center">
      <CardBody className="py-10">
        <h1 className="text-lg font-semibold text-slate-900">{title}</h1>
        <p className="mt-2 text-sm text-slate-600">{body}</p>
        <Link to="/patients" className="mt-6 inline-block text-sm font-medium text-brand-700 hover:underline">
          Browse patients
        </Link>
      </CardBody>
    </Card>
  );
}

export function DigitalTwinPage() {
  const { patientCode = DEMO_PATIENT_CODE } = useParams();
  const twin = useApiQuery((signal) => patientService.getDigitalTwin(patientCode, signal), `twin:${patientCode}`);
  const patients = useApiQuery((signal) => patientService.listPatients(signal), "patients");

  if (twin.status === "loading") {
    return <p className="py-20 text-center text-sm text-slate-500">Building Digital Twin for {patientCode}…</p>;
  }
  if (twin.status === "error") {
    return twin.error.status === 404 ? (
      <Message title="Patient not found" body={`There is no patient with code ${patientCode} in the dataset.`} />
    ) : (
      <Message title="Digital Twin unavailable" body={twin.error.message} />
    );
  }

  const data = twin.data;
  return (
    <div className="space-y-6">
      <TwinHeader twin={data} patients={patients.status === "success" ? patients.data.items : []} />

      <div className="grid gap-6 lg:grid-cols-3">
        <RequirementCard profile={data.transfusion_profile} requirement={data.requirement_state} />
        <NetworkCard network={data.network_state} />
        <HistoryCard history={data.coordination_history} />
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ActivityTimeline activity={data.recent_activity} />
        </div>
        <SummaryCard twin={data} />
      </div>
    </div>
  );
}
