import type { ConnectionState } from "../../hooks/useSystemHealth";
import type { StatusTone } from "../ui/Status";

interface ConnectionDisplay {
  tone: StatusTone;
  system: string;
  backend: string;
}

export const CONNECTION_DISPLAY: Record<ConnectionState, ConnectionDisplay> = {
  checking: { tone: "pending", system: "Checking status", backend: "Connecting" },
  online: { tone: "ok", system: "System Operational", backend: "Connected" },
  degraded: { tone: "warning", system: "System Degraded", backend: "Connected" },
  offline: { tone: "critical", system: "Backend Unreachable", backend: "Disconnected" },
};
