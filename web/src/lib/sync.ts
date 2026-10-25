import { serverRequest, MobileHttpError } from "./mobile-network";
import { mobileConnection, saveMobileConnection } from "./mobile";
import {
  exclusive,
  meta as readMeta,
  outbox as getOutbox,
  persistHealth,
  readHealth,
  setMeta as writeMeta,
  repositoryContext,
} from "./repository";
import { identifier, rowKey, emptyTables, type Table } from "./health";
import { getImageBytes, putImageBytes, validateImage } from "./mobile-files";
import { canonical, type Data } from "./ledger";
import { openLocalJournal } from "./local-db";
export const syncStatus = {
  busy: false,
  message: "",
  lastSync: "",
  pending: 0,
};
let pending: Promise<void> | null = null;
let pendingTarget = "";
export function syncNow(required = false): Promise<void> {
  const target = mobileConnection();
  if (!target) return Promise.resolve();
  const signature = target.server + "/" + target.user.id;
  if (pending)
    return pending.then(() => {
      if (pendingTarget !== signature) return syncNow(required);
      if (required && syncStatus.message !== "已同步")
        throw new Error(syncStatus.message);
    });
  pendingTarget = signature;
  const contextPromise = repositoryContext();
  const request = <T = any>(
    method: string,
    path: string,
    body?: unknown,
    binary = false,
  ) => serverRequest<T>(method, path, body, binary, target);
  pending = exclusive(async () => {
    const ctx = await contextPromise;
    const meta = <T>(key: string, fallback: T) => readMeta(key, fallback, ctx);
    const setMeta = (key: string, value: unknown) => writeMeta(key, value, ctx);
    const outbox = () => getOutbox(ctx);
    const scope = () => Promise.resolve(ctx.namespace);
    syncStatus.busy = true;
    syncStatus.message = "正在同步";
    window.dispatchEvent(new Event("fittrack-sync"));
    try {
      const health = await readHealth(ctx),
        operations = await outbox();
      let before = structuredClone(health.tables);
      const connection = await openLocalJournal();
      // Upload immutable bytes before their health-row references.
      for (const op of operations.filter((o) => o.table === "images" && o.row))
        await request(
          "PUT",
          "/mobile/images/" + op.row!.sha,
          await getImageBytes(op.row!, ctx.namespace),
        );
      const rank: Record<string, number> = {
        images: 0,
        profiles: 1,
        bodies: 2,
        jobs: 3,
        entries: 4,
        workout_templates: 5,
        feedback: 6,
        days: 7,
      };
      const order = (op: (typeof operations)[number]) =>
        op.row
          ? rank[op.table] + (op.row.kind === "plan" ? 0 : 0.1)
          : op.table === "entries"
            ? op.base?.kind === "plan"
              ? 11
              : 10
            : op.table === "jobs"
              ? 12
              : op.table === "images"
                ? 13
                : 14;
      operations.sort((a, b) => order(a) - order(b));
      for (let start = 0; start < operations.length; start += 20) {
        const batch = operations.slice(start, start + 20);
        const result = await request("POST", "/mobile/sync", {
          changes: batch.map((op) => ({
            id: op.id,
            table: op.table,
            key: op.key,
            base: op.base,
            row: op.row,
          })),
        });
        const acknowledged: string[] = [];
        for (const ack of result.acknowledgements) {
          const table = ack.table as Table;
          health.tables[table] = health
            .rows(table)
            .filter((row) => rowKey(table, row) !== ack.key);
          if (ack.row) health.rows(table).push(ack.row);
          // Only delete the exact operation acknowledged by the server.
          const row = (
            await connection.query(
              "SELECT id,payload FROM journal_outbox WHERE record_id=?",
              [await scope()],
            )
          ).values?.find((x) => JSON.parse(x.payload).id === ack.id);
          if (row) acknowledged.push(row.id);
        }
        await persistHealth(health, before, false);
        before = structuredClone(health.tables);
        for (const id of acknowledged)
          await connection.run("DELETE FROM journal_outbox WHERE id=?", [id]);
      }
      let epoch = await meta("sync-epoch", "");
      let cursor = await meta("sync-cursor", 0),
        more = true;
      while (more) {
        let result;
        try {
          result = await request(
            "GET",
            `/mobile/sync?cursor=${cursor}&limit=20${epoch ? "&epoch=" + epoch : ""}`,
          );
        } catch (error) {
          if (error instanceof MobileHttpError && error.status === 409) {
            cursor = 0;
            epoch = "";
            health.tables = emptyTables();
            continue;
          }
          throw error;
        }
        for (const change of result.changes) {
          const [table, key] = change.resource.split("/") as [Table, string];
          health.tables[table] = health
            .rows(table)
            .filter((row) => rowKey(table, row) !== key);
          if (change.row) health.rows(table).push(change.row);
        }
        epoch = result.epoch;
        cursor = result.cursor;
        more = result.more;
      }
      for (const image of health.rows("images")) {
        let present = false;
        try {
          const bytes = await getImageBytes(image, ctx.namespace);
          present = (await (await import("./ledger")).sha(bytes)) === image.sha;
        } catch {}
        if (!present) {
          const bytes = await request<Uint8Array>(
            "GET",
            "/images/" + image.id,
            undefined,
            true,
          );
          await validateImage(bytes, image as any);
          await putImageBytes(bytes, image, ctx.namespace);
        }
      }
      await persistHealth(health, before, false);
      await setMeta("sync-cursor", cursor);
      await setMeta("sync-epoch", epoch);
      await setMeta("conflicts", await request("GET", "/mobile/conflicts"));
      await setMeta("server-ai", (await request("GET", "/me")).ai);
      const remaining = await outbox();
      syncStatus.pending = remaining.length;
      syncStatus.lastSync = new Date().toISOString();
      await setMeta("last-sync", syncStatus.lastSync);
      const rotated = await meta("token-rotated", 0);
      if (Date.now() - rotated > 7 * 86400000) {
        const next = await request("POST", "/mobile/refresh");
        if (
          mobileConnection()?.server === target.server &&
          mobileConnection()?.token === target.token
        )
          await saveMobileConnection(target.server, next.token, next.user);
        await setMeta("token-rotated", Date.now());
      }
      syncStatus.message = "已同步";
      window.dispatchEvent(new Event("fittrack-local-change"));
    } catch (error) {
      syncStatus.message =
        error instanceof MobileHttpError && error.status === 401
          ? "设备已撤销或会话过期，请重新配对；本机记录仍保留"
          : error instanceof Error
            ? error.message
            : "同步失败；本机记录和待同步修改已保留";
      syncStatus.pending = (await outbox()).length;
      if (required) throw error;
    } finally {
      syncStatus.busy = false;
      window.dispatchEvent(new Event("fittrack-sync"));
    }
  }).finally(() => (pending = null));
  return pending;
}
