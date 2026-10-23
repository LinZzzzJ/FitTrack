<script lang="ts">
  import { onMount } from "svelte";
  import {
    UserRound,
    Target,
    Sparkles,
    Save,
    ShieldCheck,
    LoaderCircle,
    Check,
  } from "@lucide/svelte";
  import { api } from "../lib/api";
  import { app, perform, notify, number } from "../lib/state.svelte";
  import type { AIConfig, Profile, Day, Job } from "../lib/types";
  import DataManagement from "../components/DataManagement.svelte";
  type ProfileForm = Omit<
    Profile,
    | "height_cm"
    | "initial_weight_kg"
    | "resting_kcal"
    | "age"
    | "estimated_resting_kcal"
    | "estimated_maintenance_kcal"
  > & {
    height_cm: number | null;
    initial_weight_kg: number | null;
    age: number | null;
    resting_kcal: number | null;
  };
  const defaults: ProfileForm = {
    effective_date: "",
    height_cm: null,
    initial_weight_kg: null,
    body_fat_pct: null,
    sex: "male",
    age: null,
    resting_kcal: null,
    activity_factor: 1.2,
    activity_level: "sedentary",
    target_weight_kg: null,
    calorie_target: null,
    protein_target_g: null,
    carbs_target_g: null,
    fat_target_g: null,
  };
  let profile = $state<ProfileForm>({ ...defaults });
  function profilePayload() {
    const raw = $state.snapshot(profile) as Profile;
    const { estimated_resting_kcal: _resting, estimated_maintenance_kcal: _daily, ...payload } =
      raw;
    return Object.fromEntries(
      Object.entries(payload).map(([key, value]) => [key, value === undefined ? null : value]),
    );
  }
  let profileForm: HTMLFormElement;
  let goalJob = $state<Job | null>(null);
  let submittingGoal = $state(false);
  let adoptingGoal = $state(false);
  let goalError = $state("");
  let disposed = false;
  let goalTimer: ReturnType<typeof setTimeout> | undefined;
  let goalPending = $derived(
    submittingGoal ||
      (!!goalJob && ["queued", "running"].includes(goalJob.status)),
  );
  let goal = $derived(
    goalJob?.status === "done" ? goalJob.result?.goals : undefined,
  );
  let goalAdopted = $derived(
    !!goal &&
      profile.calorie_target === goal.calorie_target &&
      profile.protein_target_g === goal.protein_target_g &&
      profile.carbs_target_g === goal.carbs_target_g &&
      profile.fat_target_g === goal.fat_target_g,
  );
  function goalSignature(value: Partial<ProfileForm> | undefined) {
    return JSON.stringify([
      value?.height_cm,
      value?.initial_weight_kg,
      value?.body_fat_pct ?? null,
      value?.sex,
      value?.age,
      value?.resting_kcal,
      value?.activity_factor,
      value?.activity_level,
      value?.target_weight_kg,
    ]);
  }
  const activityLevels = [
    ["sedentary", "久坐", 1.2],
    ["light", "轻度活动", 1.375],
    ["moderate", "中度活动", 1.55],
    ["high", "高度活动", 1.725],
    ["very_active", "非常活跃", 1.9],
  ] as const;
  let estimatedResting = $derived.by(() => {
    if (!profile.initial_weight_kg || !profile.height_cm || !profile.age) return null;
    const offset = profile.sex === "male" ? 5 : profile.sex === "female" ? -161 : -78;
    return Math.round(
      10 * profile.initial_weight_kg + 6.25 * profile.height_cm - 5 * profile.age + offset,
    );
  });
  let effectiveActivityLevel = $derived(
    profile.activity_level ||
      activityLevels.reduce((best, current) =>
        Math.abs(current[2] - profile.activity_factor) <
        Math.abs(best[2] - profile.activity_factor)
          ? current
          : best,
      )[0],
  );
  let goalStale = $derived(
    !!goal &&
      (goalJob?.result?.stale ||
        goalJob?.date !== app.today ||
        goalSignature(profile) !==
          goalSignature(goalJob?.request.goal_profile)),
  );
  let macroEnergy = $derived(
    goal
      ? goal.protein_target_g * 4 +
          goal.carbs_target_g * 4 +
          goal.fat_target_g * 9
      : 0,
  );
  let macroShares = $derived(
    goal
      ? [
          {
            name: "蛋白质",
            grams: goal.protein_target_g,
            percent: ((goal.protein_target_g * 4) / macroEnergy) * 100,
            color: "#247052",
          },
          {
            name: "碳水",
            grams: goal.carbs_target_g,
            percent: ((goal.carbs_target_g * 4) / macroEnergy) * 100,
            color: "#dca345",
          },
          {
            name: "脂肪",
            grams: goal.fat_target_g,
            percent: ((goal.fat_target_g * 9) / macroEnergy) * 100,
            color: "#789bae",
          },
        ]
      : [],
  );
  function followGoal(job: Job) {
    if (disposed) return;
    clearTimeout(goalTimer);
    goalJob = job;
    goalError = "";
    if (["queued", "running"].includes(job.status)) {
      goalTimer = setTimeout(() => void refreshGoal(job.id), 1500);
    }
  }
  async function refreshGoal(id = goalJob?.id) {
    if (!id) return;
    try {
      const job = await api.get<Job>(`/jobs/${id}`);
      if (!disposed && (!goalJob || goalJob.id === id)) followGoal(job);
    } catch (error) {
      if (!disposed)
        goalError = error instanceof Error ? error.message : "暂时无法获取进度";
    }
  }
  onMount(() => {
    void api
      .get<Day>(`/days/${app.today}`)
      .then((day) => {
        const last = day.jobs.find((job) => job.kind === "goals");
        if (last && !goalJob) followGoal(last);
      })
      .catch(() => {});
    return () => {
      disposed = true;
      clearTimeout(goalTimer);
    };
  });
  async function generateGoal() {
    if (goalPending || app.busy || adoptingGoal) return;
    if (!profileForm.reportValidity()) return;
    if (!profile.target_weight_kg) {
      notify("请先填写目标体重", true);
      return;
    }
    submittingGoal = true;
    goalError = "";
    try {
      const job = await api.post<Job>("/jobs", {
        kind: "goals",
        date: app.today,
        goal_profile: profilePayload(),
        request_key: crypto.randomUUID(),
      });
      followGoal(job);
    } catch (error) {
      if (!disposed)
        goalError = error instanceof Error ? error.message : "生成失败，请重试";
    } finally {
      if (!disposed) submittingGoal = false;
    }
  }
  async function adoptGoal() {
    if (!goal || goalStale || !goalJob || adoptingGoal) return;
    adoptingGoal = true;
    try {
      const id = goalJob.id;
      const job = await api.get<Job>(`/jobs/${id}`);
      if (disposed || goalJob?.id !== id) return;
      followGoal(job);
      if (
        job.result?.stale ||
        goalSignature(profile) !== goalSignature(job.request.goal_profile)
      ) {
        notify("身体记录或目标已变化，请重新生成建议", true);
        return;
      }
      const suggestion = job.result?.goals;
      if (!suggestion) return;
      profile.calorie_target = suggestion.calorie_target;
      profile.protein_target_g = suggestion.protein_target_g;
      profile.carbs_target_g = suggestion.carbs_target_g;
      profile.fat_target_g = suggestion.fat_target_g;
      notify("AI 建议已填入，可修改后保存");
    } catch (error) {
      if (!disposed)
        goalError = error instanceof Error ? error.message : "暂时无法采用建议";
    } finally {
      if (!disposed) adoptingGoal = false;
    }
  }
  let config = $state({
    base_url: "https://api.deepseek.com",
    api_key: "",
    vision_model: "deepseek-flash",
    coach_model: "deepseek-flash",
    remember: true,
  });
  $effect(() => {
    profile = {
      ...defaults,
      ...(app.profile || {}),
      effective_date: app.today,
    };
  });
  $effect(() => {
    if (app.ai) {
      config.base_url = app.ai.base_url;
      config.vision_model = app.ai.vision_model;
      config.coach_model = app.ai.coach_model;
      config.remember = app.ai.remember ?? true;
    }
  });
  async function saveProfile(event: SubmitEvent) {
    event.preventDefault();
    await perform(async () => {
      const cleaned = profilePayload();
      app.profile = await api.put<Profile>("/profile", cleaned);
    }, "资料与目标已保存");
  }
  async function saveAI(event: SubmitEvent) {
    event.preventDefault();
    await perform(async () => {
      app.ai = await api.put<AIConfig>("/settings", {
        base_url: config.base_url,
        vision_model: config.vision_model,
        coach_model: config.coach_model,
        remember: config.remember,
        ...(config.api_key.trim() ? { api_key: config.api_key.trim() } : {}),
      });
      config.api_key = "";
    }, "AI 配置已保存");
  }
  async function testAI() {
    await perform(async () => {
      const result = await api.post<{ message: string }>(
        "/settings/test-connection",
      );
      notify(result.message);
    }, "");
  }
  async function clearAI() {
    if (!confirm("清除此账号保存的 Key？手动记录不受影响。")) return;
    await perform(async () => {
      await api.delete("/settings/key");
      config.api_key = "";
      if (app.ai)
        app.ai = {
          ...app.ai,
          api_key_set: false,
          credential_scope: "none",
          credential_error: "",
        };
    }, "此账号的 Key 已清除");
  }
</script>

<div class="page-intro">
  <div>
    <span class="eyebrow">BUILT AROUND YOU</span>
    <h2>{app.profile ? "让计划，适合你。" : "先认识一下现在的你。"}</h2>
    <p>可填写设备静息能量，或用身体资料生成估算。</p>
  </div>
</div>
<form onsubmit={saveProfile} bind:this={profileForm}>
  <div class="two-columns">
    <section class="panel">
      <div class="section-heading">
        <h3><UserRound size={19} />个人身体资料</h3>
        <span class="badge subtle">本地保存</span>
      </div>
      <div class="form-grid">
        <label
          >身高 <span>cm</span><input
            aria-label="身高"
            type="number"
            min="90"
            max="240"
            step="0.1"
            bind:value={profile.height_cm}
            required
          /></label
        ><label
          >初始体重 <span>kg</span><input
            aria-label="初始体重"
            type="number"
            min="20"
            max="350"
            step="0.1"
            bind:value={profile.initial_weight_kg}
            required
          /></label
        ><label
          >初始体脂 <span>%，可选</span><input
            type="number"
            min="0.1"
            max="70"
            step="0.1"
            bind:value={profile.body_fat_pct}
            placeholder="可留空"
          /></label
        ><label
          >性别<select bind:value={profile.sex}
            ><option value="male">男</option><option value="female">女</option
            ><option value="other">其他 / 不透露</option></select
          ></label
        ><label
          >年龄 <span>岁</span><input
            aria-label="年龄"
            type="number"
            min="13"
            max="110"
            step="1"
            bind:value={profile.age}
            required={profile.resting_kcal == null}
          /></label
        ><label
          >设备静息能量 <span>kcal / 天，可留空估算</span><input
            aria-label="平均静息能量"
            type="number"
            min="500"
            max="5000"
            bind:value={profile.resting_kcal}
          /></label
        ><label
          >每日活动状态<select
            aria-label="每日活动状态"
            value={effectiveActivityLevel}
            onchange={(event) => {
              const level = activityLevels.find((item) => item[0] === event.currentTarget.value);
              if (level) {
                profile.activity_level = level[0];
                profile.activity_factor = level[2];
              }
            }}
            >{#each activityLevels as [value, label, factor]}<option {value}
                >{label} · ×{factor}</option
              >{/each}</select
          ></label
        >
      </div>
      <div class="info-note">
        {#if estimatedResting != null}按 Mifflin–St Jeor 公式估算静息能量约
          {number(profile.resting_kcal ?? estimatedResting)} kcal / 天。{/if}
        活动状态用于估算日常总消耗，训练消耗仍单独计算。估算仅供参考，可填写设备值覆盖。
      </div>
      <label
        >资料生效日期<input
          type="date"
          bind:value={profile.effective_date}
          required
        /></label
      >
      <p class="small muted">
        更改参数会从生效日期开始影响计算。原有较早日期继续使用历史参数。
      </p>
    </section>
    <section class="panel">
      <div class="section-heading">
        <h3><Target size={19} />饮食与身体目标</h3>
        <button
          type="button"
          class="secondary goal-generate"
          onclick={generateGoal}
          disabled={app.busy ||
            goalPending ||
            adoptingGoal ||
            !app.ai?.api_key_set}
        >
          {#if goalPending}<LoaderCircle
              size={15}
              class="spin"
            />生成中…{:else}<Sparkles size={15} />AI 生成目标{/if}
        </button>
      </div>
      <label
        >目标体重 <span>kg</span><input
          aria-label="目标体重"
          type="number"
          min="20"
          max="350"
          step="0.1"
          bind:value={profile.target_weight_kg}
          placeholder="给长期变化一个方向"
        /></label
      >
      <p class="small muted goal-hint">
        填写目标体重和左侧身体资料，AI 帮你估算每日摄入与营养分配。
      </p>
      <label
        >每日热量目标 <span>kcal</span><input
          aria-label="每日热量目标"
          type="number"
          step="any"
          min="1"
          max="10000"
          bind:value={profile.calorie_target}
          placeholder="由你决定的摄入目标"
        /></label
      >
      <div class="form-grid three">
        <label
          >蛋白质 <span>g</span><input
            aria-label="蛋白质目标"
            type="number"
            step="any"
            min="1"
            max="1000"
            bind:value={profile.protein_target_g}
            placeholder="可选"
          /></label
        ><label
          >碳水 <span>g</span><input
            aria-label="碳水目标"
            type="number"
            step="any"
            min="1"
            max="2000"
            bind:value={profile.carbs_target_g}
            placeholder="可选"
          /></label
        ><label
          >脂肪 <span>g</span><input
            aria-label="脂肪目标"
            type="number"
            step="any"
            min="1"
            max="1000"
            bind:value={profile.fat_target_g}
            placeholder="可选"
          /></label
        >
      </div>
      <div class="goal-ai-status" aria-live="polite">
        {#if goalPending}<p class="info-note">
            <LoaderCircle
              size={15}
              class="spin"
            />正在结合身体数据与近期记录生成建议，切换页面后仍可回来查看。
          </p>{/if}
        {#if goalError}<div class="goal-error">
            <p>{goalError}</p>
            {#if goalPending && !submittingGoal}<button
                type="button"
                class="text-link"
                onclick={() => void refreshGoal()}>刷新状态</button
              >{/if}
          </div>{/if}
        {#if goalJob && ["failed", "interrupted"].includes(goalJob.status)}<p
            class="goal-error"
          >
            {goalJob.error || "生成中断，请点击 AI 生成目标重试。"} 你仍可手动填写目标。
          </p>{/if}
      </div>
      {#if goal}<div class="goal-suggestion">
          <div class="section-heading">
            <h4><Sparkles size={16} />AI 推荐起点</h4>
            <span class="badge" class:warning={goalStale}
              >{goalStale
                ? "资料已变化"
                : goalAdopted
                  ? "已填入"
                  : "待你采用"}</span
            >
          </div>
          <div class="goal-calories">
            <strong>{number(goal.calorie_target)}</strong><span>kcal / 天</span>
          </div>
          <div class="goal-macro-bar" aria-label="推荐营养素供能分配">
            {#each macroShares as macro}<span
                style:width={`${macro.percent}%`}
                style:background={macro.color}
              ></span>{/each}
          </div>
          <div class="goal-macro-values">
            {#each macroShares as macro}<span
                ><i style:background={macro.color}></i>{macro.name}<strong
                  >{number(macro.grams, 1)} g</strong
                ><small>供能 {number(macro.percent)}%</small></span
              >{/each}
          </div>
          <p>{goal.rationale}</p>
          {#if goalJob?.result?.basis}<p class="small muted">
              参考体重 {number(goalJob.result.basis.current_weight_kg, 1)} kg · 估计维持消耗
              {number(goalJob.result.basis.estimated_maintenance_kcal)} kcal / 天
              · 近七天有 {goalJob.result.basis.recorded_training_days_7d} 天训练记录
            </p>{/if}
          {#if goal.assumptions.length}<details>
              <summary>估算依据与假设</summary>
              <ul>
                {#each goal.assumptions as assumption}<li>
                    {assumption}
                  </li>{/each}
              </ul>
            </details>{/if}
          {#if goalStale}<p class="small goal-stale">
              身体资料、记录或目标已变化，请重新生成后采用。
            </p>{/if}
          <button
            type="button"
            class="primary"
            onclick={adoptGoal}
            disabled={app.busy ||
              goalStale ||
              adoptingGoal ||
              goalPending ||
              goalAdopted}
            ><Check size={16} />{adoptingGoal
              ? "核对中…"
              : goalAdopted
                ? "已填入目标"
                : "采用这组目标"}</button
          >
          <span class="small muted"
            >填入后可修改，点击“保存资料与目标”生效。</span
          >
        </div>{:else if !goalPending}<div class="goal-note">
          <Target size={32} /><strong>留一点空间，给长期坚持。</strong>
          <p>
            {app.ai?.api_key_set
              ? "自己填写，或让 AI 提供一个起点。采用建议后仍可修改，保存才会生效。"
              : "AI 尚未配置，可先手动填写目标；在下方保存自己的 Key 后即可生成建议。"}
          </p>
        </div>{/if}
    </section>
  </div>
  <div class="save-bar">
    <span><ShieldCheck size={17} />资料仅属于当前账号</span><button
      class="primary"
      disabled={app.busy}><Save size={17} />保存资料与目标</button
    >
  </div>
</form>
<section class="panel settings-ai">
  <div class="section-heading">
    <div>
      <span class="eyebrow">A LITTLE HELP FROM AI</span>
      <h3><Sparkles size={19} />我的 AI 配置</h3>
    </div>
    <span class="badge" class:success={app.ai?.api_key_set}
      >{app.ai?.api_key_set ? "密钥已配置" : "尚未配置密钥"}</span
    >
  </div>
  <form onsubmit={saveAI}>
    <div class="form-grid">
      <label
        >服务地址 / Base URL<input
          type="url"
          bind:value={config.base_url}
          required
          placeholder="https://api.deepseek.com"
          list="allowed-providers"
        /></label
      ><label
        >API Key<input
          aria-label="API Key"
          type="password"
          autocomplete="off"
          bind:value={config.api_key}
          placeholder={app.ai?.api_key_set
            ? "••••••••（已配置；留空保留）"
            : "输入服务商提供的密钥"}
        /></label
      ><label
        >图片理解模型<input bind:value={config.vision_model} required /></label
      ><label
        >文字建议模型<input bind:value={config.coach_model} required /></label
      >
    </div>
    <datalist id="allowed-providers"
      >{#each app.runtime?.allowed_providers || [] as provider}<option
          value={provider}
        ></option>{/each}</datalist
    >
    <label class="remember-key"
      ><input type="checkbox" bind:checked={config.remember} />记住此账号的 Key</label
    >
    <p class="small muted">
      {config.remember
        ? "加密保存在当前服务的数据根目录，网页不会读回完整 Key。"
        : "仅本次登录有效；退出、会话过期或服务重启后需重新填写。"}
    </p>
    {#if app.ai?.credential_error}<p class="goal-error">
        {app.ai.credential_error}
      </p>{/if}
    <div class="form-actions">
      <button class="secondary" disabled={app.busy}
        ><Save size={16} />保存 AI 配置</button
      ><button
        type="button"
        class="secondary"
        disabled={app.busy || !app.ai?.api_key_set}
        onclick={testAI}>测试连接</button
      >
      <button
        type="button"
        class="text-link danger"
        disabled={app.busy ||
          (!app.ai?.api_key_set && !app.ai?.credential_error)}
        onclick={clearAI}>清除 Key</button
      >
      <span class="small muted"
        >只使用你自己的 Key，由当前连接的后端向 AI
        服务发送必要数据。连接测试不发起付费生成。</span
      >
    </div>
    {#if app.ai?.environment_override}<p class="info-note">
        当前有系统环境变量覆盖配置，保存文件不会改变被覆盖的值。
      </p>{/if}
  </form>
</section>
{#if app.runtime}<DataManagement />{/if}
