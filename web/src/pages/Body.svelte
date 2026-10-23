<script lang="ts">
  import { Scale, Plus, Trash2, Heart, Save, ArrowRight } from "@lucide/svelte";
  import Chart from "../components/Chart.svelte";
  import Modal from "../components/Modal.svelte";
  import { api } from "../lib/api";
  import { app, number, perform, navigate } from "../lib/state.svelte";
  import { lineOptions } from "../lib/charts";
  import { TRACKING_START } from "../lib/tracking";
  import type { BodyRecord } from "../lib/types";
  let record = $state<BodyRecord>({
    date: "",
    weight_kg: null,
    body_fat_pct: null,
    resting_kcal: null,
    note: "",
  });
  let deleting = $state<string | null>(null);
  let bodySourceKey = "";
  $effect(() => {
    const body = app.day?.body;
    const key = app.date + JSON.stringify(body);
    if (key !== bodySourceKey) {
      bodySourceKey = key;
      record = {
        date: app.date,
        weight_kg: body?.weight_kg ?? null,
        body_fat_pct: body?.body_fat_pct ?? null,
        resting_kcal: body?.resting_kcal ?? null,
        note: body?.note ?? "",
      };
    }
  });
  let weightChart = $derived(
    lineOptions(
      app.trends.map((row) => row.date),
      [
        {
          name: "体重",
          values: app.trends.map((row) => row.body?.weight_kg ?? null),
        },
        {
          name: "七日均值",
          values: app.trends.map((row) => row.weight_average_7d),
          color: "#b3c4a9",
          dashed: true,
        },
      ],
      "kg",
    ),
  );
  let fatChart = $derived(
    lineOptions(
      app.trends.map((row) => row.date),
      [
        {
          name: "体脂率",
          values: app.trends.map((row) => row.body?.body_fat_pct ?? null),
          color: "#dea64e",
        },
      ],
      "%",
    ),
  );
  async function save(event: SubmitEvent) {
    event.preventDefault();
    await perform(
      () =>
        api.put("/body", {
          ...record,
          date: app.date,
          weight_kg: record.weight_kg ?? null,
          body_fat_pct: record.body_fat_pct ?? null,
          resting_kcal: record.resting_kcal ?? null,
        }),
      "身体数据已保存",
    );
  }
</script>

<div class="page-intro">
  <div>
    <span class="eyebrow">MORE THAN A NUMBER</span>
    <h2>身体的变化，慢慢看。</h2>
    <p>记录趋势，也给自己一点耐心。体脂可以留空。</p>
  </div>
</div>
<div class="two-columns body-top">
  <section class="panel">
    <div class="section-heading">
      <h3><Scale size={19} />今日身体记录</h3>
      <span class="badge subtle">{app.date}</span>
    </div>
    <form onsubmit={save}>
      <div class="form-grid">
        <label
          >体重 <span>kg</span><input
            aria-label="每日体重"
            type="number"
            min="20"
            max="350"
            step="0.1"
            bind:value={record.weight_kg}
            placeholder="例如 75.2"
          /></label
        ><label
          >体脂率 <span>%，可选</span><input
            aria-label="每日体脂率"
            type="number"
            min="0.1"
            max="70"
            step="0.1"
            bind:value={record.body_fat_pct}
            placeholder="暂时没有也没关系"
          /></label
        >
      </div>
      <label
        >当日静息能量 <span>kcal，可选覆盖</span><input
          type="number"
          min="500"
          max="5000"
          step="1"
          bind:value={record.resting_kcal}
          placeholder="留空使用个人资料中的平均值"
        /></label
      ><label
        >记录备注<textarea
          bind:value={record.note}
          maxlength="1000"
          rows="2"
          placeholder="例如：晨起空腹，训练后有些疲劳"></textarea></label
      >
      <div class="form-actions">
        <button class="primary" disabled={app.busy}
          ><Save size={16} />保存身体记录</button
        >{#if app.day?.body}<button
            type="button"
            class="text-button danger"
            onclick={() => (deleting = app.date)}
            ><Trash2 size={15} />删除当日测量</button
          >{/if}
      </div>
    </form>
  </section>
  <section class="panel profile-card">
    <span class="metric-icon sage"><Heart size={23} /></span><span
      class="eyebrow">YOUR STARTING POINT</span
    >
    <h3>每个人都有自己的节奏</h3>
    {#if app.day?.profile}<div class="profile-facts">
        <div>
          <span>身高</span><strong
            >{number(app.day.profile.height_cm, 1)}<small> cm</small></strong
          >
        </div>
        <div>
          <span>参考体重</span><strong
            >{number(app.day.effective_weight_kg, 1)}<small> kg</small></strong
          >
        </div>
        <div>
          <span>平均静息能量</span><strong
            >{number(app.day.profile.resting_kcal ?? app.day.profile.estimated_resting_kcal)}<small> kcal{app.day.profile.resting_kcal == null ? " 估算" : ""}</small></strong
          >
        </div>
        <div>
          <span>目标体重</span><strong
            >{number(app.day.profile.target_weight_kg, 1)}<small>
              kg</small
            ></strong
          >
        </div>
      </div>{:else}<p class="muted">
        先填写身高、初始体重，以及年龄或设备静息能量。
      </p>{/if}<button class="text-button" onclick={() => navigate("settings")}
      >管理个人资料与目标<ArrowRight size={16} /></button
    >
    <p class="small muted">
      体重会随饮水、进食和训练波动。七日均值帮助你观察长期方向。
    </p>
  </section>
</div>
{#if app.date < TRACKING_START}<div class="info-note">
    趋势统计从 {TRACKING_START} 开始；仍可在上方补录和修改所选日期的身体记录。
  </div>{/if}
<div class="two-columns">
  <section class="panel">
    <div class="section-heading">
      <h3>体重趋势</h3>
      <span class="muted small">{TRACKING_START} 起</span>
    </div>
    <Chart option={weightChart} label="每日体重与七日均值" />
  </section>
  <section class="panel">
    <div class="section-heading">
      <h3>体脂趋势</h3>
      <span class="muted small">{TRACKING_START} 起 · 未测量日期留空</span>
    </div>
    <Chart option={fatChart} label="体脂率变化" />
  </section>
</div>
<section class="panel">
  <div class="section-heading">
    <h3>测量记录</h3>
    <span class="muted small">在顶部选择日期可补录或修改</span>
  </div>
  <div class="table-wrap">
    <table>
      <thead
        ><tr
          ><th>日期</th><th>体重</th><th>体脂率</th><th>当日静息能量</th><th
            >备注</th
          ></tr
        ></thead
      ><tbody
        >{#each app.trends.filter((row) => row.body).reverse() as row}<tr
            ><td>{row.date}</td><td>{number(row.body?.weight_kg, 1)} kg</td><td
              >{number(row.body?.body_fat_pct, 1)} %</td
            ><td>{number(row.body?.resting_kcal)} kcal</td><td
              >{row.body?.note || "—"}</td
            ></tr
          >{:else}<tr
            ><td colspan="5" class="table-empty"
              ><Plus size={18} />还没有测量记录，保存一次就会出现在这里。</td
            ></tr
          >{/each}</tbody
      >
    </table>
  </div>
</section>
{#if deleting}<Modal title="删除这次测量？" onclose={() => (deleting = null)}
    ><p>删除 {deleting} 的身体测量后，运动估算将使用之前最近的体重。</p>
    <div class="form-actions">
      <button class="secondary" onclick={() => (deleting = null)}>取消</button
      ><button
        class="danger-button"
        disabled={app.busy}
        onclick={async () => {
          if (
            await perform(
              () => api.delete(`/body/${deleting}`),
              "测量记录已删除",
            )
          )
            deleting = null;
        }}>确认删除</button
      >
    </div></Modal
  >{/if}
