import { Capacitor } from "@capacitor/core";
import { secureStorage } from "./secure";
export const isMobile = Capacitor.isNativePlatform();
export type Connection = {
  server: string;
  token: string;
  user: { id: string; username: string; is_admin: boolean };
};
let connection: Connection | null = null;
let selectedLocal = false;
let loaded: Promise<void> | null = null;
let listeners = new Set<() => void>();
export const subscribeMobile = (fn: () => void) => {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
};
export function normalizeServer(raw: string) {
  const url = new URL(raw.trim());
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    !["", "/"].includes(url.pathname)
  )
    throw new Error("服务器必须为不带路径或密码的 HTTPS 地址");
  return url.origin;
}
export function loadMobileConnection() {
  if (!isMobile) return Promise.resolve();
  return (loaded ||= (async () => {
    const stored = await secureStorage.get({ key: "connection" });
    if (stored.value) {
      const candidate = JSON.parse(stored.value) as Connection;
      candidate.server = normalizeServer(candidate.server);
      if (!/^[a-f0-9]{24}$/.test(candidate.user?.id) || !candidate.token)
        throw new Error("配对配置不完整，请重新配对");
      connection = candidate;
    }
    selectedLocal =
      (await secureStorage.get({ key: "local-mode" })).value === "true";
  })());
}
export const apiOrigin = () => connection?.server || "";
export const mobileConnection = () => connection;
export const authHeader = (): Record<string, string> =>
  connection ? { Authorization: `Bearer ${connection.token}` } : {};
export const mobileReady = () => !!connection || selectedLocal;
export const isLocalMobileMode = () => isMobile && selectedLocal && !connection;
export async function localOwner() {
  await loadMobileConnection();
  return connection?.user.id || "000000000000000000000001";
}
export async function chooseLocalMode() {
  if (!isMobile) return;
  await secureStorage.remove({ key: "connection" });
  await secureStorage.set({ key: "local-mode", value: "true" });
  connection = null;
  selectedLocal = true;
  loaded = Promise.resolve();
  listeners.forEach((fn) => fn());
}
export async function saveMobileConnection(
  server: string,
  token: string,
  user: Connection["user"],
) {
  const next = { server: normalizeServer(server), token, user };
  if (!/^[a-f0-9]{24}$/.test(user?.id) || !token)
    throw new Error("配对响应无效");
  await secureStorage.set({ key: "connection", value: JSON.stringify(next) });
  connection = next;
  selectedLocal = false;
  await secureStorage.remove({ key: "local-mode" });
  loaded = Promise.resolve();
  listeners.forEach((fn) => fn());
}
export async function clearMobileConnection() {
  await secureStorage.remove({ key: "connection" });
  await secureStorage.remove({ key: "local-mode" });
  connection = null;
  selectedLocal = false;
  loaded = Promise.resolve();
  listeners.forEach((fn) => fn());
}
