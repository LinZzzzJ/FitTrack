import { isMobile, clearMobileConnection, mobileConnection } from "./mobile";
import { syncNow } from "./sync";
import { api, ApiError } from "./api";
import { loadTrends } from "./tracking";
export { shiftDate } from "./tracking";
import type {
  Activity,
  AIConfig,
  Day,
  Me,
  Page,
  Plan,
  Profile,
  TrendDay,
  User,
  RuntimeCapabilities,
} from "./types";

export const app = $state({
  user: null as User | null,
  profile: null as Profile | null,
  ai: null as AIConfig | null,
  runtime: null as RuntimeCapabilities | null,
  activities: [] as Activity[],
  date: "",
  today: "",
  page: "dashboard" as Page,
  day: null as Day | null,
  trends: [] as TrendDay[],
  plans: [] as Plan[],
  loading: true,
  busy: false,
  notice: "",
  noticeError: false,
  menuOpen: false,
});
let source: EventSource | null = null;
let refreshGeneration = 0;

export function number(value: number | null | undefined, digits = 0): string {
  return value == null || !Number.isFinite(value)
    ? "—"
    : value.toLocaleString("zh-CN", { maximumFractionDigits: digits });
}
export function notify(message: string, error = false) {
  app.notice = message;
  app.noticeError = error;
  if (!error)
    setTimeout(() => {
      if (app.notice === message) app.notice = "";
    }, 3500);
}
export async function refresh() {
  if (!app.user || !app.date) return;
  const generation = ++refreshGeneration;
  const selected = app.date;
  const [day, trend] = await Promise.all([
    api.get<Day>(`/days/${selected}`),
    loadTrends(
      selected,
      () =>
        generation === refreshGeneration && selected === app.date && !!app.user,
    ),
  ]);
  if (generation !== refreshGeneration || selected !== app.date || !app.user)
    return;
  app.day = day;
  if (isMobile && day.profile) app.profile = day.profile;
  app.trends = trend.days;
  app.plans = trend.plans;
}
export async function perform(
  action: () => Promise<unknown>,
  message = "已保存",
) {
  if (app.busy) return false;
  app.busy = true;
  try {
    await action();
    await refresh();
    if (message) notify(message);
    return true;
  } catch (error) {
    notify(error instanceof Error ? error.message : "操作失败，请重试", true);
    return false;
  } finally {
    app.busy = false;
  }
}
export function connectEvents() {
  source?.close();
  if (isMobile) return;
  source = new EventSource("/api/events");
  source.onmessage = () => {
    void refresh().catch(() => {});
  };
  source.addEventListener("ready", () => {
    void refresh().catch(() => {});
  });
}
export async function init() {
  app.loading = true;
  try {
    const me = await api.get<Me>("/me");
    app.user = me.user;
    app.profile = me.profile;
    app.ai = me.ai;
    app.runtime = me.runtime || null;
    app.activities = me.activities;
    app.today = me.today;
    app.date ||= me.today;
    if (!me.profile) app.page = "settings";
    await refresh();
    connectEvents();
    if (mobileConnection()) void syncNow();
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 401))
      notify(error instanceof Error ? error.message : "无法连接本地服务", true);
  } finally {
    app.loading = false;
  }
}
export async function logout() {
  await api.post("/auth/logout");
  source?.close();
  source = null;
  if (isMobile) await clearMobileConnection();
  refreshGeneration++;
  app.user = null;
  app.profile = null;
  app.day = null;
  app.trends = [];
  app.plans = [];
  app.date = "";
  app.ai = null;
  app.runtime = null;
  app.notice = "";
  app.page = "dashboard";
}
export async function selectDate(value: string) {
  if (app.date !== value) app.trends = [];
  app.date = value;
  await refresh();
}
export function navigate(page: Page) {
  app.page = page;
  app.menuOpen = false;
}
