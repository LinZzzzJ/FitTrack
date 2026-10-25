<script lang="ts">
  import { onMount } from "svelte";
  import {
    apiOrigin,
    chooseLocalMode,
    mobileConnection,
    normalizeServer,
    saveMobileConnection,
  } from "../lib/mobile";
  import { init, notify, refresh } from "../lib/state.svelte";
  import {
    readHealth,
    mutate,
    meta,
    outbox,
    setMeta,
    scope,
  } from "../lib/repository";
  import { readArchive, writeArchive } from "../lib/health-archive";
  import {
    getImageBytes,
    putImageBytes,
    shareFile,
    validateImage,
  } from "../lib/mobile-files";
  import { syncNow, syncStatus } from "../lib/sync";
  import { nativeRequest } from "../lib/mobile-network";
  import {
    identifier,
    tableNames,
    validateTables,
    type Table,
  } from "../lib/health";
  import { canonical, type Data } from "../lib/ledger";
  let busy = $state(false),
    error = $state(""),
    status = $state(""),
    pending = $state(0),
    lastSync = $state(""),
    server = $state(apiOrigin()),
    code = $state(""),
    conflicts = $state<Data[]>([]),
    retained = $state<string[]>([]);
  let fileInput: HTMLInputElement;
  async function update() {
    status = syncStatus.message;
    pending = (await outbox()).length;
    lastSync = await meta("last-sync", "");
    conflicts = await meta("conflicts", []);
    retained = await meta("retained-index", []);
  }
  onMount(() => {
    void update();
    const listener = () => void update();
    window.addEventListener("fittrack-sync", listener);
    return () => window.removeEventListener("fittrack-sync", listener);
  });
  async function run(work: () => Promise<void>) {
    if (busy) return;
    busy = true;
    error = "";
    try {
      await work();
      await update();
    } catch (e) {
      error = e instanceof Error ? e.message : "操作失败，原数据已保留";
    } finally {
      busy = false;
    }
  }
  async function backup() {
    await run(async () => {
      const h = await readHealth();
      const blob = await writeArchive(h.tables, (index) =>
        getImageBytes(index, h.storageScope),
      );
      await shareFile(
        "fittrack-health-" + new Date().toISOString().slice(0, 10) + ".zip",
        new Uint8Array(await blob.arrayBuffer()),
      );
    });
  }
  async function importFile(file: File | undefined) {
    if (!file) return;
    await run(async () => {
      const h = await readHealth();
      if (h.rows("jobs").some((j) => ["queued", "running"].includes(j.status)))
        throw new Error("请等待本地 AI 任务结束后再导入档案");
      const tables = await readArchive(
        file,
        h.owner,
        async (i, b) => putImageBytes(b, i, h.storageScope),
        validateImage,
      );
      const counts = tableNames
        .map((t) => `${t}: ${tables[t].length}`)
        .join("\n");
      if (
        !confirm(
          "导入以下健康记录并切换到新档案？当前记录将保留为历史档案。\n" +
            counts,
        )
      )
        return;
      if (
        mobileConnection() &&
        !confirm(
          "当前连接服务器。导入后将作为当前账号的修改同步到服务器，是否继续？",
        )
      )
        return;
      if ((await scope()) !== h.storageScope)
        throw new Error("账号或模式已切换，请在原空间重新导入");
      const id = identifier();
      const context={namespace:h.storageScope,owner:h.owner};
      await setMeta("retained-" + id, h.tables,context);
      await setMeta("retained-index", [id, ...retained],context);
      await mutate((current) => {
        current.tables = tables;
      },context);
      await refresh();
      notify("健康 ZIP 已导入；原档案已保留");
    });
    if (fileInput) fileInput.value = "";
  }
  async function exportRetained(id: string) {
    await run(async () => {
      const tables = await meta<any>("retained-" + id, null);
      if (!tables) throw new Error("历史档案不存在");
      const blob = await writeArchive(tables, getImageBytes);
      await shareFile(
        "fittrack-retained-" + id + ".zip",
        new Uint8Array(await blob.arrayBuffer()),
      );
    });
  }
  async function pair() {
    await run(async () => {
      const base = normalizeServer(server);
      if (!/^\d{8}$/.test(code)) throw new Error("请输入8位配对码");
      if (
        pending &&
        !confirm(
          "当前账号还有未同步修改。切换账号后这些修改仍保存在原服务器/账号空间；是否继续？",
        )
      )
        return;
      const result = await nativeRequest(
        "POST",
        base + "/api/mobile/pair/redeem",
        { code },
        { "Content-Type": "application/json" },
      );
      await saveMobileConnection(base, result.token, result.user);
      await init();
      await syncNow(true);
      code = "";
      notify("已连接服务器，原本机记录仍保留");
    });
  }
  async function local() {
    await run(async () => {
      if (
        pending &&
        !confirm(
          `还有 ${pending} 项修改未同步。切回本机模式会保留原服务器账号的修改，重新配对同一账号后继续同步。是否继续？`,
        )
      )
        return;
      await chooseLocalMode();
      await init();
      notify("已切换本机记录空间");
    });
  }
  async function exportConflict(c: Data) {
    await shareFile(
      "fittrack-conflict-" + c.id + ".json",
      new TextEncoder().encode(canonical(c)),
    );
  }
  async function adoptConflict(c: Data) {
    await run(async () => {
      if (
        !confirm(
          "将保留的本机版本作为一次新的修改同步？服务器版本仍在冲突副本中保留。",
        )
      )
        return;
      const [table, key] = c.resource.split("/") as [Table, string];
      await mutate((h) => {
        h.tables[table] = h
          .rows(table)
          .filter((row) => (row.id || row.date) !== key);
        if (c.local) h.rows(table).push({ ...c.local, user_id: h.owner });
        validateTables(h.tables, h.owner);
      });
      await syncNow(true);
      await refresh();
    });
  }
</script>

<section class="panel storage-panel">
  <div class="section-heading">
    <div>
      <span class="eyebrow">YOUR DATA, YOUR CHOICE</span>
      <h3>本机与服务器</h3>
    </div>
    <span class="badge"
      >{mobileConnection() ? "服务器与本机副本" : "仅保存在本机"}</span
    >
  </div>
  {#if error}<p class="goal-error" role="alert">{error}</p>{/if}
  {#if mobileConnection()}<p>
      {apiOrigin()} · {mobileConnection()?.user.username}
    </p>
    <p class="small muted">
      {status || "等待同步"} · 待同步 {pending} 项 {lastSync
        ? "· 最近 " + new Date(lastSync).toLocaleString("zh-CN")
        : ""}
    </p>
    <div class="form-actions">
      <button
        class="secondary"
        disabled={busy}
        onclick={() => void run(() => syncNow(true))}>立即同步</button
      ><button class="secondary" disabled={busy} onclick={() => void local()}
        >切回本机空间</button
      >
    </div>{/if}
  <details>
    <summary>连接或重新配对服务器</summary>
    <p class="small muted">
      在 PC
      网页设置生成配对码。不同服务器和账号使用独立本机空间；本机空间的数据可通过健康
      ZIP 手动导入。
    </p>
    <form
      onsubmit={(e) => {
        e.preventDefault();
        void pair();
      }}
    >
      <label
        >HTTPS 服务器<input
          type="url"
          bind:value={server}
          required
          placeholder="https://fittrack.example.com"
        /></label
      ><label
        >8位配对码<input
          bind:value={code}
          inputmode="numeric"
          minlength="8"
          maxlength="8"
          pattern="[0-9]{8}"
          required
        /></label
      ><button class="secondary" disabled={busy}>连接</button>
    </form>
  </details>
</section>
<section class="panel storage-panel">
  <div class="section-heading">
    <h3>PC / Android 健康备份</h3>
    <span class="badge">ZIP v1 / v2</span>
  </div>
  <p class="muted">
    导入 PC 导出的个人健康
    ZIP，包含身体、饮食、照片、训练、排期和模板。导出文件可恢复到 PC；密码、AI
    Key 和设备令牌不会进入备份。
  </p>
  <div class="form-actions">
    <button class="secondary" disabled={busy} onclick={() => void backup()}
      >导出健康 ZIP</button
    ><button class="secondary" disabled={busy} onclick={() => fileInput.click()}
      >导入 PC 健康 ZIP</button
    >
  </div>
  <input
    class="visually-hidden"
    type="file"
    accept=".zip,application/zip"
    bind:this={fileInput}
    onchange={(e) => void importFile(e.currentTarget.files?.[0])}
  />
  {#if retained.length}<details>
      <summary>导入前保留的历史档案（{retained.length}）</summary
      >{#each retained as id}<button
          class="text-button"
          disabled={busy}
          onclick={() => void exportRetained(id)}
          >导出原档案 {id.slice(0, 8)}</button
        >{/each}
    </details>{/if}
</section>
{#if conflicts.length}<section class="panel storage-panel">
    <h3>同步冲突副本</h3>
    <p class="muted">
      同一字段被同时修改时保留双方内容，当前采用服务器值。可导出副本或把本机版本作为新的修改。
    </p>
    {#each conflicts as c}<div class="storage-personal">
        <span>{c.resource}</span><button
          class="secondary"
          disabled={busy}
          onclick={() => void exportConflict(c)}>导出双方副本</button
        ><button
          class="secondary"
          disabled={busy}
          onclick={() => void adoptConflict(c)}>采用本机版本</button
        >
      </div>{/each}
  </section>{/if}
