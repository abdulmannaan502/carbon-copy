import type { DonorStateAssessment } from "../../types/donorState";
import { formatDate } from "../../lib/format";
import { Card, CardBody, CardHeader } from "../ui/Card";

function Row({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex justify-between gap-4 py-1.5">
      <dt className="text-slate-600">{label}</dt>
      <dd className="font-medium text-slate-900 tabular-nums">{value}</dd>
    </div>
  );
}

export function BehaviourCard({ state }: { state: DonorStateAssessment }) {
  const { response, reliability, fatigue, eligibility } = state;

  return (
    <Card>
      <CardHeader title="Historical behaviour" description="Simulated outreach and coordination outcomes" />
      <CardBody className="grid gap-x-8 gap-y-5 text-sm sm:grid-cols-2">
        <div>
          <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">Messages</p>
          <dl className="mt-1 divide-y divide-slate-100">
            <Row label="Total interactions" value={response.total_interactions} />
            <Row label="Responses" value={response.total_responses} />
            <Row label="Acceptances" value={response.acceptances} />
            <Row label="Declines" value={response.declines} />
            <Row label="Unavailable replies" value={response.unavailable_replies} />
            <Row label="No responses" value={response.no_responses} />
            {response.pending > 0 && <Row label="Awaiting reply" value={response.pending} />}
          </dl>
        </div>
        <div>
          <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">Coordination</p>
          <dl className="mt-1 divide-y divide-slate-100">
            <Row label="Successful attempts" value={reliability.successful_attempts} />
            <Row label="Failed attempts" value={reliability.failed_attempts} />
            <Row label="Donations on record" value={eligibility.donation_count} />
            <Row label="Last donation" value={formatDate(eligibility.last_donation_at)} />
            <Row label="Contacts (30 days)" value={fatigue.contacts_last_30_days} />
            <Row label="Requests (30 days)" value={fatigue.requests_last_30_days} />
          </dl>
        </div>
        <div className="sm:col-span-2">
          <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">Reliability evidence</p>
          <ul className="mt-1.5 list-disc space-y-1 pl-5 text-slate-700 marker:text-slate-300">
            {reliability.reliability_factors.map((factor) => (
              <li key={factor}>{factor}</li>
            ))}
          </ul>
          <p className="mt-3 text-xs font-medium tracking-wide text-slate-500 uppercase">Coordination fatigue</p>
          <ul className="mt-1.5 list-disc space-y-1 pl-5 text-slate-700 marker:text-slate-300">
            {fatigue.fatigue_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      </CardBody>
    </Card>
  );
}
