import { ShieldCheck } from "lucide-react";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { BrandMark } from "../components/BrandMark";
import { CONNECTION_DISPLAY } from "../components/system/connectionDisplay";
import { StatusBadge } from "../components/ui/Status";
import { useSystemHealth } from "../hooks/useSystemHealth";
import { cn } from "../lib/cn";
import { config } from "../lib/config";

const NAV_ITEMS = [
  { to: "/", label: "Overview", isActive: (path: string) => path === "/" },
  { to: "/patients", label: "Patients", isActive: (path: string) => path === "/patients" },
  {
    to: "/patients/PAT-0001/digital-twin",
    label: "Digital Twin",
    isActive: (path: string) => path.endsWith("/digital-twin"),
  },
  { to: "/donors", label: "Donors", isActive: (path: string) => path.startsWith("/donors") },
  {
    to: "/requests/DEMO-REQUEST-001/matching",
    label: "Matching",
    isActive: (path: string) => path.endsWith("/matching"),
  },
  {
    to: "/requests/DEMO-REQUEST-001/cascade",
    label: "Cascade",
    isActive: (path: string) => path.endsWith("/cascade"),
  },
  { to: "/learning", label: "Learning", isActive: (path: string) => path === "/learning" },
  { to: "/notifications", label: "Notifications", isActive: (path: string) => path === "/notifications" },
];

export function AppLayout() {
  const health = useSystemHealth(config.healthPollIntervalMs);
  const display = CONNECTION_DISPLAY[health.state];
  const { pathname } = useLocation();

  return (
    <div className="flex min-h-screen flex-col">
      <div className="bg-slate-900 text-slate-200">
        <p className="mx-auto flex max-w-7xl items-center gap-2 px-4 py-2 text-xs sm:px-6 sm:text-sm">
          <ShieldCheck className="size-4 shrink-0 text-slate-400" aria-hidden="true" />
          Demonstration prototype · Synthetic demonstration data — not for clinical use
        </p>
      </div>

      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-6 px-4 py-4 sm:px-6">
          <div className="flex items-center gap-10">
            <Link to="/" className="flex items-center gap-3 rounded-lg">
              <BrandMark />
              <span>
                <span className="block text-lg leading-tight font-semibold tracking-[0.18em] text-slate-900">
                  CARBON COPY
                </span>
                <span className="block text-xs text-slate-500">Inclusive blood coordination</span>
              </span>
            </Link>
            <nav aria-label="Primary" className="hidden items-center gap-1 md:flex">
              {NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  aria-current={item.isActive(pathname) ? "page" : undefined}
                  className={cn(
                    "rounded-md px-2 py-2 text-sm font-medium xl:px-3",
                    item.isActive(pathname) ? "bg-slate-100 text-slate-900" : "text-slate-600 hover:text-slate-900",
                  )}
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>
          <div aria-live="polite" className="hidden sm:block">
            <StatusBadge tone={display.tone}>{display.system}</StatusBadge>
          </div>
        </div>
      </header>

      <main className="flex-1">
        <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
          <Outlet context={health} />
        </div>
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-1 px-4 py-4 text-sm text-slate-500 sm:flex-row sm:justify-between sm:px-6">
          <span>Carbon Copy prototype</span>
          <span>No real patient information. Not clinically validated.</span>
        </div>
      </footer>
    </div>
  );
}
