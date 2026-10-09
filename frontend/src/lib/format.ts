import type { ApiDate, ApiDateTime, BloodGroup } from "../types/twin";

// API timestamps are naive UTC; display them in UTC so they match the dataset clock.
const dateFormat = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
const shortDateFormat = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" });
const dateTimeFormat = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: "UTC",
});

const toDate = (value: ApiDate | ApiDateTime) => new Date(value.length === 10 ? `${value}T00:00:00Z` : `${value}Z`);

export const formatDate = (value: ApiDate | ApiDateTime | null) => (value ? dateFormat.format(toDate(value)) : "—");
export const formatShortDate = (value: ApiDate | ApiDateTime | null) =>
  value ? shortDateFormat.format(toDate(value)) : "—";
export const formatDateTime = (value: ApiDateTime | null) => (value ? dateTimeFormat.format(toDate(value)) : "—");

/** "B-" → "B−" (true minus sign) for display. */
export const formatBloodGroup = (group: BloodGroup) => group.replace("-", "−");

/** "ACTIVE_COORDINATION" → "Active coordination". */
export const humanize = (value: string) => {
  const text = value.replaceAll("_", " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
};

export const plural = (count: number, singular: string, pluralForm = `${singular}s`) =>
  `${count.toLocaleString("en-US")} ${count === 1 ? singular : pluralForm}`;
