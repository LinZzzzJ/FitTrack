import { Capacitor } from "@capacitor/core";
import {
  CapacitorSQLite,
  SQLiteConnection,
  type SQLiteDBConnection,
} from "@capacitor-community/sqlite";
import { secureStorage } from "./secure";

const sqlite = new SQLiteConnection(CapacitorSQLite);
let connection: SQLiteDBConnection | null = null;
let opening: Promise<SQLiteDBConnection> | null = null;

/**
 * Open the encrypted mobile journal. `secret` must come from an Android
 * Keystore-backed bridge; this function deliberately has no fallback key.
 * The web/PC build never calls this module.
 */
async function openJournal(secret?: string) {
  if (!Capacitor.isNativePlatform())
    throw new Error("本地移动数据库仅可在 Android 应用中使用");
  secret ||= (await secureStorage.getOrCreateDatabaseSecret()).secret;
  if (!secret || secret.length < 32) throw new Error("移动数据库密钥不可用");
  if (connection) return connection;
  if (!(await sqlite.isSecretStored()).result)
    await sqlite.setEncryptionSecret(secret);
  else if (!(await sqlite.checkEncryptionSecret(secret)).result)
    throw new Error("移动数据库密钥不匹配，已保留旧库");
  connection = await sqlite.createConnection(
    "fittrack_local",
    true,
    "secret",
    1,
    false,
  );
  await connection.open();
  await connection.execute(`
    CREATE TABLE IF NOT EXISTS journal_meta (
      key TEXT PRIMARY KEY NOT NULL,
      value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS journal_records (
      id TEXT PRIMARY KEY NOT NULL,
      kind TEXT NOT NULL,
      record_date TEXT NOT NULL,
      payload TEXT NOT NULL,
      revision INTEGER NOT NULL DEFAULT 0,
      deleted INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS journal_outbox (
      id TEXT PRIMARY KEY NOT NULL,
      record_id TEXT NOT NULL,
      operation TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0
    );
  `);
  return connection;
}

export async function closeLocalJournal() {
  if (!connection) return;
  await sqlite.closeConnection("fittrack_local", false);
  connection = null;
  opening = null;
}

export function openLocalJournal(secret?: string) {
  return (opening ||= openJournal(secret).catch((error) => {
    opening = null;
    connection = null;
    throw error;
  }));
}
