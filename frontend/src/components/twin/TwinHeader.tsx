import { Building2, MapPin, Users } from "lucide-react";
import { useNavigate } from "react-router";
import { formatBloodGroup, formatDateTime, humanize } from "../../lib/format";
import type { DigitalTwinState, PatientListItem } from "../../types/twin";
import { Card } from "../ui/Card";
import { StatusBadge } from "../ui/Status";
import { OPERATIONAL_STATE_DISPLAY } from "./display";

interface TwinHeaderProps {
  twin: DigitalTwinState;
  patients: PatientListItem[];
}

export function TwinHeader({ twin, patients }: TwinHeaderProps) {
  const navigate = useNavigate();
  const { patient } = twin;
  const state = OPERATIONAL_STATE_DISPLAY[twin.operational_state];

  return (
    <Card>
      <div className="flex flex-col gap-6 px-6 py-6 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold tracking-[0.2em] text-brand-600">LIVING DIGITAL TWIN</p>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
            <h1 className="text-3xl font-semibold tracking-tight text-slate-900 sm:text-4xl">{patient.display_name}</h1>
            <span className="grid h-10 min-w-12 place-items-center rounded-lg bg-brand-600 px-2.5 text-lg font-semibold text-white">
              {formatBloodGroup(patient.blood_group)}
            </span>
          </div>
          <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm text-slate-600">
            <div className="flex items-center gap-1.5">
              <dt className="sr-only">Patient code</dt>
              <dd className="font-mono text-slate-800">{patient.patient_code}</dd>
            </div>
            <div className="flex items-center gap-1.5">
              <MapPin className="size-4 text-slate-400" aria-hidden="true" />
              <dt className="sr-only">Location</dt>
              <dd>
                {patient.city}, {patient.state}
              </dd>
            </div>
            {patient.bridge_group_name && (
              <div className="flex items-center gap-1.5">
                <Users className="size-4 text-slate-400" aria-hidden="true" />
                <dt className="sr-only">Bridge group</dt>
                <dd>
                  {patient.bridge_group_name} <span className="text-slate-400">({patient.bridge_group_code})</span>
                </dd>
              </div>
            )}
            <div className="flex items-center gap-1.5">
              <Building2 className="size-4 text-slate-400" aria-hidden="true" />
              <dt className="sr-only">Urgency profile</dt>
              <dd>{humanize(patient.urgency_level)} urgency profile</dd>
            </div>
          </dl>
        </div>

        <div className="flex shrink-0 flex-col gap-3 lg:items-end">
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <span>Patient</span>
            <select
              value={patient.patient_code}
              onChange={(event) => navigate(`/patients/${event.target.value}/digital-twin`)}
              className="rounded-md border border-slate-300 bg-white py-1.5 pr-8 pl-2.5 text-sm text-slate-900"
            >
              {patients.length === 0 && <option value={patient.patient_code}>{patient.patient_code}</option>}
              {patients.map((p) => (
                <option key={p.patient_code} value={p.patient_code}>
                  {p.patient_code} · {p.display_name} · {formatBloodGroup(p.blood_group)}
                </option>
              ))}
            </select>
          </label>
          <div className="flex flex-col gap-1 lg:items-end" aria-live="polite">
            <span className="text-xs font-medium tracking-wide text-slate-500 uppercase">Operational state</span>
            <StatusBadge tone={state.tone}>{state.label}</StatusBadge>
            <span className="max-w-xs text-xs text-slate-500 lg:text-right">{state.meaning}</span>
          </div>
          <p className="text-xs text-slate-400 tabular-nums">As of {formatDateTime(twin.as_of)} UTC · dataset clock</p>
        </div>
      </div>
    </Card>
  );
}
