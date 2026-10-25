import { openLocalJournal } from "./local-db";
import {
  emptyTables,
  Health,
  identifier,
  rowKey,
  tableNames,
  type Table,
  type Tables,
} from "./health";
import { canonical, sha, type Data } from "./ledger";
import { mobileConnection } from "./mobile";
export type Outbox = {
  id: string;
  table: Table;
  key: string;
  base: Data | null;
  row: Data | null;
};
let queue = Promise.resolve();
const recovered = new Set<string>();
export type RepositoryContext = { namespace: string; owner: string };
export async function repositoryContext(): Promise<RepositoryContext> {
  const c = mobileConnection();
  return c
    ? {
        namespace: (await sha(c.server + "\0" + c.user.id)).slice(0, 24),
        owner: c.user.id,
      }
    : { namespace: "local", owner: "000000000000000000000001" };
}
export async function scope() {
  return (await repositoryContext()).namespace;
}
export function exclusive<T>(work: () => Promise<T>): Promise<T> {
  const task = queue.then(work, work);
  queue = task.then(
    () => {},
    () => {},
  );
  return task;
}
export async function readHealth(context?: RepositoryContext): Promise<Health> {
  context ||= await repositoryContext();
  const connection = await openLocalJournal(),
    namespace = context.namespace;
  const rows =
    (
      await connection.query(
        "SELECT record_date,payload FROM journal_records WHERE kind=? AND deleted=0",
        [namespace],
      )
    ).values || [];
  const tables = emptyTables();
  for (const value of rows)
    if (tableNames.includes(value.record_date))
      tables[value.record_date as Table].push(JSON.parse(value.payload));
  if (!recovered.has(namespace)) {
    recovered.add(namespace);
    if (namespace === "local")
      for (const row of tables.jobs)
        if (["queued", "running"].includes(row.status)) {
          row.status = "interrupted";
          row.error = "应用已重启，原任务未自动重发，请手动重试";
          await connection.run(
            "UPDATE journal_records SET payload=? WHERE id=?",
            [canonical(row), `${namespace}/jobs/${row.id}`],
          );
        }
  }
  return new Health(tables, context.owner, namespace);
}
export async function persistHealth(
  health: Health,
  before: Tables,
  track = true,
  context?: RepositoryContext,
) {
  const connection = await openLocalJournal(),
    namespace = context?.namespace || health.storageScope || (await scope());
  const statements: { statement: string; values: any[] }[] = [];
  for (const table of tableNames) {
    const previous = new Map(
      before[table].map((row) => [rowKey(table, row), row]),
    );
    const next = new Map(
      health.rows(table).map((row) => [rowKey(table, row), row]),
    );
    for (const key of new Set([...previous.keys(), ...next.keys()])) {
      const row = next.get(key) || null,
        old = previous.get(key) || null;
      if (canonical(row) === canonical(old)) continue;
      const id = `${namespace}/${table}/${key}`;
      if (row)
        statements.push({
          statement:
            "INSERT INTO journal_records(id,kind,record_date,payload,revision,deleted) VALUES(?,?,?,?,1,0) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,revision=journal_records.revision+1,deleted=0",
          values: [id, namespace, table, canonical(row)],
        });
      else
        statements.push({
          statement: "DELETE FROM journal_records WHERE id=?",
          values: [id],
        });
      if (track && namespace !== "local") {
        const pending = (
          await connection.query(
            "SELECT payload FROM journal_outbox WHERE id=?",
            [id],
          )
        ).values?.[0];
        const base = pending ? JSON.parse(pending.payload).base : old;
        const operation = { id: identifier(), table, key, base, row };
        statements.push({
          statement:
            "INSERT INTO journal_outbox(id,record_id,operation,payload,created_at,attempts) VALUES(?,?,?,?,?,0) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
          values: [
            id,
            namespace,
            "upsert",
            canonical(operation),
            new Date().toISOString(),
          ],
        });
      }
    }
  }
  if (statements.length) await connection.executeSet(statements, true);
}
export async function mutate<T>(
  work: (health: Health) => Promise<T> | T,
  context?: RepositoryContext,
) {
  context ||= await repositoryContext();
  return exclusive(async () => {
    const health = await readHealth(context),
      before = structuredClone(health.tables);
    const value = await work(health);
    await persistHealth(health, before, true, context);
    window.dispatchEvent(new Event("fittrack-local-change"));
    return value;
  });
}
export async function meta<T>(
  key: string,
  fallback: T,
  context?: RepositoryContext,
): Promise<T> {
  context ||= await repositoryContext();
  const conn = await openLocalJournal();
  const row = (
    await conn.query("SELECT value FROM journal_meta WHERE key=?", [
      `${context.namespace}/${key}`,
    ])
  ).values?.[0];
  return row ? JSON.parse(row.value) : fallback;
}
export async function setMeta(
  key: string,
  value: unknown,
  context?: RepositoryContext,
) {
  context ||= await repositoryContext();
  const conn = await openLocalJournal();
  await conn.run(
    "INSERT INTO journal_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
    [`${context.namespace}/${key}`, canonical(value)],
  );
}
export async function outbox(context?: RepositoryContext): Promise<Outbox[]> {
  context ||= await repositoryContext();
  const conn = await openLocalJournal();
  return (
    (
      await conn.query(
        "SELECT payload FROM journal_outbox WHERE record_id=? ORDER BY created_at,id",
        [context.namespace],
      )
    ).values || []
  ).map((r) => JSON.parse(r.payload));
}
