<script lang="ts">
  import {
    ArrowRight,
    Plus,
    Scale,
    Flame,
    Dumbbell,
    Sparkles,
    Check,
    TrendingDown,
    Utensils,
  } from "@lucide/svelte";
  import Chart from "../components/Chart.svelte";
  import WeeklyReview from "../components/WeeklyReview.svelte";
  import { api } from "../lib/api";
  import { app, number, navigate, perform } from "../lib/state.svelte";
  import { lineOptions, pieOptions } from "../lib/charts";
  import { TRACKING_START } from "../lib/tracking";
  const slots = {
    breakfast: "早餐",
    lunch: "午餐",
    dinner: "晚餐",
    snack: "加餐",
  };
  let day = $derived(app.day);
  let target = $derived(day?.profile?.calorie_target || 0);
  let intake = $derived(day?.totals.kcal || 0);
  let percentage = $derived(
    target ? Math.min(100, (intake / target) * 100) : 0,
  );
  let remaining = $derived(target - intake);
  let activeFeedback = $derived(
    day?.jobs.some(
      (job) =>
        job.kind === "feedback" && ["queued", "running"].includes(job.status),
    ),
  );
  let weightChart = $derived(
    lineOptions(
      app.trends.map((row) => row.date),
      [
        {
          name: "每日体重",
          values: app.trends.map((row) => row.body?.weight_kg ?? null),
        },
        {
          name: "七日均值",
          values: app.trends.map((row) => row.weight_average_7d),
          color: "#b9c9b1",
          dashed: true,
        },
      ],
      "kg",
    ),
  );
  let macroChart = $derived(
    pieOptions([
      { name: "蛋白质", value: (day?.totals.protein_g || 0) * 4 },
      { name: "碳水", value: (day?.totals.carbs_g || 0) * 4 },
      { name: "脂肪", value: (day?.totals.fat_g || 0) * 9 },
    ]),
  );
  async function complete(generateAI = true) {
    const selectedDate = app.date;
    const useAI = generateAI && app.ai?.api_key_set;
    await perform(
      async () => {
        await api.post(`/days/${selectedDate}/complete`);
        if (useAI)
          await api.post("/jobs", {
            kind: "feedback",
            date: selectedDate,
            request_key: crypto.randomUUID(),
          });
      },
      useAI ? "记录已完成，AI 正在生成建议" : "今日记录已完成",
    );
  }
</script>

{#if day}
  <div class="dashboard-hero">
    <div class="hero-copy">
      <span class="eyebrow light">MAKE ROOM FOR A HEALTHIER YOU</span>
      <h2>把改变，交给每天。</h2>
      <p>认真吃饭，好好训练。每个小记录，都在靠近更好的自己。</p>
      <button class="hero-button" onclick={() => navigate("meals")}
        ><Plus size={17} />记录这一餐<ArrowRight size={16} /></button
      ><span class="hero-watermark" aria-hidden="true">fit.</span>
    </div>
    <div class="budget-card">
      <div>
        <span class="eyebrow">TODAY'S ENERGY</span>
        <h3>今日热量预算</h3>
        <span class="badge subtle"
          >{day.completed ? "今日已完成" : "记录进行中"}</span
        >
      </div>
      <div class="budget-content">
        <div class="budget-ring" style:--progress="{percentage}%">
          <div><strong>{number(intake)}</strong><span>已摄入 kcal</span></div>
        </div>
        <div class="budget-detail">
          <span class="muted"
            >{target
              ? remaining >= 0
                ? "目标剩余"
                : "超出目标"
              : "每日目标"}</span
          ><strong
            >{target ? number(Math.abs(remaining)) : "待设置"}<small
              >{target ? "kcal" : ""}</small
            ></strong
          ><span class="muted"
            >{target
              ? `目标 ${number(target)} kcal`
              : "到个人设置中填写目标"}</span
          >
        </div>
      </div>
    </div>
  </div>
  <div class="metrics-grid">
    <div class="metric-card">
      <span class="metric-icon sage"><Scale size={20} /></span>
      <div>
        <span class="muted">参考体重</span><strong
          >{number(day.effective_weight_kg, 1)}<small>kg</small></strong
        ><span class="metric-caption"
          >{day.body?.weight_kg ? "今日已称重" : "最近记录 / 初始体重"}</span
        >
      </div>
    </div>
    <div class="metric-card">
      <span class="metric-icon amber"><Flame size={20} /></span>
      <div>
        <span class="muted">估计总消耗</span><strong
          >{number(day.expenditure_kcal)}<small>kcal</small></strong
        ><span class="metric-caption">含静息、日常活动与运动</span>
      </div>
    </div>
    <div class="metric-card">
      <span class="metric-icon blue"><Dumbbell size={20} /></span>
      <div>
        <span class="muted">运动净消耗</span><strong
          >{number(day.exercise_kcal)}<small>kcal</small></strong
        ><span class="metric-caption"
          >{number(day.duration_minutes)} 分钟训练</span
        >
      </div>
    </div>
    <div class="metric-card">
      <span class="metric-icon sage"><TrendingDown size={20} /></span>
      <div>
        <span class="muted">估计热量缺口</span><strong
          >{number(day.deficit_kcal)}<small>kcal</small></strong
        ><span class="metric-caption">消耗 − 已记录摄入</span>
      </div>
    </div>
  </div>
  <div class="two-columns">
    <section class="panel">
      <div class="section-heading">
        <div>
          <span class="eyebrow">YOUR PROGRESS</span>
          <h3>看见身体的变化</h3>
          <span class="small muted">{TRACKING_START} 起 · 至 {app.date}</span>
        </div>
        <button class="text-button" onclick={() => navigate("trends")}
          >全部趋势<ArrowRight size={15} /></button
        >
      </div>
      {#if app.trends.some((row) => row.body?.weight_kg != null)}<Chart
          option={weightChart}
          label="体重与七日均值趋势"
        />{:else}<div class="empty-chart">
          <Scale size={30} /><strong>从第一次称重开始</strong>
          <p>
            {app.date < TRACKING_START
              ? `趋势从 ${TRACKING_START} 开始`
              : "记录体重后，这里会呈现你的变化轨迹。"}
          </p>
          <button class="secondary" onclick={() => navigate("body")}
            >记录身体数据</button
          >
        </div>{/if}
    </section>
    <section class="panel">
      <div class="section-heading">
        <div>
          <span class="eyebrow">BALANCE YOUR PLATE</span>
          <h3>今日营养分布</h3>
        </div>
        <span class="badge subtle">供能占比</span>
      </div>
      <div class="macro-layout">
        {#if intake > 0}<div class="macro-donut">
            <Chart
              option={macroChart}
              height={185}
              label="三大营养素供能比例"
            /><span><strong>{number(intake)}</strong><small>kcal</small></span>
          </div>{:else}<div class="macro-placeholder">
            <Utensils size={28} /><span>等待第一餐</span>
          </div>{/if}
        <div class="macro-legend">
          {#each [{ name: "蛋白质", value: day.totals.protein_g, key: "protein" as const, color: "#246b53", target: day.profile?.protein_target_g }, { name: "碳水", value: day.totals.carbs_g, key: "carbs" as const, color: "#dea64e", target: day.profile?.carbs_target_g }, { name: "脂肪", value: day.totals.fat_g, key: "fat" as const, color: "#7899ad", target: day.profile?.fat_target_g }] as macro}<div
            >
              <span
                ><i style:background={macro.color}></i>{macro.name}<b
                  >{number(macro.value, 1)} g</b
                ></span
              >
              <div class="progress-track">
                <span
                  style:background={macro.color}
                  style:width="{Math.min(
                    100,
                    macro.target
                      ? (macro.value / macro.target) * 100
                      : day.totals.macro_percent[macro.key],
                  )}%"
                ></span>
              </div>
              <small
                >{macro.target ? `目标 ${number(macro.target)} g · ` : ""}供能 {number(
                  day.totals.macro_percent[macro.key],
                )}%</small
              >
            </div>{/each}
        </div>
      </div>
      <div class="nutrient-summary dashboard-nutrients">
        <span>膳食纤维 <strong>{number(day.totals.fiber_g, 1)} g</strong></span>
        <span>总糖 <strong>{number(day.totals.sugar_g, 1)} g</strong></span>
        <span>钠 <strong>{number(day.totals.sodium_mg, 0)} mg</strong></span>
      </div>
    </section>
  </div>
  <div class="two-columns">
    <section class="panel">
      <div class="section-heading">
        <div>
          <span class="eyebrow">TODAY'S JOURNAL</span>
          <h3>今天，已经做得不错</h3>
        </div>
        <button class="text-button" onclick={() => navigate("meals")}
          >饮食记录<ArrowRight size={15} /></button
        >
      </div>
      {#if day.meals.length}<div class="compact-list">
          {#each day.meals.slice(0, 4) as meal}<div>
              <span class="list-icon"><Utensils size={18} /></span>
              <div>
                <strong>{meal.title || slots[meal.slot]}</strong><small
                  >{meal.items.map((item) => item.name).join(" · ")}</small
                >
              </div>
              <b>{number(meal.totals?.kcal)}<small> kcal</small></b>
            </div>{/each}
        </div>{:else}<div class="empty-mini">
          <p>今天还没有饮食记录。</p>
          <button class="text-button" onclick={() => navigate("meals")}
            >上传一张餐食照片<ArrowRight size={15} /></button
          >
        </div>{/if}
      <div class="panel-footer">
        <span
          >{day.workouts.length} 次训练 · {day.plans.filter(
            (plan) => plan.status === "planned",
          ).length} 项待完成排期</span
        ><button class="text-button" onclick={() => navigate("training")}
          >查看训练</button
        >
      </div>
    </section>
    <section class="panel ai-panel">
      <div class="section-heading">
        <div>
          <span class="eyebrow">A LITTLE GUIDANCE</span>
          <h3><Sparkles size={18} />你的每日反馈</h3>
        </div>
        {#if day.feedback?.stale}<span class="badge amber">记录已变化</span
          >{/if}
      </div>
      {#if day.feedback}<p class="feedback-summary">
          {day.feedback.data.summary}
        </p>
        {#if day.feedback.data.positives.length}<div class="feedback-points">
            <strong>做得不错</strong
            >{#each day.feedback.data.positives as point}<p>
                <Check size={13} />{point}
              </p>{/each}
          </div>{/if}
        {#if day.feedback.data.adjustments.length}<div class="feedback-points">
            <strong>可以调整</strong
            >{#each day.feedback.data.adjustments as point}<p>
                <ArrowRight size={13} />{point}
              </p>{/each}
          </div>{/if}
        <p class="feedback-next">
          <strong>明天可以这样做</strong>{day.feedback.data.next_day_advice}
        </p>{:else}<p class="feedback-summary">
          完成今天的饮食和训练记录，让 AI 帮你回顾营养、运动与近期趋势。
        </p>
        <p class="muted small">记录越完整，反馈越有参考价值。</p>{/if}<button
        class="primary"
        disabled={app.busy || activeFeedback}
        onclick={() => void complete()}
        >{#if activeFeedback}<Sparkles size={16} />正在生成建议…{:else}<Check
            size={16}
          />{day.feedback
            ? "重新生成今日反馈"
            : "完成今日记录并生成建议"}{/if}</button
      >
      <button
        class="text-button"
        disabled={app.busy}
        onclick={() => void complete(false)}>仅完成今日记录</button
      >
    </section>
  </div>
  <WeeklyReview />
{/if}
