import { Search } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { useApiQuery } from "../../hooks/useApiQuery";
import { humanize } from "../../lib/format";
import { notificationService } from "../../services/notificationService";
import type { RequestListItem } from "../../types/notifications";

export const DEMO_REQUEST = "DEMO-REQUEST-001";
const RESULT_LIMIT = 8;

const describe = (r: RequestListItem) =>
  `${humanize(r.urgency_level)} urgency · ${humanize(r.status)} · ${r.blood_group} · ${r.city}`;

interface Props {
  selected: RequestListItem | null;
  onSelect: (request: RequestListItem) => void;
  disabled?: boolean;
}

/**
 * Finds a request by code through the backend search (GET /requests?search=…), a page of at most
 * eight matches at a time, so the whole dataset is never loaded. It starts on the demo request, looked up
 * for real, and shows only non-sensitive details (no patient identifiers).
 */
export function RequestFinder({ selected, onSelect, disabled }: Props) {
  const inputId = useId();
  const [text, setText] = useState(DEMO_REQUEST);
  const [debounced, setDebounced] = useState(DEMO_REQUEST);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(text.trim()), 250);
    return () => clearTimeout(timer);
  }, [text]);

  const results = useApiQuery((signal) => notificationService.findRequests(debounced, RESULT_LIMIT, signal), `notifications:find:${debounced}`);

  // Select the demo request (or the first match) once, from real backend data.
  useEffect(() => {
    if (selected !== null || results.status !== "success" || results.data.items.length === 0) return;
    onSelect(results.data.items.find((r) => r.request_code === DEMO_REQUEST) ?? results.data.items[0]!);
  }, [results.status, selected]);

  const choose = (request: RequestListItem) => {
    onSelect(request);
    setText(request.request_code);
  };
  const waiting = debounced !== text.trim() || results.status === "loading";

  return (
    <div className="space-y-2" role="group" aria-labelledby={`${inputId}-label`}>
      <label id={`${inputId}-label`} htmlFor={inputId} className="block text-xs text-slate-500">
        Find a request by code
      </label>
      <div className="relative max-w-md">
        <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-slate-400" aria-hidden="true" />
        <input
          id={inputId}
          value={text}
          maxLength={24}
          disabled={disabled}
          autoComplete="off"
          placeholder="e.g. REQ-00001 or DEMO"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== "Enter") return;
            e.preventDefault(); // Enter picks the best match; it never starts the simulation
            if (results.status === "success" && results.data.items[0]) choose(results.data.items[0]);
          }}
          className="w-full rounded-md border border-slate-300 bg-white py-1.5 pr-3 pl-8 font-mono text-sm text-slate-900 disabled:opacity-60"
        />
      </div>

      <div aria-live="polite" className="text-xs text-slate-500">
        {waiting && "Searching…"}
        {!waiting && results.status === "error" && (
          <span role="alert" className="text-red-700">
            Request search failed: {results.error.detail ?? results.error.message}
          </span>
        )}
        {!waiting && results.status === "success" && results.data.total === 0 && (
          <span role="status" className="text-amber-800">
            No request matches “{debounced}”. Check the code; nothing can be simulated for an unknown request.
          </span>
        )}
        {!waiting && results.status === "success" && results.data.total > results.data.items.length && (
          <span>
            Showing {results.data.items.length} of {results.data.total} matches. Type more of the code to narrow them.
          </span>
        )}
      </div>

      {results.status === "success" && results.data.items.length > 0 && (
        <ul className="grid max-w-3xl gap-1 sm:grid-cols-2" aria-label="Matching requests">
          {results.data.items.map((request) => {
            const active = selected?.request_code === request.request_code;
            return (
              <li key={request.request_code}>
                <button
                  type="button"
                  disabled={disabled}
                  aria-pressed={active}
                  onClick={() => choose(request)}
                  className={`w-full rounded-md border px-3 py-1.5 text-left text-xs hover:bg-slate-50 disabled:opacity-60 ${
                    active ? "border-slate-900 bg-slate-50 ring-1 ring-slate-900" : "border-slate-200 bg-white"
                  }`}
                >
                  <span className="block font-mono text-sm font-medium text-slate-900">{request.request_code}</span>
                  <span className="block text-slate-600">{describe(request)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <p className="text-xs text-slate-600" data-testid="selected-request">
        {selected ? (
          <>
            Selected request: <span className="font-mono font-medium text-slate-900">{selected.request_code}</span> · {describe(selected)}
          </>
        ) : (
          "No request selected yet."
        )}
      </p>
    </div>
  );
}
