<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { Sparkles, Check, LoaderCircle, RotateCcw } from "@lucide/svelte";
  import { api } from "../lib/api";
  import { app, number, perform, notify } from "../lib/state.svelte";
  import type { CardioInput, Day, Job, Workout } from "../lib/types";
  let { workout = $bindable() }: { workout: Workout } = $props();
  let job = $state<Job | null>(null);
  let previous = $state<Job | null>(null);
  let busy = $state(false);
  let error = $state("");
  let disposed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const input = (): CardioInput => ({
    kind: "cardio",
    activity: workout.activity,
    duration_minutes: workout.duration_minutes,
    intensity: workout.intensity,
    description: workout.note || "",
  });
  const signature = (
    day: string,
    data: CardioInput | undefined,
    kind = "cardio",
  ) =>
    JSON.stringify([
      day,
      kind,
      data?.activity,
      data?.duration_minutes,
      data?.intensity,
      data?.description || "",
    ]);
  let currentKey = $derived(signature(workout.date, input(), workout.kind));
  let result = $derived(
    job?.status === "done" ? job.result?.estimate : undefined,
  );
  let stale = $derived(
    !!job &&
      (job.result?.stale ||
        currentKey !== signature(job.date, job.request.cardio_input)),
  );
  let pending = $derived(
    busy || (!!job && ["queued", "running"].includes(job.status)),
  );
  let adopted = $derived(
    !!job && workout.ai_estimate_job_id === job.id && !stale,
  );
  function follow(value: Job) {
    if (disposed) return;
    clearTimeout(timer);
    job = value;
    if (["queued", "running"].includes(value.status))
      timer = setTimeout(() => void read(value.id), 1000);
  }
  async function read(id: string) {
    try {
      const value = await api.get<Job>(`/jobs/${id}`);
      if (!job || job.id === id) follow(value);
    } catch (e) {
      if (!disposed)
        error = e instanceof Error ? e.message : "无法读取估算任务";
    }
  }
  onMount(() => {
    if (workout.ai_estimate_job_id) void read(workout.ai_estimate_job_id);
    else
      void api
        .get<Day>(`/days/${workout.date}`)
        .then((day) => {
          if (disposed || job) return;
          const candidate = day.jobs.find(
            (value) => value.kind === "cardio_estimate",
          );
          if (
            candidate &&
            signature(candidate.date, candidate.request.cardio_input) ===
              currentKey
          )
            follow(candidate);
          else previous = candidate || null;
        })
        .catch((e) => {
          if (!disposed) error = e.message;
        });
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  });
  $effect(() => {
    const day = app.day;
    if (day)
      untrack(() => {
        if (job?.status === "done") void read(job.id);
      });
  });
  $effect(() => {
    if (
      job &&
      result &&
      workout.ai_estimate_job_id === job.id &&
      (currentKey !== signature(job.date, job.request.cardio_input) ||
        workout.met !== result.effective_met ||
        workout.net_kcal_override != null)
    ) {
      workout.ai_estimate_job_id = null;
    }
  });
  async function generate() {
    if (pending || workout.kind !== "cardio") return;
    error = "";
    await perform(
      async () =>
        follow(
          await api.post<Job>("/jobs", {
            kind: "cardio_estimate",
            date: workout.date,
            request_key: crypto.randomUUID(),
            cardio_input: input(),
          }),
        ),
      "有氧估算已开始，结果需采用并保存",
    );
  }
  async function adopt() {
    if (!job || busy || stale) return;
    busy = true;
    error = "";
    try {
      const fresh = await api.get<Job>(`/jobs/${job.id}`);
      if (disposed) return;
      follow(fresh);
      if (
        fresh.result?.stale ||
        signature(fresh.date, fresh.request.cardio_input) !== currentKey ||
        workout.kind !== "cardio"
      )
        throw new Error("估算依据已变化，请重新估算");
      if (!fresh.result?.estimate || fresh.status !== "done")
        throw new Error("估算尚未完成");
      workout.met = fresh.result.estimate.effective_met;
      workout.net_kcal_override = null;
      workout.ai_estimate_job_id = fresh.id;
      notify("估算已填入，保存训练后才计入消耗");
    } catch (e) {
      error = e instanceof Error ? e.message : "无法采用估算";
    } finally {
      if (!disposed) busy = false;
    }
  }
  function restore() {
    if (!previous?.request.cardio_input) return;
    const values = previous.request.cardio_input;
    workout.date = previous.date;
    workout.activity = values.activity;
    workout.duration_minutes = values.duration_minutes;
    workout.intensity = values.intensity;
    workout.note = values.description;
    workout.met = null;
    workout.net_kcal_override = null;
    workout.ai_estimate_job_id = null;
    follow(previous);
    previous = null;
  }
</script>

<section class="coach-card" aria-label="有氧 AI 估算">
  <div class="section-heading">
    <div>
      <span class="eyebrow">MOVE WITH A LITTLE GUIDANCE</span>
      <h3><Sparkles size={17} />AI 估算有氧消耗</h3>
    </div>
    <button
      type="button"
      class="secondary"
      disabled={pending || app.busy || !app.ai?.api_key_set}
      onclick={generate}
      >{#if pending}<LoaderCircle
          size={15}
          class="spin"
        />估算中…{:else}<Sparkles size={15} />{result
          ? "重新估算消耗"
          : "AI 估算消耗"}{/if}</button
    >
  </div>
  <p class="small muted">
    结合运动类型、总时长、强度和上方描述估计整段平均强度。先预览、再采用，保存训练后计入当天。
  </p>
  {#if !app.ai?.api_key_set}<p class="small muted">
      请先在个人设置填写自己的 Key；仍可使用类型参考或手动 MET。
    </p>{/if}
  {#if previous}<button
      type="button"
      class="text-button"
      disabled={app.busy || pending}
      onclick={restore}
      ><RotateCcw size={14} />恢复上次有氧估算的输入与结果</button
    >{/if}
  {#if error}<p class="goal-error" role="alert">{error}</p>{/if}
  {#if workout.ai_estimate_job_id && !result && !pending}<button
      type="button"
      class="text-button"
      onclick={() => { workout.ai_estimate_job_id = null; }}
      >改用手动 MET</button
    >{/if}
  {#if job?.status === "failed" || job?.status === "interrupted"}<p
      class="goal-error"
    >
      {job.error || "估算未完成，可以手动重试"}
    </p>{/if}
  {#if result}
    <div class="coach-metrics">
      <div>
        <span>运动净消耗</span><strong
          >{number(result.net_kcal)}<small> kcal</small></strong
        >
      </div>
      <div>
        <span>估计总消耗</span><strong
          >{number(result.gross_kcal)}<small> kcal</small></strong
        >
      </div>
      <div>
        <span>整段平均 MET</span><strong
          >{number(result.effective_met, 2)}</strong
        >
      </div>
    </div>
    <p class="coach-rationale">{result.rationale}</p>
    <p class="small muted">
      参考体重 {number(result.weight_kg, 1)} kg · 静息 {number(
        result.resting_kcal,
      )} kcal/天 · 净消耗已扣除该时段静息能量
    </p>
    {#if result.assumptions.length}<details class="goal-assumptions">
        <summary>估算假设</summary>{#each result.assumptions as value}<p>
            {value}
          </p>{/each}
      </details>{/if}
    {#if stale}<p class="goal-stale">
        运动输入或身体资料已变化，旧估算不能采用，请重新生成。
      </p>{/if}
    <p class="small muted">采用后会替换当前 MET，并清空手动净消耗覆盖值。</p>
    <div class="form-actions">
      <button
        type="button"
        class="primary"
        disabled={pending || app.busy || stale || adopted}
        onclick={adopt}
        ><Check size={15} />{adopted ? "已采用估算" : "采用估算"}</button
      >
      {#if workout.ai_estimate_job_id}<button
          type="button"
          class="text-button"
          onclick={() => {
            workout.ai_estimate_job_id = null;
          }}>改用手动 MET</button
        >{/if}
    </div>
  {/if}
</section>
