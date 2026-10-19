<script lang="ts">
  import { onMount } from "svelte";
  import {
    Dumbbell,
    Plus,
    CalendarDays,
    ChevronLeft,
    ChevronRight,
    Pencil,
    Trash2,
    Check,
    Flame,
    Timer,
    Activity,
  } from "@lucide/svelte";
  import Modal from "../components/Modal.svelte";
  import CardioAssistant from "../components/CardioAssistant.svelte";
  import { api } from "../lib/api";
  import {
    app,
    number,
    perform,
    selectDate,
    notify,
    shiftDate,
  } from "../lib/state.svelte";
  import type { Workout, Plan } from "../lib/types";
  let draft = $state<Workout | null>(null),
    planDraft = $state<Plan | null>(null),
    deleting = $state<{ kind: "workouts" | "plans"; id: string } | null>(null);
  let month = $state(""),
    monthPlans = $state<Plan[]>([]);
  const intensityNames = {
    light: "轻强度",
    moderate: "中等强度",
    vigorous: "高强度",
  };
  let calendarDays = $derived.by(() => {
    if (!month) return [];
    const first = new Date(month + "-01T12:00:00Z");
    const offset = (first.getUTCDay() + 6) % 7;
    const start = shiftDate(month + "-01", -offset);
    return Array.from({ length: 42 }, (_, index) => shiftDate(start, index));
  });
  let selectedMet = $derived(
    draft
      ? (draft.met ??
          app.activities.find((activity) => activity.id === draft?.activity)
            ?.mets[draft.intensity] ??
          0)
      : 0,
  );
  let calculatedVolume = $derived(
    draft?.exercises.reduce(
      (sum, exercise) =>
        sum +
        exercise.sets.reduce(
          (total, set) =>
            total + (Number(set.reps) || 0) * (Number(set.weight_kg) || 0),
          0,
        ),
      0,
    ) || 0,
  );
  onMount(() => {
    month = app.date.slice(0, 7);
  });
  async function loadMonth() {
    const selected = month;
    if (!selected) return;
    const end = new Date(selected + "-01T12:00:00Z");
    end.setUTCMonth(end.getUTCMonth() + 1);
    end.setUTCDate(0);
    try {
      const result = await api.get<Plan[]>(
        `/plans?start=${selected}-01&end=${end.toISOString().slice(0, 10)}`,
      );
      if (month === selected) monthPlans = result;
    } catch (error) {
      notify(error instanceof Error ? error.message : "无法读取训练排期", true);
    }
  }
  $effect(() => {
    const current = month;
    const day = app.day;
    if (current && day) void loadMonth();
  });
  function monthShift(amount: number) {
    const value = new Date(month + "-01T12:00:00Z");
    value.setUTCMonth(value.getUTCMonth() + amount);
    month = value.toISOString().slice(0, 7);
  }
  function openWorkout(existing?: Workout, plan?: Plan) {
    draft = {
      date: plan?.date || app.date,
      title: plan?.title || "力量训练",
      kind: plan?.kind || "strength",
      activity: plan?.activity || "strength",
      duration_minutes: plan?.duration_minutes || 45,
      intensity: plan?.intensity || "moderate",
      met: null,
      net_kcal_override: null,
      exercises: [],
      note: plan?.note || "",
      plan_id: plan?.id || null,
      ai_estimate_job_id: null,
    };
    if (existing)
      draft = {
        id: existing.id,
        date: existing.date,
        title: existing.title,
        kind: existing.kind,
        activity: existing.activity,
        duration_minutes: existing.duration_minutes,
        intensity: existing.intensity,
        met: existing.met,
        net_kcal_override: existing.net_kcal_override,
        exercises: structuredClone($state.snapshot(existing.exercises)),
        note: existing.note,
        plan_id: existing.plan_id,
        ai_estimate_job_id: existing.ai_estimate_job_id || null,
      };
  }
  function openPlan(existing?: Plan) {
    planDraft = {
      date: app.date,
      title: "",
      kind: "strength",
      activity: "strength",
      duration_minutes: 45,
      intensity: "moderate",
      status: "planned",
      note: "",
    };
    if (existing)
      planDraft = {
        id: existing.id,
        date: existing.date,
        title: existing.title,
        kind: existing.kind,
        activity: existing.activity,
        duration_minutes: existing.duration_minutes,
        intensity: existing.intensity,
        status: existing.status === "completed" ? "planned" : existing.status,
        note: existing.note,
      };
  }
  async function saveWorkout(event: SubmitEvent) {
    event.preventDefault();
    if (!draft) return;
    const { id, ...payload } = $state.snapshot(draft);
    payload.met ??= null;
    payload.net_kcal_override ??= null;
    if (
      await perform(
        () =>
          id
            ? api.put(`/workouts/${id}`, payload)
            : api.post("/workouts", payload),
        "训练已记录",
      )
    ) {
      draft = null;
      await loadMonth();
    }
  }
  async function savePlan(event: SubmitEvent) {
    event.preventDefault();
    if (!planDraft) return;
    const { id, ...payload } = $state.snapshot(planDraft);
    if (
      await perform(
        () =>
          id ? api.put(`/plans/${id}`, payload) : api.post("/plans", payload),
        "训练排期已保存",
      )
    ) {
      planDraft = null;
      await loadMonth();
    }
  }
  function kindChanged() {
    if (draft) {
      draft.activity = draft.kind === "strength" ? "strength" : "running";
      draft.title = draft.kind === "strength" ? "力量训练" : "有氧训练";
      draft.met = null;
      draft.net_kcal_override = null;
      draft.ai_estimate_job_id = null;
      if (draft.kind === "cardio") draft.exercises = [];
    }
  }
</script>

<div class="page-intro">
  <div>
    <span class="eyebrow">SHOW UP FOR YOURSELF</span>
    <h2>训练有节奏，进步有记录。</h2>
    <p>记录实际运动，也为下一次训练留好时间。</p>
  </div>
  <div class="button-group">
    <button class="secondary" onclick={() => openPlan()}
      ><CalendarDays size={17} />添加排期</button
    ><button class="primary" onclick={() => openWorkout()}
      ><Plus size={17} />记录训练</button
    >
  </div>
</div>
<div class="metrics-grid three-metrics">
  <div class="metric-card">
    <span class="metric-icon sage"><Timer size={20} /></span>
    <div>
      <span class="muted">今日训练时长</span><strong
        >{number(app.day?.duration_minutes)}<small>min</small></strong
      >
    </div>
  </div>
  <div class="metric-card">
    <span class="metric-icon amber"><Flame size={20} /></span>
    <div>
      <span class="muted">运动净消耗</span><strong
        >{number(app.day?.exercise_kcal)}<small>kcal</small></strong
      >
    </div>
  </div>
  <div class="metric-card">
    <span class="metric-icon blue"><Dumbbell size={20} /></span>
    <div>
      <span class="muted">力量训练量</span><strong
        >{number(app.day?.volume_kg)}<small>kg × 次</small></strong
      >
    </div>
  </div>
</div>
<div class="two-columns training-grid">
  <section class="panel">
    <div class="section-heading">
      <div>
        <span class="eyebrow">PLAN YOUR CONSISTENCY</span>
        <h3>训练日历</h3>
      </div>
      <div class="month-switch">
        <button
          class="icon-button"
          aria-label="上个月"
          onclick={() => monthShift(-1)}><ChevronLeft size={16} /></button
        ><strong>{month.replace("-", " 年 ")} 月</strong><button
          class="icon-button"
          aria-label="下个月"
          onclick={() => monthShift(1)}><ChevronRight size={16} /></button
        >
      </div>
    </div>
    <div class="calendar-week">
      {#each ["一", "二", "三", "四", "五", "六", "日"] as weekday}<span
          >{weekday}</span
        >{/each}
    </div>
    <div class="calendar-grid">
      {#each calendarDays as day}<button
          class="calendar-day"
          class:outside={!day.startsWith(month)}
          class:selected={day === app.date}
          class:today={day === app.today}
          onclick={() => void selectDate(day)}
          ><span>{Number(day.slice(8))}</span>{#each monthPlans
            .filter((plan) => plan.date === day)
            .slice(0, 2) as plan}<small
              class:complete={plan.status === "completed"}
              class:skipped={plan.status === "skipped"}>{plan.title}</small
            >{/each}</button
        >{/each}
    </div>
    <div class="calendar-legend">
      <span><i></i>待训练</span><span><i class="done"></i>已完成</span><span
        ><i class="skipped"></i>已跳过</span
      >
    </div>
  </section>
  <section class="panel">
    <div class="section-heading">
      <h3>{app.date} 的安排</h3>
      <button class="text-button" onclick={() => openPlan()}
        ><Plus size={15} />添加</button
      >
    </div>
    {#each app.day?.plans || [] as plan}<div class="plan-card">
        <div>
          <span class="badge" class:success={plan.status === "completed"}
            >{plan.status === "completed"
              ? "已完成"
              : plan.status === "skipped"
                ? "已跳过"
                : "待训练"}</span
          >
          <h4>{plan.title}</h4>
          <p>
            {plan.kind === "strength" ? "力量" : "有氧"} · {plan.duration_minutes}
            分钟 · {intensityNames[plan.intensity]}
          </p>
        </div>
        <div class="button-group">
          {#if plan.status === "planned"}<button
              class="secondary small-button"
              onclick={() => openWorkout(undefined, plan)}
              ><Check size={14} />记录此次训练</button
            >{/if}<button
            class="icon-button"
            aria-label="编辑排期"
            onclick={() => openPlan(plan)}><Pencil size={15} /></button
          >{#if !plan.workout_id}<button
              class="icon-button danger"
              aria-label="删除排期"
              onclick={() => (deleting = { kind: "plans", id: plan.id! })}
              ><Trash2 size={15} /></button
            >{/if}
        </div>
      </div>{:else}<div class="empty-mini">
        <CalendarDays size={32} /><strong>为下一次训练，留一个位置。</strong>
        <p>选择日期并添加排期，完成后再记录实际训练。</p>
      </div>{/each}
    <div class="info-note">
      排期不会计入消耗。实际训练可以修改时长、强度与动作，确认后计入记录。
    </div>
  </section>
</div>
<section class="panel">
  <div class="section-heading">
    <div>
      <span class="eyebrow">THE WORK YOU PUT IN</span>
      <h3>今日实际训练</h3>
    </div>
  </div>
  {#each app.day?.workouts || [] as workout}<article class="workout-card">
      <div class="workout-heading">
        <span class="metric-icon sage"
          >{#if workout.kind === "strength"}<Dumbbell
              size={22}
            />{:else}<Activity size={22} />{/if}</span
        >
        <div>
          <h4>{workout.title}</h4>
          <p>
            {workout.duration_minutes} 分钟 · {intensityNames[
              workout.intensity
            ]} · MET {number(
              workout.energy?.met,
              1,
            )}{#if workout.ai_estimate_job_id}
              · AI 辅助{/if}
          </p>
        </div>
        <strong
          >{number(workout.energy?.net_kcal)}<small> kcal 净消耗</small></strong
        ><button
          class="icon-button"
          aria-label="编辑训练"
          onclick={() => openWorkout(workout)}><Pencil size={16} /></button
        ><button
          class="icon-button danger"
          aria-label="删除训练"
          onclick={() => (deleting = { kind: "workouts", id: workout.id! })}
          ><Trash2 size={16} /></button
        >
      </div>
      {#if workout.exercises.length}<div class="exercise-summary">
          {#each workout.exercises as exercise}<div>
              <strong>{exercise.name}</strong><span
                >{exercise.sets
                  .map((set) => `${set.weight_kg} kg × ${set.reps} 次`)
                  .join(" / ")}</span
              >
            </div>{/each}
        </div>{/if}
      <div class="small muted">
        估计总消耗 {number(workout.energy?.gross_kcal)} kcal · 净消耗已扣除该时段静息能量
        · {workout.note || "每组重量按总外加重量记录"}
      </div>
      {#if workout.energy?.ai_stale}<p class="small goal-stale">
          AI 估算的身体资料已变化；热量已按当前有效资料重算，可重新估算。
        </p>{/if}
    </article>{:else}<div class="empty-mini">
      <Dumbbell size={30} /><strong>每次到场，都算数。</strong>
      <p>记录一次实际训练，开始积累你的训练量。</p>
    </div>{/each}
</section>
{#if draft}<Modal
    title={draft.id ? "修改实际训练" : "记录一次训练"}
    wide
    onclose={() => (draft = null)}
    ><form onsubmit={saveWorkout}>
      <div class="form-grid">
        <label
          >训练日期<input type="date" bind:value={draft.date} required /></label
        ><label
          >训练名称<input
            bind:value={draft.title}
            maxlength="100"
            required
          /></label
        ><label
          >训练类别<select aria-label="训练类别" bind:value={draft.kind} onchange={kindChanged}
            ><option value="strength">力量训练</option><option value="cardio"
              >有氧训练</option
            ></select
          ></label
        ><label
          >运动类型<select aria-label="运动类型" bind:value={draft.activity}
            >{#each app.activities.filter((activity) => activity.kind === draft!.kind) as activity}<option
                value={activity.id}>{activity.name}</option
              >{/each}</select
          ></label
        ><label
          >实际时长 <span
            >{draft.kind === "cardio"
              ? "分钟，总时长含休息"
              : "分钟，含组间休息"}</span
          ><input
            type="number"
            min="1"
            max="1440"
            step="0.5"
            bind:value={draft.duration_minutes}
            required
          /></label
        ><label
          >运动强度<select aria-label="运动强度" bind:value={draft.intensity}
            >{#each Object.entries(intensityNames) as [value, label]}<option
                {value}>{label}</option
              >{/each}</select
          ></label
        ><label
          >手动 MET <span>可选</span><input
            type="number"
            min="1"
            max="25"
            step="0.1"
            bind:value={draft.met}
            placeholder={`按类型使用 ${selectedMet}`}
          /></label
        ><label
          >运动净消耗覆盖 <span>kcal，可选</span><input
            type="number"
            min="0"
            max="10000"
            step="1"
            bind:value={draft.net_kcal_override}
            placeholder="例如设备显示的活动热量"
          /></label
        >
      </div>
      {#if draft.kind === "strength"}<div
          class="section-heading exercise-title"
        >
          <h3>动作与组记录</h3>
          <span class="muted small"
            >训练量 {number(calculatedVolume)} kg × 次</span
          >
        </div>
        {#each draft.exercises as exercise, index}<div class="exercise-editor">
            <div class="food-row-title">
              <input
                aria-label="动作名称"
                bind:value={exercise.name}
                maxlength="100"
                placeholder="例如：深蹲 / 卧推 / 引体向上"
                required
              /><button
                type="button"
                class="icon-button danger"
                aria-label="移除动作"
                onclick={() => draft!.exercises.splice(index, 1)}
                ><Trash2 size={16} /></button
              >
            </div>
            {#each exercise.sets as set, setIndex}<div class="set-row">
                <span>第 {setIndex + 1} 组</span><label
                  >总外加重量 / kg<input
                    type="number"
                    min="0"
                    max="1000"
                    step="0.5"
                    bind:value={set.weight_kg}
                    required
                  /></label
                ><label
                  >次数<input
                    type="number"
                    min="1"
                    max="1000"
                    step="1"
                    bind:value={set.reps}
                    required
                  /></label
                ><button
                  type="button"
                  class="icon-button danger"
                  aria-label="移除训练组"
                  disabled={exercise.sets.length <= 1}
                  onclick={() => exercise.sets.splice(setIndex, 1)}
                  ><Trash2 size={14} /></button
                >
              </div>{/each}<button
              type="button"
              class="text-button"
              onclick={() => exercise.sets.push({ weight_kg: 0, reps: 10 })}
              ><Plus size={14} />加一组</button
            >
          </div>{/each}<button
          type="button"
          class="secondary"
          onclick={() =>
            draft!.exercises.push({
              name: "",
              sets: [{ weight_kg: 0, reps: 10 }],
            })}><Plus size={16} />添加动作</button
        >
        <p class="small muted">
          双手器械填写合计外加重量；自重动作填 0
          kg，另统计组数和次数。热量按整次训练时长估算。
        </p>{/if}<label
        >{draft.kind === "cardio" ? "自定义运动描述" : "训练备注"}<textarea
          aria-label={draft.kind === "cardio" ? "自定义运动描述" : "训练备注"}
          bind:value={draft.note}
          maxlength="2000"
          rows="2"
          placeholder={draft.kind === "cardio"
            ? "例如：羽毛球双打60分钟，其中休息20分钟，实际打球约40分钟"
            : "例如：状态不错，最后一组比较吃力"}></textarea></label
      >
      {#if draft.kind === "cardio"}
        <p class="small muted">
          类型参考 MET {number(
            app.activities.find((value) => value.id === draft!.activity)?.mets[
              draft.intensity
            ],
            1,
          )} ·
          <a
            href={app.activities.find((value) => value.id === draft!.activity)
              ?.source}
            target="_blank"
            rel="noreferrer">运动参考依据</a
          >{#if draft.activity === "badminton"}
            · 休闲 5.5 / 竞技 7.0 / 比赛 9.0{/if}
        </p>
        <CardioAssistant bind:workout={draft} />
      {/if}
      <div class="modal-footer">
        <span class="small muted"
          >MET {number(selectedMet, 1)} · 结合当日体重估算</span
        ><button class="primary" disabled={app.busy}
          ><Check size={16} />保存训练</button
        >
      </div>
    </form></Modal
  >{/if}
{#if planDraft}<Modal
    title={planDraft.id ? "编辑训练排期" : "安排一次训练"}
    onclose={() => (planDraft = null)}
    ><form onsubmit={savePlan}>
      <label
        >训练日期<input
          type="date"
          bind:value={planDraft.date}
          required
        /></label
      ><label
        >排期名称<input
          bind:value={planDraft.title}
          maxlength="100"
          required
          placeholder="例如：周三上肢力量"
        /></label
      >
      <div class="form-grid">
        <label
          >训练类别<select
            bind:value={planDraft.kind}
            onchange={() => {
              if (planDraft)
                planDraft.activity =
                  planDraft.kind === "strength" ? "strength" : "running";
            }}
            ><option value="strength">力量</option><option value="cardio"
              >有氧</option
            ></select
          ></label
        ><label
          >运动类型<select bind:value={planDraft.activity}
            >{#each app.activities.filter((activity) => activity.kind === planDraft!.kind) as activity}<option
                value={activity.id}>{activity.name}</option
              >{/each}</select
          ></label
        ><label
          >计划时长 / 分钟<input
            type="number"
            min="1"
            max="1440"
            bind:value={planDraft.duration_minutes}
            required
          /></label
        ><label
          >强度<select bind:value={planDraft.intensity}
            >{#each Object.entries(intensityNames) as [value, label]}<option
                {value}>{label}</option
              >{/each}</select
          ></label
        >
      </div>
      <label
        >状态<select bind:value={planDraft.status}
          ><option value="planned">待训练</option><option value="skipped"
            >跳过</option
          ></select
        ></label
      ><label
        >备注<textarea bind:value={planDraft.note} maxlength="2000" rows="2"
        ></textarea></label
      >
      <div class="form-actions">
        <button class="primary" disabled={app.busy}>保存排期</button>
      </div>
    </form></Modal
  >{/if}
{#if deleting}<Modal
    title="删除这条训练记录？"
    onclose={() => (deleting = null)}
    ><p>
      {deleting.kind === "workouts"
        ? "当天消耗与训练量会重新汇总，关联排期恢复待完成。"
        : "删除后，该安排将从日历移除。"}
    </p>
    <div class="form-actions">
      <button class="secondary" onclick={() => (deleting = null)}>取消</button
      ><button
        class="danger-button"
        disabled={app.busy}
        onclick={async () => {
          if (
            await perform(
              () => api.delete(`/${deleting?.kind}/${deleting?.id}`),
              "记录已删除",
            )
          ) {
            deleting = null;
            await loadMonth();
          }
        }}>确认删除</button
      >
    </div></Modal
  >{/if}
