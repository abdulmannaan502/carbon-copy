// Mirrors backend/app/schemas/notification.py. Keep both sides in sync.
import type { ApiDateTime, Page, RequestStatus, UrgencyLevel } from "./twin";

export type NotificationEventType =
  | "DONOR_OUTREACH"
  | "DONOR_ACCEPTED"
  | "REQUEST_UPDATE"
  | "REQUEST_FULFILLED"
  | "RECOVERY_ACTION"
  | "ESCALATION"
  | "SYSTEM_NOTICE";
export type NotificationRecipientRole = "DONOR" | "PATIENT" | "COORDINATOR" | "SYSTEM";
export type NotificationChannel = "IN_APP" | "SMS" | "WHATSAPP";
export type NotificationMode = "DEMO" | "LIVE";
export type NotificationStatus = "QUEUED" | "SIMULATED" | "SENT" | "DELIVERED" | "FAILED" | "UNCERTAIN" | "CANCELLED";

export interface NotificationItem {
  notification_id: string;
  event_type: NotificationEventType;
  recipient_role: NotificationRecipientRole;
  recipient_ref: string | null;
  blood_request_code: string | null;
  channel: NotificationChannel;
  mode: NotificationMode;
  status: NotificationStatus;
  title: string;
  body: string;
  read: boolean;
  read_at: ApiDateTime | null;
  provider_message_id: string | null;
  failure_code: string | null;
  failure_message: string | null;
  idempotency_key: string | null;
  created_at: ApiDateTime;
  updated_at: ApiDateTime;
  delivery_note: string;
}

export interface NotificationSummary {
  total: number;
  by_status: Record<NotificationStatus, number>;
  by_mode: Record<NotificationMode, number>;
  by_channel: Record<NotificationChannel, number>;
  unread_in_app: number;
  demo_notice: string;
}

export interface NotificationFilters {
  recipientRole: NotificationRecipientRole | "";
  status: NotificationStatus | "";
  channel: NotificationChannel | "";
  requestCode: string;
  unreadOnly: boolean;
}

export interface NotificationDispatchItem {
  event_type: NotificationEventType;
  recipient_role: NotificationRecipientRole;
  wave_number: number | null;
  outcome: "RECORDED" | "DUPLICATE" | "REJECTED";
  notification_id: string | null;
  error: string | null;
}

export interface NotificationDispatchReport {
  request_code: string;
  simulation_id: string;
  parameters: Record<string, string | number>;
  mode: NotificationMode;
  cascade_outcome: string;
  created: number;
  duplicates: number;
  rejected: number;
  items: NotificationDispatchItem[];
  notice: string;
}

export interface SimulationSettings {
  requestCode: string;
  seed: number;
  stress: "none" | "moderate" | "severe";
  maxWaves: number;
  waveSize: number | null;
}

/** One row of GET /api/v1/requests, as far as the demo selector needs it. */
export interface RequestListItem {
  request_code: string;
  patient_code: string;
  blood_group: string;
  urgency_level: UrgencyLevel;
  status: RequestStatus;
  city: string;
}

export type NotificationPage = Page<NotificationItem>;
