<script lang="ts">
  import { onMount } from "svelte";
  import {
    Leaf,
    LayoutDashboard,
    Scale,
    Utensils,
    Dumbbell,
    ChartNoAxesCombined,
    Settings as SettingsIcon,
    LogOut,
    ChevronLeft,
    ChevronRight,
    Menu,
    X,
    ArrowUpRight,
    LoaderCircle,
    ShieldCheck,
  } from "@lucide/svelte";
  import Auth from "./components/Auth.svelte";
  import Dashboard from "./pages/Dashboard.svelte";
  import Body from "./pages/Body.svelte";
  import Meals from "./pages/Meals.svelte";
  import Training from "./pages/Training.svelte";
  import Trends from "./pages/Trends.svelte";
  import Settings from "./pages/Settings.svelte";
  import {
    app,
    init,
    logout,
    navigate,
    selectDate,
    shiftDate,
    notify,
  } from "./lib/state.svelte";
  import type { Page } from "./lib/types";
  import { compatibility, checkVersion } from "./lib/compatibility.svelte";
  const navigation = [
    { id: "dashboard" as Page, label: "今日概览", icon: LayoutDashboard },
    { id: "body" as Page, label: "身体记录", icon: Scale },
    { id: "meals" as Page, label: "饮食记录", icon: Utensils },
    { id: "training" as Page, label: "训练与排期", icon: Dumbbell },
    { id: "trends" as Page, label: "趋势分析", icon: ChartNoAxesCombined },
    { id: "settings" as Page, label: "个人设置", icon: SettingsIcon },
  ];
  let current = $derived(navigation.find((item) => item.id === app.page)!);
  let dateLabel = $derived(
    app.date
      ? new Date(app.date + "T12:00:00+08:00").toLocaleDateString("zh-CN", {
          weekday: "long",
          month: "long",
          day: "numeric",
          timeZone: "Asia/Shanghai",
        })
      : "",
  );
  onMount(() => {
    void init();
    void checkVersion();
    const timer = setInterval(() => void checkVersion(), 30000);
    const onFocus = () => void checkVersion();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  });
  async function changeDate(day: string) {
    try {
      await selectDate(day);
    } catch (error) {
      notify(error instanceof Error ? error.message : "读取失败", true);
    }
  }
</script>

{#if app.loading}<div class="startup">
    <span class="brand-mark"><Leaf size={25} /></span>
    <h2>FitTrack · 轻衡</h2>
    <LoaderCircle size={23} class="spin" />
  </div>{:else if !app.user}<Auth />{:else}<div
    class="app-shell"
    class:menu-open={app.menuOpen}
  >
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark"><Leaf size={23} /></span><span
          >FitTrack<span class="brand-sub">轻衡</span></span
        >
      </div>
      <span class="nav-caption">你的健康日常</span>
      <nav aria-label="主导航">
        {#each navigation as item}<button
            class:active={app.page === item.id}
            onclick={() => navigate(item.id)}
            aria-current={app.page === item.id ? "page" : undefined}
            ><item.icon size={19} /><span>{item.label}</span
            >{#if app.page === item.id}<i></i>{/if}</button
          >{/each}
      </nav>
      <div class="sidebar-note">
        <span class="mini-leaf"><Leaf size={20} /></span><strong
          >慢慢来，也是一种力量。</strong
        >
        <p>把注意力放在每天<br />能做到的小事上。</p>
        <span class="eyebrow">ONE DAY AT A TIME</span>
      </div>
      <div class="sidebar-bottom">
        <div class="account-avatar">
          {app.user.username.slice(0, 1).toUpperCase()}
        </div>
        <div>
          <strong>{app.user.username}</strong><span
            >{app.user.is_admin
              ? app.runtime?.mode === "server"
                ? "管理员"
                : "本机管理员"
              : "独立账号"}</span
          >
        </div>
        <button
          class="icon-button"
          aria-label="退出登录"
          onclick={() => void logout()}><LogOut size={17} /></button
        >
      </div>
    </aside>
    {#if app.menuOpen}<button
        class="mobile-scrim"
        aria-label="收起导航"
        onclick={() => (app.menuOpen = false)}
      ></button>{/if}
    <div class="main-shell">
      <header class="topbar">
        <div class="topbar-title">
          <button
            class="icon-button menu-toggle"
            aria-label="打开导航"
            onclick={() => (app.menuOpen = !app.menuOpen)}
            ><Menu size={21} /></button
          ><span>{current.label}</span><span class="topbar-divider"></span><span
            class="topbar-subtitle">{dateLabel}</span
          >
        </div>
        <div class="date-control">
          <button
            class="icon-button"
            aria-label="前一天"
            onclick={() => void changeDate(shiftDate(app.date, -1))}
            ><ChevronLeft size={16} /></button
          ><input
            type="date"
            aria-label="记录日期"
            value={app.date}
            onchange={(event) => {
              if (event.currentTarget.value)
                void changeDate(event.currentTarget.value);
            }}
          /><button
            class="icon-button"
            aria-label="后一天"
            onclick={() => void changeDate(shiftDate(app.date, 1))}
            ><ChevronRight size={16} /></button
          >{#if app.date !== app.today}<button
              class="text-button"
              onclick={() => void changeDate(app.today)}>今天</button
            >{/if}
        </div>
      </header>
      <main class="main-content">
        {#if compatibility.message}<div class="version-alert" role="alert">
            <strong>后台需要更新</strong>
            <p>{compatibility.message}</p>
            <button class="secondary" onclick={() => void checkVersion()}
              >重新检查版本</button
            >
          </div>{/if}
        {#if !app.profile && app.page !== "settings"}<div class="setup-banner">
            <span>填写身体资料，开始计算你的消耗与目标。</span><button
              class="text-button"
              onclick={() => navigate("settings")}
              >去填写<ArrowUpRight size={16} /></button
            >
          </div>{/if}{#key app.page}{#if app.page === "dashboard"}<Dashboard
            />{:else if app.page === "body"}<Body
            />{:else if app.page === "meals"}<Meals
            />{:else if app.page === "training"}<Training
            />{:else if app.page === "trends"}<Trends />{:else}<Settings
            />{/if}{/key}
        <footer class="app-footer">
          <span><ShieldCheck size={13} />记录保存在本机</span><span
            >FitTrack · 轻衡 {compatibility.version
              ? `v${compatibility.version}`
              : ""} <i> / </i> 消耗与食物热量均为估计</span
          >
        </footer>
      </main>
    </div>
  </div>{/if}
{#if app.notice}<div class="toast" class:error={app.noticeError} role="status">
    <span>{app.notice}</span><button
      class="icon-button"
      aria-label="关闭提示"
      onclick={() => (app.notice = "")}><X size={16} /></button
    >
  </div>{/if}
