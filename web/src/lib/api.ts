import { ensureCompatible } from "./compatibility.svelte";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  if (
    method !== "GET" &&
    !path.startsWith("/auth/") &&
    !path.startsWith("/local/")
  )
    await ensureCompatible();
  const init: RequestInit = { method, credentials: "same-origin" };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const response = await fetch("/api" + path, init);
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try {
      const error: { detail?: string } = await response.json();
      message = error.detail || message;
    } catch {
      /* retain HTTP error */
    }
    throw new ApiError(message, response.status);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  delete: (path: string) => request<void>("DELETE", path),
};
export const imageUrl = (id: string, thumb = false) =>
  `/api/images/${id}${thumb ? "?thumb=true" : ""}`;
