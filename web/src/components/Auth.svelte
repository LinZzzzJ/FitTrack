<script lang="ts">
  import {
    ArrowRight,
    Leaf,
    LockKeyhole,
    Utensils,
    Dumbbell,
    ChartNoAxesCombined,
    LoaderCircle,
  } from "@lucide/svelte";
  import { api } from "../lib/api";
  import { init, app, notify } from "../lib/state.svelte";
  let registering = $state(false),
    username = $state(""),
    password = $state(""),
    pending = $state(false);
  async function submit(event: SubmitEvent) {
    event.preventDefault();
    pending = true;
    try {
      await api.post(`/auth/${registering ? "register" : "login"}`, {
        username,
        password,
      });
      password = "";
      await init();
    } catch (error) {
      notify(error instanceof Error ? error.message : "登录失败", true);
    } finally {
      pending = false;
    }
  }
</script>

<main class="auth-layout">
  <section class="auth-story">
    <div class="brand">
      <span class="brand-mark"><Leaf size={22} /></span><span
        >FitTrack<span class="brand-sub">轻衡</span></span
      >
    </div>
    <div class="auth-copy">
      <span class="eyebrow light">A LITTLE BETTER, EVERY DAY</span>
      <h1>照顾今天的自己，<br />看见明天的改变。</h1>
      <p>
        从一餐、一组训练、一次称重开始。<br
        />把每个小进步，记录成属于你的长期变化。
      </p>
      <div class="auth-features">
        <span><Utensils size={18} />饮食与营养</span><span
          ><Dumbbell size={18} />训练与排期</span
        ><span><ChartNoAxesCombined size={18} />身体趋势</span>
      </div>
      <div class="auth-illustration" aria-hidden="true">
        <div class="orbit orbit-one"></div>
        <div class="orbit orbit-two"></div>
        <div class="leaf-card">
          <Leaf size={60} strokeWidth={1} /><span
            >Small steps.<br />Lasting change.</span
          >
        </div>
        <div class="floating-pill">每一天，都值得记录</div>
      </div>
    </div>
    <div class="auth-footnote">你的记录，保存在这台电脑。</div>
  </section>
  <section class="auth-form">
    <div class="auth-form-inner">
      <span class="eyebrow">YOUR PERSONAL WELLNESS SPACE</span>
      <h2>{registering ? "开启你的记录之旅" : "欢迎回来"}</h2>
      <p class="muted">
        {registering
          ? "创建独立账号，让每一次记录都有归属。"
          : "今天也为自己留一点时间。"}
      </p>
      <form onsubmit={submit}>
        <label
          >用户名<input
            autocomplete="username"
            bind:value={username}
            minlength="2"
            maxlength="40"
            required
            placeholder="请输入用户名"
          /></label
        ><label
          >密码<input
            type="password"
            autocomplete={registering ? "new-password" : "current-password"}
            bind:value={password}
            minlength="8"
            maxlength="128"
            required
            placeholder="至少 8 个字符"
          /></label
        >
        <button class="primary full" disabled={pending}
          >{#if pending}<LoaderCircle
              size={18}
              class="spin"
            />{:else}{registering ? "创建账号" : "登录"}<ArrowRight
              size={18}
            />{/if}</button
        >
      </form>
      <div class="auth-switch">
        {registering ? "已有账号？" : "第一次使用？"}<button
          class="text-button"
          onclick={() => {
            registering = !registering;
            app.notice = "";
          }}>{registering ? "去登录" : "创建账号"}</button
        >
      </div>
      <p class="secure-note">
        <LockKeyhole size={15} />独立账号 · 本地存储 · 在线 AI 辅助
      </p>
    </div>
  </section>
</main>
