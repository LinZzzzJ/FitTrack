/** Android service facade. UI uses exactly the same contracts as FastAPI. */
import contracts from "./mobile-contracts.json";
import {
  activities,
  canonical,
  dates,
  labelFood,
  levels,
  shanghaiToday,
  validate,
  type Data,
} from "./ledger";
import { Health, identifier, tableNames, unpack } from "./health";
import { meta, setMeta, mutate, readHealth } from "./repository";
import { mobileConnection, mobileReady } from "./mobile";
import { putImageBytes, validateImage } from "./mobile-files";
import {
  publicAI,
  saveAI,
  clearAI,
  clearTemporaryAI,
  testAI,
  submitAI,
} from "./local-ai";
import { serverRequest } from "./mobile-network";
export async function localRequest<T>(
  method: string,
  path: string,
  body?: any,
): Promise<T> {
  if (!mobileReady())
    throw Object.assign(new Error("请选择本地使用或连接服务器"), {
      status: 401,
    });
  const [route, query = ""] = path.split("?"),
    params = new URLSearchParams(query),
    parts = route.split("/").filter(Boolean);
  if (route === "/auth/logout") {
    if (mobileConnection()) {
      try {
        await serverRequest("POST", "/auth/logout");
      } catch {
        /* Local credentials are cleared by logout even when the server is unreachable. */
      }
    }
    clearTemporaryAI();
    return undefined as T;
  }
  if (route === "/exercise-catalog")
    return { version: 1, exercises: contracts.exercises } as T;
  if (route === "/settings") {
    const value =
      method === "PUT"
        ? await (mobileConnection()
            ? serverRequest("PUT", path, body)
            : saveAI(body))
        : await publicAI();
    if (mobileConnection()) await setMeta("server-ai", value);
    return value as T;
  }
  if (route === "/settings/key") {
    if (mobileConnection()) await serverRequest("DELETE", path);
    else await clearAI();
    return undefined as T;
  }
  if (route === "/settings/test-connection")
    return (await (mobileConnection()
      ? serverRequest("POST", path)
      : testAI())) as T;
  if (route === "/jobs" && method === "POST") {
    if (mobileConnection()) {
      // AI is never auto-retried or queued for later paid execution. The user
      // must explicitly request it after all relevant local data has synced.
      const { syncNow } = await import("./sync");
      await syncNow(true);
      const job = await serverRequest("POST", path, body);
      void import("./sync").then((s) => s.syncNow()).catch(() => {});
      return job as T;
    }
    return (await submitAI(body)) as T;
  }
  if (parts[0] === "jobs" && method === "GET" && mobileConnection()) {
    try {
      return (await serverRequest("GET", path)) as T;
    } catch (error) {
      if ((error as any).status) throw error;
    }
  }
  if (method !== "GET")
    return mutate(async (h) => {
      if (route === "/profile") return h.saveProfile(body) as T;
      if (route === "/body") return h.saveBody(body) as T;
      if (parts[0] === "body" && method === "DELETE") {
        h.remove("bodies", parts[1]);
        return undefined as T;
      }
      if (route === "/uploads") {
        const file = body instanceof FormData ? body.get("file") : null;
        if (!(file instanceof Blob)) throw new Error("请选择照片");
        const bytes = new Uint8Array(await file.arrayBuffer()),
          index = await validateImage(bytes);
        const existing = h.rows("images").find((x) => x.sha === index.sha);
        if (existing) return existing as T;
        await putImageBytes(bytes, index, h.storageScope);
        const image = {
          id: identifier(),
          user_id: h.owner,
          ...index,
          created_at: Date.now() / 1000,
        };
        h.upsert("images", image);
        return image as T;
      }
      if (parts[0] === "workout-templates") {
        if (method === "DELETE") {
          h.remove("workout_templates", parts[1]);
          return undefined as T;
        }
        return h.saveTemplate(body, parts[1]) as T;
      }
      if (parts[0] === "plans" && parts[2] === "complete") {
        const row = h.find("entries", parts[1]);
        if (row.kind !== "plan") throw new Error("排期不存在");
        const p = unpack(row);
        return h.saveEntry("workout", {
          ...Object.fromEntries(
            [
              "date",
              "title",
              "kind",
              "activity",
              "duration_minutes",
              "intensity",
              "note",
              "exercises",
            ].map((k) => [k, p[k]]),
          ),
          plan_id: p.id,
        }) as T;
      }
      if (["meals", "workouts", "plans"].includes(parts[0])) {
        const kind = (
          { meals: "meal", workouts: "workout", plans: "plan" } as Data
        )[parts[0]];
        if (method === "DELETE") {
          h.deleteEntry(kind, parts[1]);
          return undefined as T;
        }
        if (kind === "workout" && body.ai_estimate_job_id) {
          const source = h.job(body.ai_estimate_job_id);
          if (source.source_hash !== (await h.fingerprint(source.request)))
            throw new Error("AI 有氧估算已过期，请重新估算或解除来源");
        }
        return h.saveEntry(kind, body, parts[1]) as T;
      }
      if (parts[0] === "days" && parts[2] === "complete") {
        dates(parts[1], parts[1]);
        h.upsert("days", { user_id: h.owner, date: parts[1], completed: 1 });
        return { completed: true } as T;
      }
      if (route === "/nutrition-label/preview")
        return { item: labelFood(body) } as T;
      if (parts[0] === "jobs" && method === "DELETE") {
        const job = h.job(parts[1]);
        if (job.kind !== "meal" || ["queued", "running"].includes(job.status))
          throw new Error("只能删除已结束的餐食分析");
        // Preserve provenance for already confirmed meals just as the PC store does.
        for (const row of h
          .rows("entries")
          .filter((x) => x.source_job_id === job.id)) {
          const data = JSON.parse(row.data);
          data.source_job_id = null;
          row.source_job_id = null;
          row.data = canonical(data);
        }
        h.remove("jobs", parts[1]);
        return undefined as T;
      }
      throw new Error("当前平台不提供此系统管理操作");
    });
  const h = await readHealth();
  if (route === "/me")
    return {
      user: mobileConnection()?.user || {
        id: h.owner,
        username: "本机记录",
        is_admin: true,
      },
      today: shanghaiToday(),
      profile: h.profile(shanghaiToday()),
      ai: mobileConnection() ? await serverAI() : await publicAI(),
      activities,
      activity_levels: levels,
      runtime: {
        mode: mobileConnection() ? "server" : "local",
        choose_directory: false,
        open_directory: false,
        migrate_workspace: false,
        migrate_root: false,
        stop_service: false,
        allowed_providers: [],
      },
    } as T;
  if (route === "/profile")
    return h.profile(params.get("day") || shanghaiToday()) as T;
  if (route === "/body") {
    const days = dates(params.get("start")!, params.get("end")!);
    return h
      .rows("bodies")
      .filter((x) => days.includes(x.date))
      .map(unpack) as T;
  }
  if (parts[0] === "days")
    return (await withStaleness(h, h.summary(parts[1]))) as T;
  if (route === "/plans")
    return h.plans(params.get("start")!, params.get("end")!) as T;
  if (route === "/workout-days")
    return [
      ...new Set(
        h
          .entries("workout", params.get("start")!, params.get("end")!)
          .map((x) => x.date),
      ),
    ] as T;
  if (route === "/workout-templates")
    return h.rows("workout_templates").map(unpack) as T;
  if (route === "/trends")
    return h.trends(
      params.get("start")!,
      params.get("end")!,
      params.get("measurement_start") || undefined,
    ) as T;
  if (parts[0] === "jobs") {
    const j = h.job(parts[1]);
    if (j.result)
      j.result.stale = j.source_hash !== (await h.fingerprint(j.request));
    return j as T;
  }
  if (route === "/diet-history") {
    const days = dates(params.get("start")!, params.get("end")!);
    if (days.length > 7) throw new Error("饮食历史每次最多7天");
    return {
      start: days[0],
      end: days.at(-1),
      days: days.map((d) => {
        const s = h.summary(d);
        return {
          date: d,
          meals: s.meals,
          totals: s.totals,
          jobs: s.jobs.filter((j: Data) => j.kind === "meal"),
        };
      }),
    } as T;
  }
  if (route === "/weekly-review") {
    const w = h.weekly(params.get("week_start") || undefined);
    delete w.days;
    if (w.report?.result)
      w.report.result.stale =
        w.report.source_hash !== (await h.fingerprint(w.report.request));
    return w as T;
  }
  throw new Error("此接口不适用于移动端");
}
async function serverAI() {
  const cached = await meta<any>("server-ai", null);
  if (cached) return cached;
  try {
    const ai = (await serverRequest("GET", "/me")).ai;
    await setMeta("server-ai", ai);
    return ai;
  } catch {
    return {
      api_key_set: false,
      base_url: "https://api.deepseek.com",
      vision_model: "deepseek-flash",
      coach_model: "deepseek-flash",
      environment_override: false,
      credential_scope: "none",
    };
  }
}
async function withStaleness(h: Health, summary: Data) {
  for (const job of summary.jobs)
    if (job.result && job.kind !== "meal")
      job.result.stale = job.source_hash !== (await h.fingerprint(job.request));
  if (summary.feedback) {
    const req = { kind: "feedback", date: summary.date };
    summary.feedback.stale =
      h.rows("feedback").find((x) => x.date === summary.date)!.source_hash !==
      (await h.fingerprint(req));
  }
  return summary;
}
