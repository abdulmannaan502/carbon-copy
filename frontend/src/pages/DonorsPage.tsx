import { ArrowRight } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Card, CardHeader } from "../components/ui/Card";
import { useApiQuery } from "../hooks/useApiQuery";
import { formatBloodGroup } from "../lib/format";
import { donorService } from "../services/donorService";

const PAGE_SIZE = 25;
const DEMO_LINKS = [
  { code: "DON-00001", label: "DON-00001 · first demo candidate" },
  { code: "DON-00002", label: "DON-00002 · second demo candidate" },
];

export function DonorsPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page")) || 1);
  const donors = useApiQuery((signal) => donorService.listDonors(page, PAGE_SIZE, signal), `donors:${page}`);
  const [code, setCode] = useState("");

  const open = (event: FormEvent) => {
    event.preventDefault();
    if (code.trim()) navigate(`/donors/${code.trim().toUpperCase()}`);
  };

  return (
    <div className="space-y-6">
      <Card>
        <div className="flex flex-col gap-4 px-6 py-5 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-base font-semibold text-slate-900">Donor State Intelligence</h1>
            <p className="mt-0.5 text-sm text-slate-500">
              Open a donor to see their computed coordination state, or start from the demo request.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {DEMO_LINKS.map((link) => (
              <Link
                key={link.code}
                to={`/donors/${link.code}?request=DEMO-REQUEST-001`}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                {link.label} <ArrowRight className="size-3.5" aria-hidden="true" />
              </Link>
            ))}
            <form onSubmit={open} className="flex items-center gap-2">
              <input
                value={code}
                onChange={(event) => setCode(event.target.value)}
                placeholder="DON-00042"
                aria-label="Donor code"
                className="w-32 rounded-md border border-slate-300 px-2.5 py-2 font-mono text-sm"
              />
              <button type="submit" className="rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700">
                Open
              </button>
            </form>
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Donors"
          description={donors.status === "success" ? `${donors.data.total.toLocaleString("en-US")} synthetic donors` : "Synthetic donors"}
        />
        {donors.status === "loading" && <p className="px-6 py-10 text-sm text-slate-500">Loading donors…</p>}
        {donors.status === "error" && <p className="px-6 py-10 text-sm text-red-700">{donors.error.message}</p>}
        {donors.status === "success" && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-200 bg-slate-50 text-xs tracking-wide text-slate-500 uppercase">
                  <tr>
                    <th className="px-6 py-3 font-medium">Donor</th>
                    <th className="px-3 py-3 font-medium">Blood group</th>
                    <th className="px-3 py-3 font-medium">Location</th>
                    <th className="px-3 py-3 font-medium">Bridge group</th>
                    <th className="px-6 py-3" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {donors.data.items.map((d) => (
                    <tr key={d.donor_code} className="hover:bg-slate-50">
                      <td className="px-6 py-3">
                        <span className="font-medium text-slate-900">{d.display_name}</span>{" "}
                        <span className="font-mono text-xs text-slate-500">{d.donor_code}</span>
                        {!d.active && <span className="ml-2 text-xs text-slate-400">(inactive)</span>}
                      </td>
                      <td className="px-3 py-3 font-medium text-slate-900">{formatBloodGroup(d.blood_group)}</td>
                      <td className="px-3 py-3 text-slate-600">{d.city}</td>
                      <td className="px-3 py-3 font-mono text-xs text-slate-600">{d.bridge_group_code ?? "—"}</td>
                      <td className="px-6 py-3 text-right">
                        <Link
                          to={`/donors/${d.donor_code}`}
                          className="inline-flex items-center gap-1 font-medium whitespace-nowrap text-brand-700 hover:underline"
                        >
                          Donor state <ArrowRight className="size-3.5" aria-hidden="true" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-slate-100 px-6 py-3 text-sm text-slate-600">
              <span className="tabular-nums">
                Page {donors.data.page} of {donors.data.pages}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => setParams({ page: String(page - 1) })}
                  className="rounded-md border border-slate-300 px-3 py-1.5 disabled:opacity-40"
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={page >= donors.data.pages}
                  onClick={() => setParams({ page: String(page + 1) })}
                  className="rounded-md border border-slate-300 px-3 py-1.5 disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
