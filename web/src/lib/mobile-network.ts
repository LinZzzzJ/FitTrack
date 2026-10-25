import { registerPlugin } from "@capacitor/core";
import {
  apiOrigin,
  authHeader,
  mobileConnection,
  type Connection,
} from "./mobile";
import { fromBase64, base64 } from "./mobile-files";
const network = registerPlugin<{
  request(options: {
    url: string;
    method: string;
    headers: Record<string, string>;
    data?: string;
    binary?: boolean;
    responseBinary?: boolean;
  }): Promise<{ status: number; data: string; contentType: string }>;
}>("FitTrackNetwork");
export class MobileHttpError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function nativeRequest(
  method: string,
  url: string,
  body?: unknown,
  headers: Record<string, string> = {},
  responseBinary = false,
) {
  const binary = body instanceof Uint8Array;
  const result = await network.request({
    method,
    url,
    headers,
    data:
      body === undefined
        ? undefined
        : binary
          ? base64(body)
          : JSON.stringify(body),
    binary,
    responseBinary,
  });
  if (result.status >= 300 || result.status < 200) {
    let detail = "";
    try {
      detail = JSON.parse(result.data).detail;
    } catch {}
    throw new MobileHttpError(
      typeof detail === "string" ? detail : `请求失败（HTTP ${result.status}）`,
      result.status,
    );
  }
  if (responseBinary) return fromBase64(result.data);
  if (result.status === 204 || !result.data) return undefined;
  try {
    return JSON.parse(result.data);
  } catch {
    throw new Error("服务器返回了无效 JSON");
  }
}
export async function serverRequest<T = any>(
  method: string,
  path: string,
  body?: unknown,
  binary = false,
  target?: Connection,
): Promise<T> {
  target ||= mobileConnection() || undefined;
  if (
    !target ||
    !/^\/[a-zA-Z0-9/?=&_.%-]+$/.test(path) ||
    path.startsWith("//")
  )
    throw new Error("服务器连接或接口路径无效");
  return nativeRequest(
    method,
    target.server + "/api" + path,
    body,
    {
      Authorization: "Bearer " + target.token,
      ...(body === undefined
        ? {}
        : {
            "Content-Type":
              body instanceof Uint8Array
                ? "application/octet-stream"
                : "application/json",
          }),
    },
    binary,
  );
}
