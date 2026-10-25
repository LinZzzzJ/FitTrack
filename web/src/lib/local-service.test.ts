import { beforeEach, describe, expect, it, vi } from "vitest";
import { DatabaseSync } from "node:sqlite";
const state = vi.hoisted(() => ({
  db: null as any,
  aiEnabled: false,
  remote: false,
  server: "https://example.test",
  user: "a".repeat(24),
}));
vi.mock("./local-db", () => ({
  openLocalJournal: async () => ({
    query: async (sql: string, values: any[] = []) => ({
      values: state.db.prepare(sql).all(...values),
    }),
    run: async (sql: string, values: any[] = []) =>
      state.db.prepare(sql).run(...values),
    executeSet: async (statements: any[]) => {
      state.db.exec("BEGIN");
      try {
        for (const item of statements)
          state.db.prepare(item.statement).run(...item.values);
        state.db.exec("COMMIT");
      } catch (e) {
        state.db.exec("ROLLBACK");
        throw e;
      }
    },
  }),
}));
vi.mock("./mobile", () => ({
  isMobile: true,
  mobileReady: () => true,
  localOwner: async () =>
    state.remote ? state.user : "000000000000000000000001",
  mobileConnection: () =>
    state.remote
      ? {
          server: state.server,
          token: "synthetic",
          user: { id: state.user, username: "test" },
        }
      : null,
  saveMobileConnection: vi.fn(),
}));
vi.mock("./secure", () => ({
  secureStorage: {
    get: async (options: any) =>
      options.key.startsWith("ai-") && state.aiEnabled
        ? {
            value: JSON.stringify({
              api_key: "offline-synthetic-key",
              base_url: "https://offline.example.test",
              vision_model: "offline-model",
              coach_model: "offline-model",
              remember: true,
            }),
          }
        : {},
    set: async () => {},
    remove: async () => {},
  },
}));
vi.mock("./mobile-network", () => ({
  serverRequest: vi.fn(),
  nativeRequest: vi.fn(),
  MobileHttpError: class extends Error {
    constructor(
      message: string,
      public status: number,
    ) {
      super(message);
    }
  },
}));
import { localRequest } from "./local-api";
import { outbox, readHealth, scope } from "./repository";
import { serverRequest, nativeRequest } from "./mobile-network";
import { syncNow } from "./sync";
beforeEach(() => {
  state.remote = false;
  state.aiEnabled = false;
  vi.mocked(nativeRequest).mockReset();
  state.user = "a".repeat(24);
  state.server = "https://example.test";
  state.db = new DatabaseSync(":memory:");
  state.db.exec(
    `CREATE TABLE journal_records(id TEXT PRIMARY KEY,kind TEXT,record_date TEXT,payload TEXT,revision INTEGER,deleted INTEGER);CREATE TABLE journal_meta(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE journal_outbox(id TEXT PRIMARY KEY,record_id TEXT,operation TEXT,payload TEXT,created_at TEXT,attempts INTEGER)`,
  );
  vi.stubGlobal("window", new EventTarget());
  vi.mocked(serverRequest).mockReset();
});
describe("native service with real SQLite transactions", () => {
  it("persists CRUD and deterministically returns days/trends to existing Svelte pages", async () => {
    const profile = {
      effective_date: "2026-10-15",
      height_cm: 175,
      initial_weight_kg: 75,
      resting_kcal: 1800,
    };
    await localRequest("PUT", "/profile", profile);
    await localRequest("PUT", "/body", { date: "2026-10-20", weight_kg: 74 });
    const meal: any = await localRequest("POST", "/meals", {
      date: "2026-10-20",
      items: [
        {
          name: "meal",
          kcal: 200,
          protein_g: 10,
          carbs_g: 20,
          fat_g: 5,
          estimated_edible_grams: 100,
        },
      ],
    });
    const day: any = await localRequest("GET", "/days/2026-10-20");
    expect(day.body.weight_kg).toBe(74);
    expect(day.totals.kcal).toBe(200);
    expect(day.totals.protein_g).toBe(10);
    expect(day.expenditure_kcal).toBe(2160);
    const trend: any = await localRequest(
      "GET",
      "/trends?start=2026-10-15&end=2026-10-20&measurement_start=2026-10-15",
    );
    expect(trend.days.at(-1).totals.kcal).toBe(200);
    expect(trend.days.at(-1).weight_average_7d).toBe(74);
    await localRequest("DELETE", "/meals/" + meal.id);
    expect((await localRequest<any>("GET", "/days/2026-10-20")).meals).toEqual(
      [],
    );
  });
  it("completes a plan once and respects duplicate confirmation after restart reads", async () => {
    const plan = await localRequest<any>("POST", "/plans", {
      date: "2026-10-20",
      title: "back",
    });
    const one = await localRequest<any>("POST", `/plans/${plan.id}/complete`),
      two = await localRequest<any>("POST", `/plans/${plan.id}/complete`);
    expect(one.id).toBe(two.id);
    expect(one.plan_id).toBe(plan.id);
  });
  it("refuses paid AI when no personal key is configured", async () => {
    await expect(
      localRequest("POST", "/jobs", {
        kind: "meal",
        date: "2026-10-20",
        meal_description: "synthetic food",
        request_key: "synthetic-request",
      }),
    ).rejects.toThrow();
    expect(serverRequest).not.toHaveBeenCalled();
  });
  it("separates server accounts and leaves unsent rows durable after connection errors", async () => {
    state.remote = true;
    await localRequest("PUT", "/body", { date: "2026-10-20", weight_kg: 74 });
    expect(await outbox()).toHaveLength(1);
    vi.mocked(serverRequest).mockRejectedValue(new Error("offline"));
    await expect(syncNow(true)).rejects.toThrow("offline");
    expect(await outbox()).toHaveLength(1);
    expect((await readHealth()).body("2026-10-20")?.weight_kg).toBe(74);
    state.user = "b".repeat(24);
    expect((await readHealth()).rows("bodies")).toHaveLength(0);
    expect(await outbox()).toHaveLength(0);
    state.user = "a".repeat(24);
    expect(await outbox()).toHaveLength(1);
  });
  it("commits acknowledged rows before clearing outbox even if the following pull fails", async () => {
    state.remote = true;
    await localRequest("PUT", "/body", { date: "2026-10-20", weight_kg: 74 });
    const [operation] = await outbox();
    vi.mocked(serverRequest).mockImplementation(
      async (method: any, path: any) => {
        if (method === "POST" && path === "/mobile/sync")
          return {
            acknowledgements: [{ ...operation, row: operation.row }],
          } as any;
        throw new Error("pull disconnected");
      },
    );
    await expect(syncNow(true)).rejects.toThrow();
    expect(await outbox()).toHaveLength(0);
    expect((await readHealth()).body("2026-10-20")?.weight_kg).toBe(74);
  });
});

it("pins an in-flight local write to its original account when the account changes", async () => {
  const { mutate } = await import("./repository");
  state.remote = true;
  let release!: () => void, started!: () => void;
  const wait = new Promise<void>((resolve) => (release = resolve)),
    entered = new Promise<void>((resolve) => (started = resolve));
  const writing = mutate(async (h) => {
    started();
    await wait;
    h.saveBody({ date: "2026-10-20", weight_kg: 73 });
  });
  await entered;
  state.user = "b".repeat(24);
  release();
  await writing;
  expect((await readHealth()).rows("bodies")).toHaveLength(0);
  state.user = "a".repeat(24);
  expect((await readHealth()).body("2026-10-20")?.weight_kg).toBe(73);
});

it("stores an offline AI result in the initiating local workspace after switching accounts", async () => {
  state.aiEnabled = true;
  let respond!: (value: any) => void, called!: () => void;
  const started = new Promise<void>((resolve) => (called = resolve));
  vi.mocked(nativeRequest).mockImplementation(async () => {
    called();
    return new Promise((resolve) => (respond = resolve));
  });
  const job = await localRequest<any>("POST", "/jobs", {
    kind: "meal",
    date: "2026-10-20",
    meal_description: "synthetic meal",
    request_key: "offline-ai-scope-test",
  });
  await started;
  state.remote = true;
  state.user = "b".repeat(24);
  respond({
    choices: [
      {
        message: {
          content: JSON.stringify({
            items: [
              {
                name: "synthetic",
                estimated_edible_grams: 100,
                kcal: 200,
                protein_g: 10,
                carbs_g: 20,
                fat_g: 5,
              },
            ],
            assumptions: [],
          }),
        },
      },
    ],
  });
  await vi.waitFor(async () => {
    const original = await readHealth({
      namespace: "local",
      owner: "000000000000000000000001",
    });
    expect(original.job(job.id).status).toBe("done");
  });
  expect((await readHealth()).rows("jobs")).toHaveLength(0);
  expect(nativeRequest).toHaveBeenCalledTimes(1);
});
