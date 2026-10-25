import {
  BlobReader,
  BlobWriter,
  Uint8ArrayReader,
  ZipReader,
  ZipWriter,
  type FileEntry,
} from "@zip.js/zip.js";
import { columns, tableNames, validateTables, type Tables } from "./health";
import { canonical, sha } from "./ledger";
const MAX_COMPRESSED = 512 * 1024 * 1024,
  MAX_EXPANDED = 2 * 1024 * 1024 * 1024;
export async function readArchive(
  file: Blob,
  owner: string,
  onImage: (index: any, bytes: Uint8Array) => Promise<void>,
  checkImage: (bytes: Uint8Array, index: any) => Promise<unknown>,
) {
  if (file.size > MAX_COMPRESSED) throw new Error("备份超过512 MiB限制");
  const reader = new ZipReader(new BlobReader(file), {
    useWebWorkers: false,
    checkSignature: true,
  });
  try {
    const entries = await reader.getEntries();
    const names = new Set<string>();
    let expanded = 0;
    for (const entry of entries) {
      if (
        names.has(entry.filename) ||
        entry.directory ||
        entry.encrypted ||
        ((entry.externalFileAttributes >>> 16) & 0o170000) === 0o120000
      )
        throw new Error("备份包含重复条目、链接、加密或目录");
      names.add(entry.filename);
      expanded += entry.uncompressedSize;
      if (names.size > 10002 || expanded > MAX_EXPANDED)
        throw new Error("备份文件数量或解压体积超限");
    }
    const manifest = entries.find((e) => e.filename === "manifest.json") as
      FileEntry | undefined;
    if (!manifest || manifest.uncompressedSize > 32 * 1024 * 1024)
      throw new Error("备份清单缺失或过大");
    const data = JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(
        await bounded(manifest, 32 * 1024 * 1024),
      ),
    );
    if (
      data.format !== "fittrack-health" ||
      ![1, 2].includes(data.version) ||
      Object.keys(data).some(
        (k) => !["format", "version", "tables"].includes(k),
      )
    )
      throw new Error("不支持此健康备份格式");
    const tables = validateTables(data.tables, owner);
    const expected = new Set([
      "manifest.json",
      ...tables.images.map((i) => `images/${i.sha}.${i.ext}`),
    ]);
    if (
      expected.size !== names.size ||
      [...names].some((n) => !expected.has(n))
    )
      throw new Error("备份包含额外路径或缺失照片");
    // Check every image before writing health rows. Image bytes are immutable and
    // content-addressed; a failed import never replaces the active journal.
    for (const index of tables.images) {
      const entry = entries.find(
        (e) => e.filename === `images/${index.sha}.${index.ext}`,
      ) as FileEntry;
      const bytes = await bounded(entry, 12 * 1024 * 1024);
      if ((await sha(bytes)) !== index.sha) throw new Error("照片哈希不符");
      await checkImage(bytes, index);
      await onImage(index, bytes);
    }
    return tables;
  } finally {
    await reader.close();
  }
}
async function bounded(entry: FileEntry, limit: number) {
  if (entry.uncompressedSize > limit) throw new Error("备份条目超出大小限制");
  const chunks: Uint8Array[] = [];
  let size = 0;
  await entry.getData(
    new WritableStream<Uint8Array>({
      write(chunk) {
        size += chunk.length;
        if (size > limit) throw new Error("解压数据超限");
        chunks.push(chunk);
      },
    }),
    { useWebWorkers: false, checkSignature: true },
  );
  if (size !== entry.uncompressedSize) throw new Error("解压长度与清单不符");
  const result = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.length;
  }
  return result;
}
export async function writeArchive(
  tables: Tables,
  getImage: (index: any) => Promise<Uint8Array>,
) {
  const validated = validateTables(
    tables,
    tables.profiles[0]?.user_id ||
      tables.images[0]?.user_id ||
      tableNames.flatMap((t) => tables[t])[0]?.user_id ||
      "000000000000000000000001",
  );
  // Export only the exact PC v2 columns, never sync metadata or credentials.
  const rows = Object.fromEntries(
    tableNames.map((t) => [
      t,
      validated[t].map((row) =>
        Object.fromEntries(columns[t].map((k) => [k, row[k]])),
      ),
    ]),
  );
  const writer = new ZipWriter(new BlobWriter("application/zip"), {
    useWebWorkers: false,
  });
  const manifest = new TextEncoder().encode(
    canonical({ format: "fittrack-health", version: 2, tables: rows }),
  );
  if (manifest.length > 32 * 1024 * 1024) throw new Error("备份清单过大");
  await writer.add("manifest.json", new Uint8ArrayReader(manifest));
  const written = new Set<string>();
  for (const index of validated.images) {
    const name = `images/${index.sha}.${index.ext}`;
    if (written.has(name)) continue;
    const bytes = await getImage(index);
    if ((await sha(bytes)) !== index.sha) throw new Error("照片缺失或哈希错误");
    await writer.add(name, new Uint8ArrayReader(bytes));
    written.add(name);
  }
  const blob = await writer.close();
  if (blob.size > MAX_COMPRESSED) throw new Error("备份超过512 MiB限制");
  return blob;
}
