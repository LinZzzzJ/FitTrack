import { api } from "./api";
import type { Plan, TrendDay } from "./types";

export const TRACKING_START = "2026-10-15";

export function dietWeek(day: string) {
  const offset = Math.floor(
    (Date.parse(day + "T12:00:00Z") -
      Date.parse(TRACKING_START + "T12:00:00Z")) /
      86400000 /
      7,
  );
  return shiftDate(TRACKING_START, offset * 7);
}

export function shiftDate(day: string, amount: number) {
  const value = new Date(day + "T12:00:00Z");
  value.setUTCDate(value.getUTCDate() + amount);
  return value.toISOString().slice(0, 10);
}

export async function loadTrends(end: string, current: () => boolean) {
  const result = { days: [] as TrendDay[], plans: [] as Plan[] };
  for (let start = TRACKING_START; start <= end && current();) {
    const last = shiftDate(start, 365) < end ? shiftDate(start, 365) : end;
    const batch = await api.get<typeof result>(
      `/trends?start=${start}&end=${last}&measurement_start=${TRACKING_START}`,
    );
    result.days.push(...batch.days);
    result.plans.push(...batch.plans);
    start = shiftDate(last, 1);
  }
  return result;
}
