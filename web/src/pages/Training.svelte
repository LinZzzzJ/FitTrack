<script lang="ts">
  import { onMount, tick } from "svelte";
  import QRCode from "qrcode";
  import jsQR from "jsqr";
  import Papa from "papaparse";
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
    Download,
    Upload,
    QrCode,
    Camera,
    BicepsFlexed,
    Brain,
    Footprints,
    HeartPulse,
    PersonStanding,
    MoveUpRight,
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
  import type { Workout, Plan, WorkoutTemplate, Exercise } from "../lib/types";
  let draft = $state<Workout | null>(null),
    planDraft = $state<Plan | null>(null),
    deleting = $state<{ kind: "workouts" | "plans"; id: string } | null>(null);
  let month = $state(""),
    monthPlans = $state<Plan[]>([]),
    workoutDates = $state<string[]>([]),
    templates = $state<WorkoutTemplate[]>([]),
    templateDraft = $state<WorkoutTemplate | null>(null),
    qrTemplate = $state<WorkoutTemplate | null>(null),
    qrDialog = $state(false),
    qrSource = $state(""),
    cameraOpen = $state(false),
    qrError = $state(""),
    importInput = $state<HTMLInputElement>(),
    csvHeaders = $state<string[]>([]),
    csvRows = $state<Record<string, string>[]>([]),
    csvMapping = $state<Record<string, string>>({});
  let qrVideo = $state<HTMLVideoElement>();
  let qrFileInput = $state<HTMLInputElement>();
  let cameraStream: MediaStream | null = null;
  let scanFrame = 0;
  const builtInTemplates: WorkoutTemplate[] = [
    { title: "背部训练", category: "back", icon: "back", kind: "strength", duration_minutes: 45, intensity: "moderate", note: "", exercises: ["高位下拉", "坐姿划船", "单臂哑铃划船"].map((name) => ({ name, sets: [{ reps: 10, weight_kg: 0 }] })) },
    { title: "胸部训练", category: "chest", icon: "chest", kind: "strength", duration_minutes: 45, intensity: "moderate", note: "", exercises: ["杠铃卧推", "上斜哑铃卧推", "绳索夹胸"].map((name) => ({ name, sets: [{ reps: 10, weight_kg: 0 }] })) },
    { title: "手臂训练", category: "arms", icon: "arms", kind: "strength", duration_minutes: 40, intensity: "moderate", note: "", exercises: ["哑铃弯举", "绳索下压", "锤式弯举"].map((name) => ({ name, sets: [{ reps: 10, weight_kg: 0 }] })) },
    { title: "肩部训练", category: "shoulders", icon: "shoulders", kind: "strength", duration_minutes: 40, intensity: "moderate", note: "", exercises: ["坐姿推举", "哑铃侧平举", "反向飞鸟"].map((name) => ({ name, sets: [{ reps: 10, weight_kg: 0 }] })) },
    { title: "腿部训练", category: "legs", icon: "legs", kind: "strength", duration_minutes: 50, intensity: "moderate", note: "", exercises: ["深蹲", "罗马尼亚硬拉", "腿举"].map((name) => ({ name, sets: [{ reps: 10, weight_kg: 0 }] })) },
  ];
  let allTemplates = $derived([...builtInTemplates, ...templates]);
  function templateIcon(category: WorkoutTemplate["category"]) {
    return {
      back: PersonStanding,
      chest: HeartPulse,
      arms: BicepsFlexed,
      shoulders: MoveUpRight,
      legs: Footprints,
      core: Brain,
      full_body: PersonStanding,
      custom: Dumbbell,
    }[category];
  }
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
    void api.get<WorkoutTemplate[]>("/workout-templates").then((value) => (templates = value));
  });
  async function loadMonth() {
    const selected = month;
    if (!selected) return;
    const end = new Date(selected + "-01T12:00:00Z");
    end.setUTCMonth(end.getUTCMonth() + 1);
    end.setUTCDate(0);
    try {
      const last = end.toISOString().slice(0, 10);
      const [result, recorded] = await Promise.all([
        api.get<Plan[]>(`/plans?start=${selected}-01&end=${last}`),
        api.get<string[]>(`/workout-days?start=${selected}-01&end=${last}`),
      ]);
      if (month === selected) {
        monthPlans = result;
        workoutDates = recorded;
      }
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
  function openWorkout(existing?: Workout, plan?: Plan, template?: WorkoutTemplate) {
    draft = {
      date: plan?.date || app.date,
      title: template?.title || plan?.title || "力量训练",
      kind: template?.kind || plan?.kind || "strength",
      activity: plan?.activity || "strength",
      duration_minutes: template?.duration_minutes || plan?.duration_minutes || 45,
      intensity: template?.intensity || plan?.intensity || "moderate",
      met: null,
      net_kcal_override: null,
      exercises: structuredClone(template?.exercises || plan?.exercises || []),
      note: template?.note || plan?.note || "",
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
  function makeTemplate() {
    templateDraft = {
      title: "我的训练模板",
      category: "custom",
      icon: "dumbbell",
      kind: "strength",
      duration_minutes: 45,
      intensity: "moderate",
      exercises: [{ name: "", sets: [{ reps: 10, weight_kg: 0 }] }],
      note: "",
    };
  }
  function editTemplate(value: WorkoutTemplate) {
    templateDraft = structuredClone(value);
  }
  async function saveTemplate(event: SubmitEvent) {
    event.preventDefault();
    if (!templateDraft) return;
    try {
      const { id, ...body } = $state.snapshot(templateDraft);
      const saved = id
        ? await api.put<WorkoutTemplate>(`/workout-templates/${id}`, body)
        : await api.post<WorkoutTemplate>("/workout-templates", body);
      templates = id
        ? templates.map((item) => (item.id === id ? saved : item))
        : [...templates, saved];
      templateDraft = null;
      notify("训练模板已保存");
    } catch (error) {
      notify(error instanceof Error ? error.message : "训练模板保存失败", true);
    }
  }
  async function deleteTemplate(value: WorkoutTemplate) {
    if (!value.id || !confirm(`删除“${value.title}”模板？`)) return;
    try {
      await api.delete(`/workout-templates/${value.id}`);
      templates = templates.filter((item) => item.id !== value.id);
      notify("训练模板已删除");
    } catch (error) {
      notify(error instanceof Error ? error.message : "训练模板删除失败", true);
    }
  }
  function downloadFile(name: string, content: string, type = "application/json") {
    const url = URL.createObjectURL(new Blob([content], { type }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name;
    anchor.click();
    URL.revokeObjectURL(url);
  }
  function downloadDataUrl(name: string, value: string) {
    const anchor = document.createElement("a");
    anchor.href = value;
    anchor.download = name;
    anchor.click();
  }
  function templatePayload(value: WorkoutTemplate) {
    const { id: _id, ...template } = value;
    return { format: "fittrack-template", version: 1, template };
  }
  function exportTemplates() {
    downloadFile("fittrack-templates.json", JSON.stringify({ format: "fittrack-training", version: 1, templates: templates.map(({ id: _id, ...item }) => item) }, null, 2));
  }
  async function exportQr(value: WorkoutTemplate) {
    const payload = JSON.stringify(templatePayload(value));
    if (new TextEncoder().encode(payload).length > 2900) {
      notify("模板内容超过二维码容量，请导出 JSON 文件", true);
      return;
    }
    qrError = "";
    qrTemplate = value;
    qrDialog = true;
    qrSource = await QRCode.toDataURL(payload, { errorCorrectionLevel: "L", margin: 2, width: 360 });
  }
  async function importTemplatePayload(raw: string) {
    if (new TextEncoder().encode(raw).length > 100000) throw new Error("模板文件过大");
    const value = JSON.parse(raw);
    if (value.format === "fittrack-template" && value.version === 1 && value.template) {
      const { id: _id, ...body } = value.template;
      templates = [...templates, await api.post<WorkoutTemplate>("/workout-templates", body)];
      return;
    }
    if (value.format === "fittrack-training" && value.version === 1 && Array.isArray(value.templates)) {
      for (const item of value.templates) {
        const { id: _id, ...body } = item;
        templates = [...templates, await api.post<WorkoutTemplate>("/workout-templates", body)];
      }
      return;
    }
    throw new Error("无法识别此训练模板格式");
  }
  async function decodeQr(raw: string) {
    try {
      await importTemplatePayload(raw);
      qrTemplate = null;
      cameraOpen = false;
      stopCamera();
      notify("训练模板已导入");
    } catch (error) {
      qrError = error instanceof Error ? error.message : "二维码内容无效";
    }
  }
  function stopCamera() {
    if (scanFrame) cancelAnimationFrame(scanFrame);
    cameraStream?.getTracks().forEach((track) => track.stop());
    cameraStream = null;
  }
  async function startCamera() {
    try {
      qrError = "";
      cameraOpen = true;
      qrDialog = true;
      await tick();
      cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      if (qrVideo) {
        qrVideo.srcObject = cameraStream;
        await qrVideo.play();
      }
      scanCameraFrame();
    } catch {
      stopCamera();
      cameraOpen = false;
      qrError = "无法使用摄像头，请上传二维码图片导入";
    }
  }
  function scanCameraFrame() {
    if (!qrVideo || !cameraOpen) return;
    if (qrVideo.readyState >= 2) {
      const canvas = document.createElement("canvas");
      canvas.width = qrVideo.videoWidth;
      canvas.height = qrVideo.videoHeight;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      context?.drawImage(qrVideo, 0, 0);
      const frame = context?.getImageData(0, 0, canvas.width, canvas.height);
      const result = frame && jsQR(frame.data, frame.width, frame.height, { inversionAttempts: "attemptBoth" });
      if (result) {
        cameraOpen = false;
        stopCamera();
        void decodeQr(result.data);
        return;
      }
    }
    scanFrame = requestAnimationFrame(scanCameraFrame);
  }
  async function readQrImage(file: File | undefined) {
    if (!file) return;
    try {
      const bitmap = await createImageBitmap(file);
      const canvas = document.createElement("canvas");
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      context?.drawImage(bitmap, 0, 0);
      bitmap.close();
      const frame = context?.getImageData(0, 0, canvas.width, canvas.height);
      const result = frame && jsQR(frame.data, frame.width, frame.height, { inversionAttempts: "attemptBoth" });
      if (!result) throw new Error("图片中没有可识别的二维码");
      await decodeQr(result.data);
    } catch (error) {
      qrError = error instanceof Error ? error.message : "二维码图片读取失败";
    }
  }
  function openImport() {
    importInput?.click();
  }
  function openQrImport() {
    qrTemplate = null;
    qrSource = "";
    qrError = "";
    qrDialog = true;
  }
  async function importFile(file: File | undefined) {
    if (!file) return;
    if (file.size > 20 * 1024 * 1024) {
      notify("训练文件不能超过 20 MB", true);
      return;
    }
    const raw = await file.text();
    if (file.name.toLowerCase().endsWith(".json")) {
      try {
        const parsed = JSON.parse(raw);
        if (parsed.format === "fittrack-training" && Array.isArray(parsed.plans)) {
          for (const plan of parsed.plans) {
            const { id: _id, workout_id: _workout, ...body } = plan;
            await api.post("/plans", { ...body, status: "planned" });
          }
          await loadMonth();
          notify("训练排期已导入");
        } else {
          await importTemplatePayload(raw);
          notify("训练模板已导入");
        }
      } catch (error) {
        notify(error instanceof Error ? error.message : "JSON 导入失败", true);
      }
      return;
    }
    const parsed = Papa.parse<Record<string, string>>(raw, { header: true, skipEmptyLines: true, dynamicTyping: false });
    if (parsed.errors.length || !parsed.meta.fields?.length) {
      notify("CSV 文件无法解析，请检查表头和分隔符", true);
      return;
    }
    if (parsed.data.length > 100000) {
      notify("CSV 行数不能超过 100000", true);
      return;
    }
    csvHeaders = parsed.meta.fields;
    csvRows = parsed.data;
    csvMapping = Object.fromEntries(["date", "title", "exercise", "sets", "reps", "weight_kg", "duration_minutes"].map((key) => [key, csvHeaders.find((header) => header.toLowerCase() === key || header.includes(({ date: "日期", title: "名称", exercise: "动作", sets: "组", reps: "次数", weight_kg: "重量", duration_minutes: "时长" } as Record<string, string>)[key])) || ""]));
  }
  async function importCsvPlans(event: SubmitEvent) {
    event.preventDefault();
    const grouped = new Map<string, Plan>();
    let skipped = 0;
    for (const row of csvRows) {
      const date = row[csvMapping.date];
      const title = row[csvMapping.title] || "导入训练计划";
      const duration = Number(row[csvMapping.duration_minutes]) || 45;
      const key = `${date}|${title}`;
      const parsedDate = date ? new Date(`${date}T12:00:00Z`) : null;
      if (
        !date ||
        !/^\d{4}-\d{2}-\d{2}$/.test(date) ||
        !parsedDate ||
        Number.isNaN(parsedDate.getTime()) ||
        parsedDate.toISOString().slice(0, 10) !== date ||
        title.length > 100 ||
        duration < 1 ||
        duration > 1440
      ) {
        skipped++;
        continue;
      }
      let plan = grouped.get(key);
      if (!plan) {
        plan = { date, title, kind: "strength", activity: "strength", duration_minutes: duration, intensity: "moderate", status: "planned", note: "CSV 导入", exercises: [] };
        grouped.set(key, plan);
      }
      const name = row[csvMapping.exercise]?.trim();
      if (!name || name.length > 100) {
        skipped++;
        continue;
      }
      let exercise = plan.exercises.find((item) => item.name === name);
      if (!exercise) {
        if (plan.exercises.length >= 30) {
          skipped++;
          continue;
        }
        exercise = { name, sets: [] };
        plan.exercises.push(exercise);
      }
      const countValue = Number(row[csvMapping.sets]) || 1;
      const repsValue = Number(row[csvMapping.reps]) || 10;
      const weightValue = Number(row[csvMapping.weight_kg]) || 0;
      if (!Number.isInteger(countValue) || countValue < 1 || countValue > 50 || !Number.isInteger(repsValue) || repsValue < 1 || repsValue > 1000 || weightValue < 0 || weightValue > 1000 || exercise.sets.length + countValue > 50) {
        skipped++;
        continue;
      }
      for (let index = 0; index < countValue; index++) exercise.sets.push({ reps: repsValue, weight_kg: weightValue });
    }
    if (!grouped.size) {
      notify("没有找到有效日期的训练行", true);
      return;
    }
    try {
      for (const plan of grouped.values()) await api.post("/plans", plan);
      csvRows = [];
      await loadMonth();
      notify(`已导入 ${grouped.size} 天训练排期${skipped ? `，跳过 ${skipped} 行` : ""}`);
    } catch (error) {
      notify(
        `${error instanceof Error ? error.message : "CSV 导入失败"}；已保存排期不会回滚`,
        true,
      );
    }
  }
  async function exportMonthPlans() {
    const start = `${month}-01`;
    const first = new Date(`${start}T12:00:00Z`);
    first.setUTCMonth(first.getUTCMonth() + 1);
    first.setUTCDate(0);
    const plans = await api.get<Plan[]>(`/plans?start=${start}&end=${first.toISOString().slice(0, 10)}`);
    downloadFile(`fittrack-plans-${month}.json`, JSON.stringify({ format: "fittrack-training", version: 1, plans }, null, 2));
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
      exercises: [],
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
        exercises: structuredClone(existing.exercises || []),
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
    <button class="secondary" onclick={openImport}><Upload size={16} />导入计划/模板</button>
    <button class="secondary" onclick={exportTemplates}><Download size={16} />导出模板 JSON</button>
    <button class="secondary" onclick={openQrImport}><QrCode size={16} />扫码导入模板</button>
    <button class="secondary" onclick={() => void exportMonthPlans()}><Download size={16} />导出本月排期</button>
    <button class="secondary" onclick={() => openPlan()}
      ><CalendarDays size={17} />添加排期</button
    ><button class="primary" onclick={() => openWorkout()}
      ><Plus size={17} />记录训练</button
    >
  </div>
</div>
<input bind:this={importInput} class="visually-hidden" type="file" accept=".json,.csv,application/json,text/csv" onchange={(event) => void importFile(event.currentTarget.files?.[0])} />
<input bind:this={qrFileInput} class="visually-hidden" type="file" accept="image/*" onchange={(event) => void readQrImage(event.currentTarget.files?.[0])} />
<section class="panel template-library">
  <div class="section-heading">
    <div><span class="eyebrow">QUICK START</span><h3>训练模板</h3></div>
    <button class="secondary small-button" onclick={makeTemplate}><Plus size={15} />新建个人模板</button>
  </div>
  <div class="template-grid">
    {#each allTemplates as template, index}{@const TemplateIcon = templateIcon(template.category)}<article class="template-tile">
      <span class="metric-icon" class:sage={index % 3 === 0} class:amber={index % 3 === 1} class:blue={index % 3 === 2}><TemplateIcon size={19} /></span>
      <div><strong>{template.title}</strong><small>{template.exercises.length} 个动作 · {template.duration_minutes} 分钟</small></div>
      <button class="secondary small-button" onclick={() => openWorkout(undefined, undefined, template)}>套用到今天</button>
      {#if template.id}<button class="icon-button" title="编辑模板" aria-label="编辑模板" onclick={() => editTemplate(template)}><Pencil size={15} /></button><button class="icon-button" title="导出二维码" aria-label="导出二维码" onclick={() => void exportQr(template)}><QrCode size={15} /></button><button class="icon-button danger" title="删除模板" aria-label="删除模板" onclick={() => void deleteTemplate(template)}><Trash2 size={15} /></button>{:else}<button class="icon-button" title="导出二维码" aria-label="导出二维码" onclick={() => void exportQr(template)}><QrCode size={15} /></button>{/if}
    </article>{/each}
  </div>
</section>
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
          class:has-workout={workoutDates.includes(day)}
          onclick={() => void selectDate(day)}
          ><span>{Number(day.slice(8))}{#if workoutDates.includes(day)}<i class="workout-marker" aria-label="有训练记录"></i>{/if}</span>{#each monthPlans
            .filter((plan) => plan.date === day)
            .slice(0, 2) as plan}<small
              class:complete={plan.status === "completed"}
              class:skipped={plan.status === "skipped"}>{plan.title}</small
            >{/each}</button
        >{/each}
    </div>
    <div class="calendar-legend">
      <span><i class="recorded"></i>有训练记录</span><span><i></i>待训练</span><span><i class="done"></i>已完成</span><span
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
{#if templateDraft}<Modal title={templateDraft.id ? "编辑训练模板" : "新建训练模板"} wide onclose={() => (templateDraft = null)}>
  <form onsubmit={saveTemplate}>
    <div class="form-grid">
      <label>模板名称<input bind:value={templateDraft.title} maxlength="100" required /></label>
      <label>训练部位<select bind:value={templateDraft.category}><option value="back">背部</option><option value="chest">胸部</option><option value="arms">手臂</option><option value="shoulders">肩部</option><option value="legs">腿部</option><option value="core">核心</option><option value="full_body">全身</option><option value="custom">自定义</option></select></label>
      <label>默认时长 / 分钟<input type="number" min="1" max="1440" bind:value={templateDraft.duration_minutes} required /></label>
      <label>默认强度<select bind:value={templateDraft.intensity}><option value="light">轻强度</option><option value="moderate">中等强度</option><option value="vigorous">高强度</option></select></label>
    </div>
    <div class="section-heading"><h3>动作与默认组数</h3><button type="button" class="text-button" onclick={() => templateDraft?.exercises.push({ name: "", sets: [{ reps: 10, weight_kg: 0 }] })}><Plus size={15} />添加动作</button></div>
    {#each templateDraft.exercises as exercise, index}<div class="template-exercise-row">
      <input aria-label="动作名称" bind:value={exercise.name} maxlength="100" placeholder="动作名称" required />
      <label>组数<input type="number" min="1" max="50" value={exercise.sets.length} onchange={(event) => { const count = Math.max(1, Number(event.currentTarget.value) || 1); exercise.sets = Array.from({ length: count }, (_, i) => exercise.sets[i] || { reps: 10, weight_kg: 0 }); }} /></label>
      <label>次数<input type="number" min="1" max="1000" bind:value={exercise.sets[0].reps} /></label>
      <label>重量 / kg<input type="number" min="0" max="1000" step="0.5" bind:value={exercise.sets[0].weight_kg} /></label>
      <button class="icon-button danger" type="button" aria-label="移除动作" disabled={templateDraft.exercises.length <= 1} onclick={() => templateDraft?.exercises.splice(index, 1)}><Trash2 size={15} /></button>
    </div>{/each}
    <label>备注<textarea bind:value={templateDraft.note} maxlength="2000" rows="2"></textarea></label>
    <div class="form-actions"><button class="primary"><Check size={16} />保存模板</button></div>
  </form>
</Modal>{/if}
{#if csvRows.length}<Modal title="映射 CSV 列到训练排期" wide onclose={() => (csvRows = [])}>
  <p class="small muted">每一行对应一个动作；相同日期和训练名称会合并为同一条排期。</p>
  <form onsubmit={importCsvPlans}>
    <div class="form-grid csv-map-grid">
      {#each [["date", "训练日期"], ["title", "训练名称"], ["exercise", "动作名称"], ["sets", "组数"], ["reps", "次数"], ["weight_kg", "重量 kg"], ["duration_minutes", "时长分钟"]] as [key, label]}<label>{label}<select bind:value={csvMapping[key]}><option value="">未映射</option>{#each csvHeaders as header}<option value={header}>{header}</option>{/each}</select></label>{/each}
    </div>
    <p class="small muted">预览 {Math.min(csvRows.length, 5)} / {csvRows.length} 行</p>
    <div class="form-actions"><button type="button" class="secondary" onclick={() => (csvRows = [])}>取消</button><button class="primary" disabled={!csvMapping.date || !csvMapping.exercise}>导入排期</button></div>
  </form>
</Modal>{/if}
{#if qrDialog}<Modal title={qrTemplate ? `分享模板：${qrTemplate.title}` : "导入训练模板二维码"} onclose={() => { qrDialog = false; cameraOpen = false; stopCamera(); }}>
  {#if qrTemplate && qrSource}<div class="qr-export"><img src={qrSource} alt="训练模板二维码" /><button class="secondary" onclick={() => downloadDataUrl(`${qrTemplate?.title || "训练模板"}.png`, qrSource)}><Download size={16} />下载二维码</button></div>{/if}
  {#if cameraOpen}<video bind:this={qrVideo} class="qr-video" playsinline></video>{/if}
  {#if qrError}<p class="error-text">{qrError}</p>{/if}
  <div class="form-actions"><button class="secondary" onclick={() => void startCamera()}><Camera size={16} />打开摄像头</button><button class="secondary" onclick={() => qrFileInput?.click()}><Upload size={16} />上传二维码图片</button>{#if qrTemplate}<button class="secondary" onclick={() => qrTemplate && downloadFile("fittrack-template.json", JSON.stringify(templatePayload(qrTemplate), null, 2))}><Download size={16} />导出 JSON</button>{/if}</div>
</Modal>{/if}
