import { useEffect, useState } from "react";
import { systemService } from "../services/systemService";
import type { DatasetStats } from "../types/api";

/** Loads dataset counts whenever the backend is (or becomes) reachable. */
export function useDatasetStats(backendOnline: boolean): DatasetStats | null {
  const [stats, setStats] = useState<DatasetStats | null>(null);

  useEffect(() => {
    if (!backendOnline) return;
    const controller = new AbortController();
    systemService
      .getDatasetStats(controller.signal)
      .then(setStats)
      .catch(() => {
        if (!controller.signal.aborted) setStats(null);
      });
    return () => controller.abort();
  }, [backendOnline]);

  return backendOnline ? stats : null;
}
