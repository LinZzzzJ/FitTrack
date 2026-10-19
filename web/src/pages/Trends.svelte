<script lang="ts">
  import { TrendingDown, ChartNoAxesCombined, Dumbbell } from "@lucide/svelte";
  import Chart from "../components/Chart.svelte";
  import { app, number } from "../lib/state.svelte";
  import { TRACKING_START } from "../lib/tracking";
  import { lineOptions, palette } from "../lib/charts";
  import type { EChartsOption } from "echarts";
  const startDate = TRACKING_START;
  let rows = $derived(app.trends);
  let loading = $derived(app.date >= startDate && app.day?.date !== app.date);
  let labels = $derived(rows.map((row) => row.date));
  let weight = $derived(
    lineOptions(
      labels,
      [
        {
          name: "体重",
          values: rows.map((row) => row.body?.weight_kg ?? null),
        },
        {
          name: "七日均值",
          values: rows.map((row) => row.weight_average_7d),
          dashed: true,
          color: "#b4c6af",
        },
      ],
      "kg",
    ),
  );
  let fat = $derived(
    lineOptions(
      labels,
      [
        {
          name: "体脂率",
          values: rows.map((row) => row.body?.body_fat_pct ?? null),
          color: "#dea64e",
        },
      ],
      "%",
    ),
  );
  let calories = $derived(
    lineOptions(
      labels,
      [
        {
          name: "已记录摄入",
          values: rows.map((row) => (row.meal_count ? row.totals.kcal : null)),
        },
        {
          name: "估计消耗",
          values: rows.map((row) => row.expenditure_kcal),
          color: "#dea64e",
        },
        {
          name: "已完成日缺口",
          values: rows.map((row) => (row.completed ? row.deficit_kcal : null)),
          color: "#7899ad",
        },
      ],
      "kcal",
    ),
  );
  let training = $derived<EChartsOption>({
    color: palette,
    tooltip: { trigger: "axis" },
    legend: { bottom: 0, textStyle: { color: "#6b7771" } },
    grid: { left: 52, right: 52, top: 22, bottom: 48 },
    xAxis: {
      type: "category",
      data: labels.map((day) => day.slice(5)),
      axisLabel: { color: "#88948b", fontSize: 10 },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: "#e5e9e3" } },
    },
    yAxis: [
      {
        type: "value",
        name: "分钟",
        splitLine: { lineStyle: { color: "#edf0e9", type: "dashed" } },
        axisLabel: { color: "#88948b", fontSize: 10 },
      },
      {
        type: "value",
        name: "kg × 次",
        splitLine: { show: false },
        axisLabel: { color: "#88948b", fontSize: 10 },
      },
    ],
    series: [
      {
        name: "训练时长",
        type: "bar",
        data: rows.map((row) => row.duration_minutes),
        barMaxWidth: 16,
        itemStyle: { borderRadius: [4, 4, 0, 0] },
      },
      {
        name: "力量训练量",
        type: "line",
        yAxisIndex: 1,
        data: rows.map((row) => row.volume_kg),
        smooth: 0.15,
        symbolSize: 4,
      },
    ],
  });
</script>

<div class="page-intro">
  <div>
    <span class="eyebrow">THE BIGGER PICTURE</span>
    <h2>把日常的小步，连成进步的轨迹。</h2>
    <p>观察趋势，而不是单个数字。缺少测量的日期会保留空白。</p>
  </div>
  <span class="badge subtle" aria-label="趋势统计范围"
    >{startDate} 起{#if app.date >= startDate}
      · 至 {app.date}{/if}</span
  >
</div>
{#if loading}<p class="info-note" role="status">正在读取趋势数据…</p>{/if}
{#if app.date < startDate}<p class="info-note">
    趋势统计从 2026-10-15 开始，请选择该日期或之后的日期。
  </p>{/if}
<div class="two-columns">
  <section class="panel">
    <div class="section-heading">
      <h3><TrendingDown size={18} />体重与七日均值</h3>
      <span class="badge subtle">kg</span>
    </div>
    <Chart option={weight} height={255} label="体重和七日均值折线图" />
  </section>
  <section class="panel">
    <div class="section-heading">
      <h3>体脂率变化</h3>
      <span class="badge subtle">%</span>
    </div>
    <Chart option={fat} height={255} label="体脂率折线图" />
  </section>
</div>
<section class="panel">
  <div class="section-heading">
    <h3><ChartNoAxesCombined size={18} />热量摄入、消耗与缺口</h3>
    <span class="muted small">消耗为估计，摄入以已确认餐食为准</span>
  </div>
  <Chart option={calories} height={270} label="摄入消耗与完成记录的热量缺口" />
</section>
<section class="panel">
  <div class="section-heading">
    <h3><Dumbbell size={18} />训练量与时长</h3>
    <span class="muted small">仅统计实际训练</span>
  </div>
  <Chart
    option={training}
    height={250}
    label="训练时长柱状图和力量训练量折线图"
  />
</section>
<section class="panel">
  <div class="section-heading">
    <h3>每日数据明细</h3>
    <span class="muted small">统计截至 {app.date}</span>
  </div>
  <div class="table-wrap">
    <table>
      <thead
        ><tr
          ><th>日期</th><th>体重 / kg</th><th>体脂 / %</th><th>摄入 / kcal</th
          ><th>估计消耗</th><th>估计缺口</th><th>训练 / min</th><th
            >力量训练量</th
          ><th>状态</th></tr
        ></thead
      ><tbody
        >{#each [...rows].reverse() as row}<tr
            ><td>{row.date}</td><td>{number(row.body?.weight_kg, 1)}</td><td
              >{number(row.body?.body_fat_pct, 1)}</td
            ><td>{row.meal_count ? number(row.totals.kcal) : "—"}</td><td
              >{number(row.expenditure_kcal)}</td
            ><td>{row.meal_count ? number(row.deficit_kcal) : "—"}</td><td
              >{number(row.duration_minutes)}</td
            ><td>{number(row.volume_kg)}</td><td
              ><span class="badge subtle"
                >{row.completed ? "已完成" : "进行中"}</span
              ></td
            ></tr
          >{:else}<tr
            ><td colspan="9">{loading ? "正在读取…" : "此范围暂无趋势数据"}</td
            ></tr
          >{/each}</tbody
      >
    </table>
  </div>
</section>
