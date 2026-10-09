import { FileText } from "lucide-react";
import type { DigitalTwinState } from "../../types/twin";
import { Card, CardBody, CardHeader } from "../ui/Card";

export function SummaryCard({ twin }: { twin: DigitalTwinState }) {
  return (
    <Card className="flex flex-col">
      <CardHeader
        title="Digital Twin summary"
        description="Operational coordination intelligence"
        action={<FileText className="size-4 text-slate-400" aria-hidden="true" />}
      />
      <CardBody className="flex flex-1 flex-col gap-5">
        <p className="text-[15px] leading-relaxed text-slate-800">{twin.summary}</p>

        <div className="border-t border-slate-100 pt-4">
          <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">Why this state</p>
          <ul className="mt-2 space-y-1.5 text-sm text-slate-700">
            {twin.operational_state_reasons.map((reason) => (
              <li key={reason} className="flex gap-2">
                <span className="mt-2 size-1 shrink-0 rounded-full bg-slate-400" aria-hidden="true" />
                {reason}
              </li>
            ))}
          </ul>
        </div>

        <div className="mt-auto rounded-lg bg-slate-50 px-4 py-3 text-xs leading-relaxed text-slate-600">
          <p>
            <span className="font-medium text-slate-700">
              {twin.summary_source === "deterministic" ? "Deterministic summary." : "AI-assisted summary."}
            </span>{" "}
            Generated from rule-based calculations. AI-assisted explanation will be added in a later stage.
          </p>
          <p className="mt-1">
            Describes coordination and donor-network state only — not a medical assessment or diagnosis.{" "}
            {twin.data_notice}
          </p>
        </div>
      </CardBody>
    </Card>
  );
}
