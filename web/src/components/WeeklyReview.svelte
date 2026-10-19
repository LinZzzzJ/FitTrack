<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { Sparkles, CalendarDays, Check, LoaderCircle } from "@lucide/svelte";
  import { api } from "../lib/api";
  import { app, number, perform } from "../lib/state.svelte";
  import { shiftDate } from "../lib/tracking";
  import type { Job, WeeklyStatus } from "../lib/types";
  let status = $state<WeeklyStatus | null>(null);
  let week = $state("");
  let error = $state("");
  let submitting = $state(false);
  let reading = $state(false);
  let disposed = false;
  let generation = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let review = $derived(status?.report?.result?.review);
  let statistics = $derived(status?.report?.result?.statistics);
  let pending = $derived(submitting || !!status?.active_job);
  async function load() {
    const current = ++generation;
    clearTimeout(timer);
    reading = true;
    try {
      const value = await api.get<WeeklyStatus>(
        `/weekly-review${week ? `?week_start=${week}` : ""}`,
      );
      if (disposed || current !== generation) return;
      status = value;
      week = value.week_start;
      error = "";
      if (value.active_job) timer = setTimeout(() => void load(), 1000);
    } catch (e) {
      if (!disposed && current === generation)
        error = e instanceof Error ? e.message : "无法读取每周复盘";
    } finally {
      if (!disposed && current === generation) reading = false;
    }
  }
  onMount(() => () => {
    disposed = true;
    generation++;
    clearTimeout(timer);
  });
  $effect(() => {
    const day = app.day;
    if (day) untrack(() => void load());
  });
  async function generate() {
    if (!status?.can_generate || pending || app.busy) return;
    const selected = status;
    submitting = true;
    await perform(async () => {
      await api.post<Job>("/jobs", {
        kind: "weekly_review",
        date: selected.week_end,
        week_start: selected.week_start,
        request_key: crypto.randomUUID(),
      });
    }, "周复盘已开始，可切换页面后回来查看");
    if (!disposed) {
      submitting = false;
      await load();
    }
  }
</script>

<section class="panel weekly-review" aria-label="每周 AI 复盘">
  <div class="section-heading">
    <div>
      <span class="eyebrow">A WEEK WORTH REFLECTING ON</span>
      <h3><Sparkles size={19} />每周 AI 复盘</h3>
    </div>
    {#if status}<label class="weekly-picker"
        >选择周次<select
          aria-label="周复盘周期"
          bind:value={week}
          onchange={() => {
            status = null;
            void load();
          }}
          >{#each status.available_weeks as start}<option value={start}
              >{start} — {shiftDate(start, 6)}</option
            >{/each}</select
        ></label
      >{/if}
  </div>
  {#if error}<p class="goal-error" role="alert">{error}</p>
    <button type="button" class="text-button" onclick={() => void load()}
      >重新读取</button
    >{/if}
  {#if status}
    <div class="weekly-period">
      <span
        ><CalendarDays size={16} />第 {status.week_number} 周 · {status.week_start}
        至 {status.week_end}</span
      ><span class="badge" class:success={status.completed_days === 7}
        >完整记录 {status.completed_days}/7 天</span
      >
    </div>
    <p class="small muted">
      每期连续七天都要有已确认饮食并完成当日记录；没有训练可作为休息日。仅点击生成时调用
      AI。
    </p>
    {#if !status.closed}<div class="info-note">
        本周尚未结束，最早 {status.earliest_generation_date} 可生成。记录时间不足一周，暂时无法分析。
      </div>{:else if status.missing_dates.length}<div class="info-note">
        记录还不完整，暂时无法生成。请补齐以下日期并点击“仅完成今日记录”。
      </div>{/if}
    {#if status.missing_dates.length}<details class="weekly-missing">
        <summary>查看缺失日期（{status.missing_dates.length} 天）</summary
        >{#each status.missing_dates as missing}<p>
            {missing.date} · {missing.reasons.join("、")}
          </p>{/each}
      </details>{/if}
    {#if !app.ai?.api_key_set}<p class="small muted">
        生成前请在个人设置填写自己的 Key；已有报告可继续查看。
      </p>{/if}
    {#if status.latest_job && ["failed", "interrupted"].includes(status.latest_job.status)}<p
        class="goal-error"
      >
        {status.latest_job.error || "本次分析未完成"}；已有成功报告仍保留。
      </p>{/if}
    {#if review && statistics}
      {#if status.report?.result?.stale}<p class="goal-stale">
          本周记录已变化，下面保留生成时的报告与统计，可手动重新分析。
        </p>{/if}
      <div class="coach-metrics weekly-metrics">
        <div>
          <span>日均已记录摄入</span><strong
            >{number(statistics.average_intake_kcal)}<small>
              kcal</small
            ></strong
          >
        </div>
        <div>
          <span>实际训练</span><strong
            >{statistics.training_sessions}<small>
              次 / {statistics.training_days} 天</small
            ></strong
          >
        </div>
        <div>
          <span>估计周缺口</span><strong
            >{number(statistics.deficit_total_kcal)}<small> kcal</small></strong
          >
        </div>
      </div>
      <p class="feedback-summary">{review.summary}</p>
      <div class="weekly-findings">
        <div>
          <h4>饮食与营养</h4>
          {#each review.diet_findings as value}<p>
              <Check size={13} />{value}
            </p>{/each}
        </div>
        <div>
          <h4>训练与恢复</h4>
          {#each review.training_findings as value}<p>
              <Check size={13} />{value}
            </p>{/each}
        </div>
      </div>
      <div class="weekly-next">
        <h4>下一周，可以这样安排</h4>
        {#each review.next_week_plan as value}<p>{value}</p>{/each}
      </div>
      {#if review.limitations.length}<details class="weekly-missing">
          <summary>本次分析的依据与局限</summary
          >{#each review.limitations as value}<p>{value}</p>{/each}
        </details>{/if}
      {#if status.report}<p class="small muted">
          生成于 {new Date(status.report.created_at * 1000).toLocaleString(
            "zh-CN",
            { timeZone: "Asia/Shanghai" },
          )} · 查看报告不会重复调用 AI
        </p>{/if}
    {/if}
    <button
      class="primary"
      disabled={!status.can_generate ||
        pending ||
        app.busy ||
        reading ||
        !app.ai?.api_key_set}
      onclick={generate}
      >{#if pending}<LoaderCircle
          size={16}
          class="spin"
        />正在生成周复盘…{:else}<Sparkles size={16} />{status.report
          ? "重新分析本周"
          : "生成本周分析"}{/if}</button
    >
  {:else if !error}<p class="small muted">正在读取本周记录…</p>{/if}
</section>
