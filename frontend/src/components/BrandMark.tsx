import { Droplet } from "lucide-react";

export function BrandMark() {
  return (
    <span className="grid size-10 place-items-center rounded-lg bg-brand-600 text-white">
      <Droplet className="size-5" strokeWidth={2.25} aria-hidden="true" />
    </span>
  );
}
