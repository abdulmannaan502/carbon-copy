import { Network } from "lucide-react";
import type { NetworkState, NetworkStrengthComponents } from "../../types/twin";
import { Card, CardBody, CardHeader } from "../ui/Card";
import { Metric } from "../ui/Metric";
import { StatusBadge } from "../ui/Status";
import { NETWORK_BAND_DISPLAY } from "./display";

const COMPONENTS: Array<{ key: keyof NetworkStrengthComponents; label: string }> = [
  { key: "depth", label: "Depth" },
  { key: "reliability", label: "Reliability" },
  { key: "freshness", label: "Freshness" },
  { key: "responsiveness", label: "Responsiveness" },
];

function Meter({ value, label }: { value: number; label: string }) {
  return (
    <div
      className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100"
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
    >
      <div className="h-full rounded-full bg-slate-800" style={{ width: `${value}%` }} />
    </div>
  );
}

export function NetworkCard({ network }: { network: NetworkState }) {
  const band = NETWORK_BAND_DISPLAY[network.network_strength_band];

  return (
    <Card className="flex flex-col">
      <CardHeader
        title="Donor network"
        description="Compatible donors known to this patient"
        action={<Network className="size-4 text-slate-400" aria-hidden="true" />}
      />
      <CardBody className="flex flex-1 flex-col gap-5">
        <div>
          <div className="flex items-end justify-between gap-4">
            <Metric
              size="lg"
              label="Network strength"
              value={
                <>
                  {network.network_strength_score}
                  <span className="text-base font-normal text-slate-400"> / 100</span>
                </>
              }
            />
            <StatusBadge tone={band.tone}>{band.label}</StatusBadge>
          </div>
          <div className="mt-3">
            <Meter value={network.network_strength_score} label="Network strength" />
          </div>
        </div>

        <dl className="grid grid-cols-3 gap-x-4 gap-y-4 border-t border-slate-100 pt-4">
          <Metric label="Known" value={network.known_donor_count} />
          <Metric label="Available" value={network.available_donor_count} />
          <Metric label="High reliability" value={network.high_reliability_donor_count} />
          <Metric label="Recently contacted" value={network.recently_contacted_donor_count} />
          <Metric label="Fatigued" value={network.fatigued_donor_count} />
          <Metric label="Bridge group" value={network.bridge_group_donor_count} />
        </dl>

        <div className="mt-auto space-y-2 border-t border-slate-100 pt-4">
          <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">Score components</p>
          {COMPONENTS.map(({ key, label }) => (
            <div key={key} className="grid grid-cols-[7.5rem_1fr_2rem] items-center gap-3 text-sm">
              <span className="text-slate-600">
                {label} <span className="text-xs text-slate-400">{network.strength_weights[key]}%</span>
              </span>
              <Meter value={network.strength_components[key]} label={`${label} component`} />
              <span className="text-right text-slate-700 tabular-nums">{network.strength_components[key]}</span>
            </div>
          ))}
          <p className="pt-1 text-xs text-slate-500">Demo operational metric — not a clinical score.</p>
        </div>
      </CardBody>
    </Card>
  );
}
