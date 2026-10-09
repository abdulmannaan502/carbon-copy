import { MessageSquare, Phone, Smartphone, Users } from "lucide-react";
import { Link } from "react-router";
import { cn } from "../../lib/cn";
import { formatBloodGroup, formatDateTime, humanize } from "../../lib/format";
import type { CascadeWave, Channel, SimulatedResponse } from "../../types/cascade";
import { Card } from "../ui/Card";
import { StatusBadge, type StatusTone } from "../ui/Status";

const CHANNEL: Record<Channel, { icon: typeof Phone; label: string }> = {
  SIMULATED_CALL: { icon: Phone, label: "Call" },
  SIMULATED_SMS: { icon: MessageSquare, label: "SMS" },
  SIMULATED_APP: { icon: Smartphone, label: "App" },
};

const RESPONSE: Record<SimulatedResponse, { label: string; tone: StatusTone }> = {
  ACCEPTED: { label: "Accepted", tone: "ok" },
  DECLINED: { label: "Declined", tone: "warning" },
  UNAVAILABLE: { label: "Unavailable", tone: "warning" },
  NO_RESPONSE: { label: "No response", tone: "neutral" },
};

function minutesBetween(start: string, end: string) {
  const minutes = Math.round((new Date(`${end}Z`).getTime() - new Date(`${start}Z`).getTime()) / 60000);
  return minutes >= 60 ? `${Math.floor(minutes / 60)} h ${minutes % 60} min` : `${minutes} min`;
}

export function WaveCard({ wave, requestCode }: { wave: CascadeWave; requestCode: string }) {
  const securedHere = wave.contacts.some((c) => c.secured);

  return (
    <Card className={cn(securedHere && "ring-1 ring-emerald-200")}>
      <div className="flex flex-col gap-2 border-b border-slate-100 px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <span className="grid size-9 place-items-center rounded-lg bg-slate-900 text-sm font-semibold text-white tabular-nums">
            W{wave.wave_number}
          </span>
          <div>
            <h3 className="text-base font-semibold text-slate-900">
              Wave {wave.wave_number} · {wave.applied_action ? humanize(wave.applied_action) : "Initial outreach"}
            </h3>
            <p className="text-xs text-slate-500 tabular-nums">
              {formatDateTime(wave.started_at)} → {formatDateTime(wave.closed_at)} UTC ·{" "}
              {minutesBetween(wave.started_at, wave.closed_at)} · window {wave.response_window_minutes} min
            </p>
          </div>
        </div>
        <p className="text-xs text-slate-500 tabular-nums">
          Re-matched: {wave.eligible_candidates} eligible ·{" "}
          {wave.radius_km === null ? "whole region" : `${wave.radius_km} km radius`}
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="py-2 pr-2 pl-6 font-medium">Rank</th>
              <th className="px-3 py-2 font-medium">Donor</th>
              <th className="px-3 py-2 font-medium">Channel</th>
              <th className="px-3 py-2 text-right font-medium">Reply · accept chance</th>
              <th className="px-3 py-2 font-medium">Simulated response</th>
              <th className="py-2 pr-6 pl-3 font-medium">Detail</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {wave.contacts.map((c) => {
              const channel = CHANNEL[c.channel];
              const response = RESPONSE[c.response];
              return (
                <tr key={c.donor_code} className={cn(c.secured && "bg-emerald-50/60")}>
                  <td className="py-3 pr-2 pl-6 text-slate-500 tabular-nums">#{c.match_rank}</td>
                  <td className="px-3 py-3 whitespace-nowrap">
                    <Link to={`/donors/${c.donor_code}?request=${requestCode}`} className="font-mono font-medium text-slate-900 hover:underline">
                      {c.donor_code}
                    </Link>{" "}
                    <span className="text-slate-500">{formatBloodGroup(c.blood_group)}</span>
                    {c.bridge_group_member && (
                      <Users className="ml-1.5 inline size-3.5 text-slate-400" aria-label="Patient's bridge group member" />
                    )}
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap text-slate-700">
                    <channel.icon className="mr-1.5 inline size-3.5 text-slate-400" aria-hidden="true" />
                    {channel.label}
                  </td>
                  <td className="px-3 py-3 text-right whitespace-nowrap text-slate-600 tabular-nums">
                    {c.response_probability}% · {c.acceptance_probability}%
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap">
                    <StatusBadge tone={response.tone}>{c.secured ? "Accepted · secured" : response.label}</StatusBadge>
                  </td>
                  <td className="py-3 pr-6 pl-3 text-slate-600">
                    {c.note}
                    {c.responded_at && (
                      <span className="block text-xs text-slate-400 tabular-nums">
                        replied after {minutesBetween(c.sent_at, c.responded_at)}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
