import { ArrowRight } from "lucide-react";
import { Link } from "react-router";
import { Card, CardHeader } from "../components/ui/Card";
import { useApiQuery } from "../hooks/useApiQuery";
import { formatBloodGroup, formatDate, humanize } from "../lib/format";
import { patientService } from "../services/patientService";

export function PatientsPage() {
  const patients = useApiQuery((signal) => patientService.listPatients(signal), "patients");

  return (
    <Card>
      <CardHeader
        title="Patients"
        description="Synthetic recurring patients. Open a patient to see their Living Digital Twin."
      />
      {patients.status === "loading" && <p className="px-6 py-10 text-sm text-slate-500">Loading patients…</p>}
      {patients.status === "error" && <p className="px-6 py-10 text-sm text-red-700">{patients.error.message}</p>}
      {patients.status === "success" && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs tracking-wide text-slate-500 uppercase">
              <tr>
                <th className="px-6 py-3 font-medium">Patient</th>
                <th className="px-3 py-3 font-medium">Blood group</th>
                <th className="px-3 py-3 font-medium">Location</th>
                <th className="px-3 py-3 font-medium">Cadence</th>
                <th className="px-3 py-3 font-medium">Next requirement</th>
                <th className="px-3 py-3 font-medium">Urgency</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {patients.data.items.map((p) => (
                <tr key={p.patient_code} className="hover:bg-slate-50">
                  <td className="px-6 py-3">
                    <span className="font-medium text-slate-900">{p.display_name}</span>{" "}
                    <span className="font-mono text-xs text-slate-500">{p.patient_code}</span>
                    {!p.active && <span className="ml-2 text-xs text-slate-400">(inactive)</span>}
                  </td>
                  <td className="px-3 py-3 font-medium text-slate-900">{formatBloodGroup(p.blood_group)}</td>
                  <td className="px-3 py-3 text-slate-600">{p.city}</td>
                  <td className="px-3 py-3 text-slate-600 tabular-nums">{p.transfusion_frequency_days} days</td>
                  <td className="px-3 py-3 text-slate-600 tabular-nums">{formatDate(p.next_expected_requirement)}</td>
                  <td className="px-3 py-3 text-slate-600">{humanize(p.urgency_level)}</td>
                  <td className="px-6 py-3 text-right">
                    <Link
                      to={`/patients/${p.patient_code}/digital-twin`}
                      className="inline-flex items-center gap-1 font-medium whitespace-nowrap text-brand-700 hover:underline"
                    >
                      Digital Twin <ArrowRight className="size-3.5" aria-hidden="true" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
