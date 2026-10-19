<script lang="ts">
  import { onMount } from "svelte";
  import {
    FolderOpen,
    Database,
    Archive,
    ShieldCheck,
    ArrowRight,
    LoaderCircle,
    Power,
    HardDrive,
    Upload,
  } from "@lucide/svelte";
  import { api } from "../lib/api";
  import { app, notify, refresh } from "../lib/state.svelte";
  import type { StorageInfo, StorageOperation, BackupInfo } from "../lib/types";
  let info = $state<StorageInfo | null>(null);
  let backups = $state<BackupInfo[]>([]);
  let operation = $state<StorageOperation | null>(null);
  let target = $state("");
  let nextRoot = $state("");
  let busy = $state(false);
  let error = $state("");
  let stopping = $state(false);
  let upload = $state<HTMLInputElement>();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;
  const names: Record<string, string> = {
    backup: "创建备份",
    restore: "恢复备份",
    import: "导入备份",
    "workspace-migration": "迁移个人目录",
  };
  let active = $derived(
    busy || (!!operation && ["queued", "running"].includes(operation.status)),
  );
  function size(value: number) {
    return value < 1024
      ? `${value} B`
      : value < 1048576
        ? `${(value / 1024).toFixed(1)} KB`
        : `${(value / 1048576).toFixed(1)} MB`;
  }
  async function load() {
    const [storage, items] = await Promise.all([
      api.get<StorageInfo>("/storage"),
      api.get<BackupInfo[]>("/backups"),
    ]);
    if (disposed) return;
    info = storage;
    backups = items;
    if (!operation && storage.operations.length) follow(storage.operations[0]);
  }
  function follow(value: StorageOperation) {
    if (disposed) return;
    operation = value;
    clearTimeout(timer);
    if (["queued", "running"].includes(value.status))
      timer = setTimeout(async () => {
        try {
          const result = await api.get<StorageOperation>(
            `/storage/operations/${value.id}`,
          );
          follow(result);
          if (result.status === "done") {
            await load();
            await refresh();
            notify("数据操作完成，原档已按规则保留");
          }
        } catch (e) {
          if (!disposed)
            error =
              e instanceof Error
                ? e.message
                : "暂时无法读取进度，请刷新页面恢复查看";
        }
      }, 1000);
  }
  onMount(() => {
    void load().catch((e) => (error = e.message));
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  });
  async function run(work: () => Promise<void>) {
    if (busy || active || app.busy) return;
    busy = true;
    error = "";
    try {
      await work();
    } catch (e) {
      error = e instanceof Error ? e.message : "操作失败，原数据已保留";
    } finally {
      if (!disposed) busy = false;
    }
  }
  async function pick(root = false) {
    await run(async () => {
      const value = await api.post<{ path: string | null }>(
        "/storage/pick-directory",
      );
      if (value.path) {
        if (root) nextRoot = value.path;
        else target = value.path;
      }
    });
  }
  async function migrate() {
    if (
      !target.trim() ||
      !confirm("将当前账号记录复制到新目录并核验后切换？原目录会保留。")
    )
      return;
    await run(async () => {
      follow(
        await api.post<StorageOperation>("/storage/migrate", {
          path: target.trim(),
        }),
      );
    });
  }
  async function createBackup() {
    await run(async () => follow(await api.post<StorageOperation>("/backups")));
  }
  async function restore(id: string) {
    if (
      !confirm(
        "恢复到新的个人工作区并切换？当前记录将保留为旧档案，不会合并覆盖。",
      )
    )
      return;
    await run(async () =>
      follow(
        await api.post<StorageOperation>("/backups/restore", { backup_id: id }),
      ),
    );
  }
  async function importFile(file: File | undefined) {
    if (!file || !confirm("将此备份导入当前账号的新工作区？现有数据会保留。"))
      return;
    await run(async () => {
      const form = new FormData();
      form.append("file", file);
      follow(await api.post<StorageOperation>("/backups/import", form));
    });
    if (upload) upload.value = "";
  }
  async function open(path: string) {
    try {
      await api.post("/storage/open", { path });
    } catch (e) {
      error = e instanceof Error ? e.message : "无法打开目录";
    }
  }
  async function stop() {
    if (
      !confirm(
        "停止本机 FitTrack？已提交的 AI 任务会正常结束，之后需通过启动入口重新运行。",
      )
    )
      return;
    await run(async () => {
      await api.post("/local/stop");
      stopping = true;
    });
  }
  async function migrateRoot() {
    if (
      !nextRoot.trim() ||
      !confirm(
        "将整个应用根目录复制迁移到新位置？服务会重启并要求重新登录；原根目录保留。",
      )
    )
      return;
    await run(async () => {
      await api.post("/local/root-migration", { path: nextRoot.trim() });
      stopping = true;
    });
  }
</script>

<section class="panel storage-panel">
  <div class="section-heading">
    <div>
      <span class="eyebrow">YOUR DATA, YOUR PLACE</span>
      <h3><HardDrive size={19} />存储位置与数据管理</h3>
    </div>
    <span class="badge subtle"
      >{app.runtime?.mode === "local"
        ? "本机受控根目录"
        : "服务器独立空间"}</span
    >
  </div>
  {#if error}<p class="goal-error" role="alert">{error}</p>{/if}
  {#if stopping}<div class="info-note">
      服务正在停止或切换目录。根目录迁移成功后会自动打开新页面；普通停止后请使用启动快捷方式再次运行。
    </div>{/if}
  {#if info}
    <div class="storage-root">
      <span><ShieldCheck size={17} />所有应用运行数据集中于</span><strong
        >{info.root}</strong
      >{#if app.runtime?.open_directory && app.user?.is_admin}<button
          type="button"
          class="text-link"
          onclick={() => open("root")}
          >打开根目录 <FolderOpen size={14} /></button
        >{/if}
    </div>
    <div class="storage-personal">
      <div>
        <span class="small muted"
          >我的健康工作区 · {size(info.workspace_bytes)}</span
        ><strong>{info.workspace}</strong>
      </div>
      {#if app.runtime?.open_directory}<button
          type="button"
          class="secondary"
          onclick={() => open("workspace")}
          ><FolderOpen size={15} />打开我的目录</button
        >{/if}
    </div>
    <details class="storage-paths">
      <summary>查看账号库、密钥、日志、临时文件及备份位置</summary>
      <div class="storage-path-row">
        <span>账号库 / 加密凭据</span><code>{info.account_db}</code>
      </div>
      <div class="storage-path-row">
        <span>主加密密钥</span><code>{info.key_file}</code>
      </div>
      {#each info.areas as area}<div class="storage-path-row">
          <span>{area.label}<small>{size(area.bytes)}</small></span><code
            >{area.path}</code
          >
        </div>{/each}
    </details>
    <p class="small muted">
      业务文件只写入以上根目录。浏览器的登录 Cookie、缓存以及 Windows
      自身记录由浏览器和系统管理。
    </p>
    {#if app.runtime?.migrate_workspace}<div class="storage-section">
        <h4><Database size={17} />更改我的健康记录目录</h4>
        <p class="small muted">
          选择根目录内的空子目录。复制并核验后切换，原目录保留。
        </p>
        <div class="storage-location">
          <input
            aria-label="个人数据目录"
            bind:value={target}
            placeholder="例如 records/my-health，或根目录内绝对路径"
          /><button
            type="button"
            class="secondary"
            disabled={active}
            onclick={() => pick()}>选择文件夹</button
          ><button
            type="button"
            class="primary"
            disabled={active || !target.trim()}
            onclick={migrate}>复制迁移 <ArrowRight size={15} /></button
          >
        </div>
      </div>{/if}
    <div class="storage-section">
      <div class="section-heading">
        <h4><Archive size={17} />我的备份</h4>
        <div class="storage-buttons">
          <button
            type="button"
            class="secondary"
            disabled={active || stopping}
            onclick={createBackup}><Archive size={15} />创建备份</button
          ><button
            type="button"
            class="secondary"
            disabled={active || stopping}
            onclick={() => upload?.click()}><Upload size={15} />导入备份</button
          >{#if app.runtime?.open_directory}<button
              type="button"
              class="text-link"
              onclick={() => open("backups")}>打开备份目录</button
            >{/if}
        </div>
      </div>
      <input
        class="visually-hidden"
        type="file"
        accept=".zip"
        bind:this={upload}
        onchange={(e) => void importFile(e.currentTarget.files?.[0])}
      />
      <p class="small muted">
        备份只含当前账号的健康记录与照片，不包含密码、API Key
        或主密钥。本机备份直接写入根目录，不会自动下载到系统下载文件夹。
      </p>
      {#if backups.length}<div class="backup-list">
          {#each backups as backup}<div>
              <span
                ><strong
                  >{new Date(backup.created_at * 1000).toLocaleString(
                    "zh-CN",
                  )}</strong
                ><small>{backup.name} · {size(backup.size)}</small></span
              ><button
                type="button"
                class="text-link"
                disabled={active || stopping}
                onclick={() => restore(backup.id)}>恢复到新工作区</button
              >{#if app.runtime?.mode === "server"}<a
                  href={`/api/backups/${backup.id}/download`}>下载</a
                >{/if}
            </div>{/each}
        </div>{:else}<p class="small muted">
          还没有备份，记录一段时间后可以在这里创建。
        </p>{/if}
    </div>
    {#if operation}<div class="storage-operation" aria-live="polite">
        <strong
          >{#if ["queued", "running"].includes(operation.status)}<LoaderCircle
              size={16}
              class="spin"
            />{/if}{names[operation.kind] || operation.kind} · {operation.status ===
          "done"
            ? "已完成"
            : operation.status === "failed" ||
                operation.status === "interrupted"
              ? "未完成"
              : `${operation.progress}%`}</strong
        >{#if operation.error}<p class="goal-error">
            {operation.error}
          </p>{/if}<progress max="100" value={operation.progress}></progress>
      </div>{/if}
    {#if info.archives.length || info.legacy_paths.length}<details
        class="storage-paths"
      >
        <summary>保留的旧档案位置（不再写入）</summary
        >{#each [...info.archives, ...info.legacy_paths] as path}<code
            class="retained-path">{path}</code
          >{/each}
      </details>{/if}
    {#if app.runtime?.migrate_root}<div class="storage-section">
        <h4><HardDrive size={17} />迁移整个应用根目录</h4>
        <p class="small muted">
          仅本机管理员操作。包含账号、加密凭据、所有工作区和备份，完成后重启服务并重新登录。请选独立空目录。
        </p>
        <div class="storage-location">
          <input
            aria-label="新应用根目录"
            bind:value={nextRoot}
            placeholder="新根目录的绝对路径"
          /><button
            type="button"
            class="secondary"
            disabled={active || stopping}
            onclick={() => pick(true)}>选择文件夹</button
          ><button
            type="button"
            class="secondary"
            disabled={active || stopping || !nextRoot.trim()}
            onclick={migrateRoot}>迁移根目录</button
          >
        </div>
      </div>{/if}
    {#if app.runtime?.stop_service}<div class="storage-stop">
        <span class="small muted"
          >关闭网页后，后台仍会运行。需要退出时在这里停止。</span
        ><button
          type="button"
          class="secondary"
          disabled={active || stopping}
          onclick={stop}><Power size={15} />停止本机服务</button
        >
      </div>{/if}
  {:else}<p class="muted">正在读取存储位置…</p>{/if}
</section>
