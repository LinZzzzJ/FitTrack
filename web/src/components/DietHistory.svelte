<script lang="ts">
  import { onMount, untrack } from "svelte";
  import {
    ChevronLeft,
    ChevronRight,
    Plus,
    Pencil,
    Trash2,
    Utensils,
    Check,
    RotateCcw,
    LoaderCircle,
  } from "@lucide/svelte";
  import { api, imageUrl } from "../lib/api";
  import { app, number } from "../lib/state.svelte";
  import { dietWeek, shiftDate } from "../lib/tracking";
  import type { DietHistory, Meal, Job } from "../lib/types";
  let {
    onedit,
    ondelete,
    ondeletejob,
    onview,
    onretry,
    onmanual,
    onlabel,
    onphoto,
    onadd,
  }: {
    onedit: (meal: Meal) => void;
    ondelete: (meal: Meal) => void;
    ondeletejob: (job: Job) => void;
    onview: (job: Job) => void;
    onretry: (job: Job) => void;
    onmanual: (job: Job) => void;
    onlabel: (job: Job) => void;
    onphoto: (id: string) => void;
    onadd: (day: string) => void;
  } = $props();
  let week = $state(""),
    history = $state<DietHistory | null>(null),
    error = $state(""),
    loading = $state(false);
  let selected = "",
    generation = 0,
    disposed = false;
  let total = $derived(
    history?.days.reduce((sum, day) => sum + day.totals.kcal, 0) || 0,
  );
  const slots = {
    breakfast: "早餐",
    lunch: "午餐",
    dinner: "晚餐",
    snack: "加餐",
  };
  async function load() {
    if (!week) return;
    const token = ++generation;
    loading = true;
    try {
      const value = await api.get<DietHistory>(
        `/diet-history?start=${week}&end=${shiftDate(week, 6)}`,
      );
      if (!disposed && token === generation) {
        history = value;
        error = "";
      }
    } catch (e) {
      if (!disposed && token === generation)
        error = e instanceof Error ? e.message : "无法读取周记录";
    } finally {
      if (!disposed && token === generation) loading = false;
    }
  }
  function move(amount: number) {
    week = shiftDate(week, amount);
    history = null;
    void load();
  }
  $effect(() => {
    const date = app.date;
    const day = app.day;
    if (date && day)
      untrack(() => {
        if (selected !== date) {
          selected = date;
          week = dietWeek(date);
          history = null;
        }
        void load();
      });
  });
  onMount(() => () => {
    disposed = true;
    generation++;
  });
</script>

<section class="panel diet-history" aria-label="每周饮食记录">
  <div class="section-heading">
    <div>
      <span class="eyebrow">EVERY MEAL HAS A PLACE</span>
      <h3>每周饮食记录</h3>
    </div>
    <strong class="total-label"
      >{number(total)}<small> kcal 已记录</small></strong
    >
  </div>
  <div class="diet-week-controls">
    <button class="icon-button" aria-label="饮食上一周" onclick={() => move(-7)}
      ><ChevronLeft size={18} /></button
    ><strong>{week} — {week ? shiftDate(week, 6) : ""}</strong><button
      class="icon-button"
      aria-label="饮食下一周"
      onclick={() => move(7)}><ChevronRight size={18} /></button
    ><button
      class="text-button"
      onclick={() => {
        week = dietWeek(app.date);
        history = null;
        void load();
      }}>返回所选日期所在周</button
    >
  </div>
  <p class="small muted">
    记录长期保留，按10/15起每七天分组。切换周次只改变查看范围；草稿确认后才计入摄入。
  </p>
  {#if error}<p class="goal-error" role="alert">{error}</p>
    <button class="text-button" onclick={() => void load()}
      >重新读取饮食记录</button
    >{/if}
  {#if loading && !history}<p class="small muted">正在读取七天记录…</p>{/if}
  {#each history?.days || [] as day}
    <article
      class="diet-day"
      class:selected={day.date === app.date}
      aria-label={`${day.date}饮食记录`}
    >
      <div class="diet-day-heading">
        <div>
          <strong>{day.date}</strong>{#if day.date === app.today}<span
              class="badge subtle">今天</span
            >{/if}<span class="small muted"
            >{day.meals.length} 餐 · {number(day.totals.kcal)} kcal</span
          >
        </div>
        <button class="text-button" onclick={() => onadd(day.date)}
          ><Plus size={14} />补记本日饮食</button
        >
      </div>
      <div class="meal-cards">
        {#each day.meals as meal}<article class="meal-card">
            {#if meal.image_id}<button
                type="button"
                class="meal-photo-button"
                aria-label="查看已入账餐食原图"
                onclick={() => onphoto(meal.image_id!)}
                ><img
                  class="meal-photo"
                  src={imageUrl(meal.image_id, true)}
                  alt={meal.title || slots[meal.slot]}
                /></button
              >{:else}<div class="meal-photo meal-photo-placeholder">
                <Utensils size={25} />
              </div>{/if}
            <div class="meal-card-body">
              <span class="eyebrow"
                >{slots[meal.slot]} · 已入账{#if meal.nutrition_label}
                  · 标签换算{/if}</span
              >
              <h4>
                {meal.title ||
                  meal.items
                    .map((item) => item.name)
                    .slice(0, 2)
                    .join(" · ")}
              </h4>
              <p>
                {meal.items
                  .map(
                    (item) =>
                      `${item.name} ${number(item.estimated_edible_grams, 1)}g`,
                  )
                  .join(" · ")}
              </p>
              <div class="meal-card-footer">
                <strong
                  >{number(meal.totals?.kcal, 2)}<small> kcal</small></strong
                >
                <div>
                  <button
                    class="icon-button"
                    aria-label="编辑餐食"
                    onclick={() => onedit(meal)}><Pencil size={16} /></button
                  ><button
                    class="icon-button danger"
                    aria-label="删除餐食"
                    onclick={() => ondelete(meal)}><Trash2 size={16} /></button
                  >
                </div>
              </div>
            </div>
          </article>{/each}
      </div>
      {#if !day.meals.length}<p class="diet-day-empty">
          暂无已确认饮食，可补录本日记录。
        </p>{/if}
      {#if day.jobs.length}<div class="job-list">
          <span class="small muted">餐食 AI 分析记录</span>
          {#each day.jobs as job}{@const booked = day.meals.some(
              (meal) => meal.source_job_id === job.id,
            )}
            <div class="job-row">
              {#if job.request.image_id}<button
                  class="job-photo-button"
                  type="button"
                  aria-label="查看任务餐食原图"
                  onclick={() => onphoto(job.request.image_id!)}
                  ><img
                    src={imageUrl(job.request.image_id, true)}
                    alt="任务餐食缩略图"
                  /></button
                >{/if}
              <div>
                <strong
                  >{slots[job.request.slot || "lunch"]} · {job.request
                    .meal_mode === "label"
                    ? "标签"
                    : job.request.meal_description
                      ? job.request.image_id
                        ? "文字+照片"
                        : "文字描述"
                      : "照片"} · {job.status === "done"
                    ? booked
                      ? "已入账"
                      : "待确认"
                    : job.status === "running"
                      ? "正在识别"
                      : job.status === "queued"
                        ? "等待分析"
                        : job.status === "interrupted"
                          ? "任务已中断"
                          : "分析未完成"}</strong
                >
                <p class:job-error={!!job.error}>
                  {job.error || job.request.note || job.request.meal_description || "按照片中可食部分估算"}
                </p>
              </div>
              {#if job.status === "done"}{#if day.meals.some((meal) => meal.source_job_id === job.id)}<span
                    class="badge success"><Check size={13} />已入账</span
                  >{:else}<button class="secondary" onclick={() => onview(job)}
                    >查看并确认草稿</button
                  >{/if}
              {:else if ["failed", "interrupted"].includes(job.status)}<button
                  class="secondary"
                  disabled={app.busy}
                  onclick={() => onretry(job)}
                  ><RotateCcw size={15} />重试</button
                >{#if job.request.meal_mode !== "label" && job.request.image_id}<button
                    class="text-button"
                    disabled={app.busy}
                    onclick={() => onlabel(job)}>按营养标签重试</button
                  >{/if}<button
                  class="text-button"
                  onclick={() => onmanual(job)}>手动补录</button
                >{:else}<LoaderCircle size={18} class="spin" /><span class="small muted"
                  >分析结束后可删除</span
                >{/if}
              <button
                type="button"
                class="icon-button danger"
                aria-label="删除餐食分析记录"
                title={["queued", "running"].includes(job.status)
                  ? "请等待餐食分析结束后再删除记录"
                  : "删除餐食分析记录"}
                disabled={app.busy || ["queued", "running"].includes(job.status)}
                onclick={() => ondeletejob(job)}><Trash2 size={16} /></button
              >
            </div>{/each}
        </div>{/if}
    </article>
  {/each}
</section>
