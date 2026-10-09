import { History } from "lucide-react";
import type { CoordinationHistory } from "../../types/twin";
import { Card, CardBody, CardHeader } from "../ui/Card";
import { Metric } from "../ui/Metric";
import { RequestOutcomeChart } from "./RequestOutcomeChart";

const percent = (value: number | null) => (value === null ? "—" : `${value}%`);

export function HistoryCard({ history }: { history: CoordinationHistory }) {
  return (
    <Card className="flex flex-col">
      <CardHeader
        title="Coordination history"
        description="How this patient's requests were resolved"
        action={<History className="size-4 text-slate-400" aria-hidden="true" />}
      />
      <CardBody className="flex flex-1 flex-col gap-5">
        <dl className="grid grid-cols-3 gap-x-4 gap-y-4">
          <Metric label="Requests" value={history.total_requests} />
          <Metric
            label="Success rate"
            value={percent(history.historical_success_rate)}
            hint={`${history.fulfilled_requests} fulfilled`}
          />
          <Metric
            label="Avg attempts"
            value={history.average_coordination_attempts ?? "—"}
            hint={`${history.total_coordination_attempts} in total`}
          />
          <Metric label="Failures" value={history.total_failures} hint={`in ${history.requests_with_failures} requests`} />
          <Metric
            label="Recoveries"
            value={`${history.successful_recoveries}/${history.total_recovery_actions}`}
            hint="led to acceptance"
          />
          <Metric label="First-attempt" value={percent(history.first_attempt_success_rate)} hint="success rate" />
        </dl>
        {history.requests.length > 0 && (
          <div className="mt-auto border-t border-slate-100 pt-4">
            <RequestOutcomeChart requests={history.requests} />
          </div>
        )}
      </CardBody>
    </Card>
  );
}
