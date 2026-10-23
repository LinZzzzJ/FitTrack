<script lang="ts">
  import {
    Camera,
    Upload,
    Plus,
    Sparkles,
    Utensils,
    Pencil,
    Trash2,
    Check,
    LoaderCircle,
    RotateCcw,
    ImagePlus,
    Maximize2,
  } from "@lucide/svelte";
  import Modal from "../components/Modal.svelte";
  import Chart from "../components/Chart.svelte";
  import DietHistory from "../components/DietHistory.svelte";
  import NutritionLabelEditor from "../components/NutritionLabelEditor.svelte";
  import { api, imageUrl } from "../lib/api";
  import {
    app,
    number,
    perform,
    notify,
    selectDate,
    refresh,
  } from "../lib/state.svelte";
  import { pieOptions } from "../lib/charts";
  import type {
    Food,
    Job,
    Meal,
    LabelReadout,
    NutritionLabel,
  } from "../lib/types";
  let fileInput = $state<HTMLInputElement>();
  let dragDepth = 0;
  type Photo = { id: string; width?: number; height?: number };
  let image = $state<Photo | null>(null),
    note = $state(""),
    mealDescription = $state(""),
    estimatingMeal = $state(false),
    slot = $state<Meal["slot"]>("lunch"),
    dragging = $state(false);
  let draft = $state<Meal | null>(null),
    assumptions = $state<string[]>([]),
    deleting = $state<Meal | null>(null);
  let preview = $state<Photo | null>(null);
  let mealMode = $state<"photo" | "label">("photo");
  let labelDraft = $state<Meal | null>(null);
  let deletingJob = $state<Job | null>(null),
    deleteJobError = $state("");
  function askDeleteJob(job: Job) {
    deleteJobError = "";
    deletingJob = job;
  }
  async function removeJob() {
    if (!deletingJob || app.busy) return;
    const job = deletingJob;
    app.busy = true;
    deleteJobError = "";
    try {
      try {
        await api.delete(`/jobs/${job.id}`);
      } catch (error) {
        deleteJobError = error instanceof Error ? error.message : "删除失败，请重试";
        return;
      }
      if (draft?.source_job_id === job.id) draft.source_job_id = null;
      if (labelDraft?.source_job_id === job.id) labelDraft.source_job_id = null;
      deletingJob = null;
      try {
        await refresh();
        notify("餐食分析记录已删除，已入账餐食和原图已保留");
      } catch {
        notify("分析记录已删除，列表刷新失败，请刷新页面查看", true);
      }
    } finally {
      app.busy = false;
    }
  }
  function blankLabel(label?: LabelReadout): NutritionLabel {
    return {
      label: label || {
        name: null,
        basis_kind: null,
        basis_grams: null,
        energy_value: null,
        energy_unit: null,
        protein_g: null,
        carbs_g: null,
        fat_g: null,
        fiber_g: null,
        sugar_g: null,
        sodium_mg: null,
        assumptions: [],
      },
      portion: { mode: "grams", grams: null, pack_grams: null, packs: null },
    };
  }
  const slots = {
    breakfast: "早餐",
    lunch: "午餐",
    dinner: "晚餐",
    snack: "加餐",
  };
  const blankFood = (): Food => ({
    name: "",
    consumed_part: "",
    estimated_edible_grams: 100,
    kcal: 0,
    protein_g: 0,
    carbs_g: 0,
    fat_g: 0,
    fiber_g: null,
    sugar_g: null,
    sodium_mg: null,
  });
  let mealJobs = $derived(
    app.day?.jobs.filter((job) => job.kind === "meal") || [],
  );
  let active = $derived(
    mealJobs.some((job) => ["queued", "running"].includes(job.status)),
  );
  let draftTotal = $derived(
    draft?.items.reduce((sum, item) => sum + (Number(item.kcal) || 0), 0) || 0,
  );
  let draftFoodChart = $derived(
    pieOptions(
      draft?.items.map((item) => ({
        name: item.name || "待命名",
        value: Number(item.kcal) || 0,
      })) || [],
    ),
  );
  let draftMacroChart = $derived(
    pieOptions([
      {
        name: "蛋白质",
        value:
          (draft?.items.reduce(
            (sum, item) => sum + (Number(item.protein_g) || 0),
            0,
          ) || 0) * 4,
      },
      {
        name: "碳水",
        value:
          (draft?.items.reduce(
            (sum, item) => sum + (Number(item.carbs_g) || 0),
            0,
          ) || 0) * 4,
      },
      {
        name: "脂肪",
        value:
          (draft?.items.reduce(
            (sum, item) => sum + (Number(item.fat_g) || 0),
            0,
          ) || 0) * 9,
      },
    ]),
  );
  async function upload(file: File | undefined) {
    if (!file || app.busy) return;
    const supported = [
      "image/jpeg",
      "image/png",
      "image/webp",
      "image/gif",
    ].includes(file.type);
    // Explorer and some desktop apps provide files without a MIME type.
    // The backend still checks the actual image bytes before accepting a file.
    if (
      !supported &&
      !(file.type === "" && /\.(jpe?g|png|webp|gif)$/i.test(file.name))
    ) {
      notify("请选择 JPEG、PNG、WebP 或 GIF 图片", true);
      return;
    }
    if (file.size > 12 * 1024 * 1024) {
      notify("上传图片不能超过 12 MB", true);
      return;
    }
    await perform(async () => {
      const form = new FormData();
      form.append("file", file);
      image = await api.post<Photo>("/uploads", form);
    }, "照片已上传，可以补充食用说明");
  }
  function isFileDrag(event: DragEvent) {
    return Array.from(event.dataTransfer?.types || []).includes("Files");
  }
  function resetDrag() {
    dragDepth = 0;
    dragging = false;
  }
  function dragEnter(event: DragEvent) {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    if (app.busy) return;
    dragDepth++;
    dragging = true;
  }
  function dragOver(event: DragEvent) {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    if (event.dataTransfer)
      event.dataTransfer.dropEffect = app.busy ? "none" : "copy";
    dragging = !app.busy;
  }
  function dragLeave() {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) dragging = false;
  }
  function dropPhoto(event: DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    resetDrag();
    if (app.busy) return;
    const files = event.dataTransfer?.files;
    if (files?.length !== 1) {
      notify(
        files?.length
          ? "每次请拖入一张餐食图片"
          : "请拖入本机图片文件，或点击选择图片",
        true,
      );
      return;
    }
    void upload(files[0]);
  }
  function preventFileNavigation(event: DragEvent) {
    if (isFileDrag(event)) event.preventDefault();
  }
  function dropOutside(event: DragEvent) {
    resetDrag();
    if (!isFileDrag(event) || event.defaultPrevented) return;
    event.preventDefault();
    notify("请把图片拖到“餐食照片”的上传区域", true);
  }
  async function analyze() {
    if (!image) return;
    await perform(
      () =>
        api.post("/jobs", {
          kind: "meal",
          meal_mode: mealMode,
          date: app.date,
          image_id: image!.id,
          note,
          slot,
          request_key: crypto.randomUUID(),
        }),
      "分析已开始，关闭页面也会继续",
    );
  }
  function manual() {
    mealDescription = "";
    if (mealMode === "label") {
      labelDraft = {
        date: app.date,
        slot,
        title: "",
        note,
        items: [],
        image_id: image?.id || null,
        source_job_id: null,
        nutrition_label: blankLabel(),
      };
      return;
    }
    assumptions = [];
    draft = {
      date: app.date,
      slot,
      title: "",
      note: "",
      items: [blankFood()],
      image_id: image?.id || null,
      source_job_id: null,
    };
  }
  function manualFromJob(job: Job) {
    if (job.request.meal_mode === "label") {
      labelDraft = {
        date: job.date,
        slot: job.request.slot || "lunch",
        title: "",
        note: job.request.note || "",
        items: [],
        image_id: job.request.image_id || null,
        source_job_id: null,
        nutrition_label: blankLabel(job.result?.label),
      };
      return;
    }
    assumptions = [];
    draft = {
      date: job.date,
      slot: job.request.slot || "lunch",
      title: "",
      note: job.request.note || "",
      items: [blankFood()],
      image_id: job.request.image_id || null,
      source_job_id: null,
    };
  }
  function edit(meal: Meal) {
    if (meal.nutrition_label) {
      labelDraft = structuredClone($state.snapshot(meal));
      return;
    }
    assumptions = meal.assumptions || [];
    draft = {
      id: meal.id,
      date: meal.date,
      slot: meal.slot,
      title: meal.title,
      note: meal.note,
      assumptions: meal.assumptions || [],
      items: structuredClone($state.snapshot(meal.items)),
      image_id: meal.image_id,
      source_job_id: meal.source_job_id,
    };
  }
  function view(job: Job) {
    if (job.result?.label) {
      labelDraft = {
        date: job.date,
        slot: job.request.slot || "lunch",
        title: "",
        note: job.request.note || "",
        assumptions: job.result.label.assumptions,
        items: [],
        image_id: job.request.image_id || null,
        source_job_id: job.id,
        nutrition_label: blankLabel(job.result.label),
      };
      return;
    }
    if (!job.result?.items) return;
    assumptions = job.result.assumptions || [];
    draft = {
      date: job.date,
      slot: job.request.slot || "lunch",
      title: "",
      note: job.request.note || "",
      assumptions: job.result.assumptions || [],
      items: structuredClone($state.snapshot(job.result.items)),
      image_id: job.request.image_id || null,
      source_job_id: job.id,
    };
  }
  function scale(item: Food, event: Event) {
    const grams = (event.currentTarget as HTMLInputElement).valueAsNumber;
    if (!Number.isFinite(grams) || grams < 0) return;
    const ratio =
      item.estimated_edible_grams > 0 ? grams / item.estimated_edible_grams : 1;
    for (const key of [
      "kcal",
      "protein_g",
      "carbs_g",
      "fat_g",
      "fiber_g",
      "sugar_g",
      "sodium_mg",
    ] as const) {
      if (item[key] != null) item[key] = Math.round(item[key]! * ratio * 100) / 100;
    }
    item.estimated_edible_grams = grams;
  }
  async function estimateManual() {
    if (!draft || estimatingMeal || mealDescription.trim().length < 3) return;
    estimatingMeal = true;
    try {
      let job = await api.post<Job>("/jobs", {
        kind: "meal",
        date: draft.date,
        slot: draft.slot,
        note: draft.note || "",
        meal_description: mealDescription.trim(),
        image_id: image?.id || null,
        request_key: crypto.randomUUID(),
      });
      while (["queued", "running"].includes(job.status)) {
        await new Promise((resolve) => setTimeout(resolve, 1200));
        job = await api.get<Job>(`/jobs/${job.id}`);
      }
      if (job.status !== "done" || !job.result?.items) {
        throw new Error(job.error || "AI 估算未完成，可继续手动填写");
      }
      assumptions = job.result.assumptions || [];
      draft.items = structuredClone($state.snapshot(job.result.items));
      draft.image_id = job.request.image_id || null;
      draft.source_job_id = job.id;
      notify("营养草稿已生成，请核对后确认入账");
    } catch (error) {
      notify(error instanceof Error ? error.message : "AI 估算失败", true);
    } finally {
      estimatingMeal = false;
    }
  }
  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!draft) return;
    const { id, ...payload } = $state.snapshot(draft);
    if (
      await perform(
        () =>
          id ? api.put(`/meals/${id}`, payload) : api.post("/meals", payload),
        "餐食已确认入账",
      )
    )
      draft = null;
  }
  async function retry(job: Job) {
    await perform(
      () =>
        api.post("/jobs", { ...job.request, request_key: crypto.randomUUID() }),
      "已重新提交分析",
    );
  }
  async function retryLabel(job: Job) {
    await perform(
      () =>
        api.post("/jobs", {
          ...job.request,
          meal_mode: "label",
          request_key: crypto.randomUUID(),
        }),
      "已按原日期提交标签识别",
    );
  }
  async function addDay(day: string) {
    await selectDate(day);
    manual();
  }
</script>

<svelte:window
  ondragover={preventFileNavigation}
  ondrop={dropOutside}
  ondragend={resetDrag}
/>

<div class="page-intro">
  <div>
    <span class="eyebrow">KNOW WHAT NOURISHES YOU</span>
    <h2>把每一餐，记录得明明白白。</h2>
    <p>拍一张照片，补充你的吃法。估计之后，仍由你确认。</p>
  </div>
  <button class="secondary" onclick={manual}
    ><Plus size={17} />{mealMode === "label"
      ? "手动填写标签"
      : "手动记一餐"}</button
  >
</div>
<div class="meal-mode-controls" aria-label="饮食录入方式">
  <button
    class:active={mealMode === "photo"}
    onclick={() => (mealMode = "photo")}>普通餐食照片</button
  >
  <button
    class:active={mealMode === "label"}
    onclick={() => (mealMode = "label")}>包装营养标签</button
  >
  <span class="small muted">草稿日期：{app.date}</span>
</div>
<div class="two-columns meal-upload-grid">
  <section class="panel">
    <div class="section-heading">
      <h3><Camera size={20} />餐食照片</h3>
      <span class="badge subtle"
        >{mealMode === "label" ? "读取营养标签" : "AI 辅助估算"}</span
      >
    </div>
    <input
      class="visually-hidden"
      type="file"
      aria-label="餐食照片文件"
      disabled={app.busy}
      bind:this={fileInput}
      accept="image/jpeg,image/png,image/webp,image/gif"
      onchange={(event) => {
        const file = event.currentTarget.files?.[0];
        event.currentTarget.value = "";
        void upload(file);
      }}
    />
    <button
      class="upload-area"
      type="button"
      aria-label={image
        ? "更换餐食照片，支持拖入图片"
        : "上传餐食照片，支持拖入图片"}
      aria-busy={app.busy}
      class:dragging
      ondragenter={dragEnter}
      ondragover={dragOver}
      ondragleave={dragLeave}
      ondrop={dropPhoto}
      onclick={() => fileInput?.click()}
      disabled={app.busy}
      >{#if image}<img
          src={imageUrl(image.id)}
          alt="已上传的餐食照片"
          onload={(event) => {
            const photo = event.currentTarget as HTMLImageElement;
            if (image) {
              image.width = photo.naturalWidth;
              image.height = photo.naturalHeight;
            }
          }}
        /><span class="replace-photo"
          ><ImagePlus size={16} />点击或拖入更换照片</span
        >{:else}<span class="upload-symbol"><Upload size={28} /></span><strong
          >拖入照片，或点击上传</strong
        ><span>JPEG、PNG、WebP、GIF · 最大 12 MB</span>{/if}
      {#if dragging}<span class="drop-photo-hint"
          ><ImagePlus size={30} /><strong>松开鼠标，上传这张照片</strong></span
        >{/if}</button
    >
    {#if image}<div class="photo-preview-meta">
        <span class="small muted"
          >{image.width && image.height
            ? `完整画面 · ${image.width} × ${image.height} px`
            : "完整画面"}</span
        >
        <button
          type="button"
          class="text-button"
          onclick={() => (preview = image)}
          ><Maximize2 size={14} />查看完整照片</button
        >
      </div>{/if}
  </section>
  <section class="panel">
    <div class="section-heading"><h3>告诉 AI，你实际吃了什么</h3></div>
    <label
      >餐次<select bind:value={slot}
        >{#each Object.entries(slots) as [value, label]}<option {value}
            >{label}</option
          >{/each}</select
      ></label
    ><label
      >补充说明<textarea
        bind:value={note}
        rows="4"
        maxlength="2000"
        placeholder="例如：鸡蛋只吃蛋白；米饭只吃一半；包装食品每袋60克，实际吃了2袋。"
      ></textarea></label
    >
    <div class="prompt-chips">
      {#each ["鸡蛋只吃蛋白", "米饭只吃一半", "虾去头去壳"] as hint}<button
          class="chip"
          onclick={() => (note = note ? `${note}；${hint}` : hint)}
          >{hint}</button
        >{/each}
    </div>
    <div class="info-note">
      {#if mealMode === "label"}AI只读取标签原始数值。核对每100克或每份、千焦或千卡，再填写实际克数或袋数；看不清的字段保持空白，可手动补充。
      {:else}照片无法精确反映重量、用油与食物身份。识别完成后，你可以逐项修改，再确认计入当天。{/if}
      包装标签尽量正对镜头、避免反光。
    </div>
    <button
      class="primary full"
      disabled={!image || app.busy || active || !app.ai?.api_key_set}
      onclick={analyze}
      >{#if active}<LoaderCircle
          size={17}
          class="spin"
        />正在分析餐食…{:else}<Sparkles size={17} />{mealMode === "label"
          ? "开始读取标签"
          : "开始估算热量"}{/if}</button
    >{#if !app.ai?.api_key_set}<p class="small muted">
        AI 尚未配置，仍可{mealMode === "label"
          ? "手动填写标签并计算"
          : "手动记一餐"}。
      </p>{/if}
  </section>
</div>
<DietHistory
  onedit={edit}
  ondelete={(meal) => (deleting = meal)}
  ondeletejob={askDeleteJob}
  onview={view}
  onretry={(job) => void retry(job)}
  onmanual={manualFromJob}
  onlabel={(job) => void retryLabel(job)}
  onphoto={(id) => (preview = { id })}
  onadd={(day) => void addDay(day)}
/>
{#if preview}<Modal title="完整餐食照片" wide onclose={() => (preview = null)}>
    <p>
      按原图比例显示，不裁剪；可滚动查看整张照片。AI
      使用完整画面，必要时会等比缩小。
    </p>
    <img
      class="full-meal-photo"
      src={imageUrl(preview.id)}
      alt="完整餐食原图"
    />
  </Modal>{/if}
{#if labelDraft}<NutritionLabelEditor
    meal={labelDraft}
    onclose={() => (labelDraft = null)}
  />{/if}
{#if draft}<Modal
    title={draft.id ? "修改餐食记录" : "确认这餐的食物与份量"}
    wide
    onclose={() => (draft = null)}
    ><form onsubmit={save}>
      <div class="form-grid">
        <label
          >记录日期<input type="date" bind:value={draft.date} required /></label
        ><label
          >餐次<select bind:value={draft.slot}
            >{#each Object.entries(slots) as [value, label]}<option {value}
                >{label}</option
              >{/each}</select
          ></label
        >
      </div>
      <label
        >餐食标题 <span>可选</span><input
          bind:value={draft.title}
          maxlength="100"
          placeholder="例如：训练后的午餐"
        /></label
      >{#if assumptions.length}<div class="assumptions">
          <strong>识别时的假设，请核对</strong
          >{#each assumptions as assumption}<p>· {assumption}</p>{/each}
        </div>{/if}
      <div class="food-editor">
        {#each draft.items as item, index}<div class="food-row">
            <div class="food-row-title">
              <span class="food-index"
                >{String(index + 1).padStart(2, "0")}</span
              ><input
                aria-label="食物名称"
                bind:value={item.name}
                required
                maxlength="100"
                placeholder="食物名称"
              /><button
                type="button"
                class="icon-button danger"
                aria-label="移除食物"
                disabled={draft.items.length <= 1}
                onclick={() => draft!.items.splice(index, 1)}
                ><Trash2 size={16} /></button
              >
            </div>
            <label
              >实际食用部分<input
                bind:value={item.consumed_part}
                maxlength="300"
                placeholder="例如：3 个蛋清，不含蛋黄"
              /></label
            >
            <div class="form-grid food-numbers">
              <label
                >食用重量 / g<input
                  aria-label="食用重量"
                  type="number"
                  min="0"
                  max="10000"
                  step="0.1"
                  value={item.estimated_edible_grams}
                  oninput={(event) => scale(item, event)}
                  required
                /></label
              ><label
                >热量 / kcal<input
                  aria-label="食物热量"
                  type="number"
                  min="0"
                  max="20000"
                  step="0.1"
                  bind:value={item.kcal}
                  required
                /></label
              ><label
                >蛋白质 / g<input
                  type="number"
                  min="0"
                  max="2000"
                  step="0.1"
                  bind:value={item.protein_g}
                  required
                /></label
              ><label
                >碳水 / g<input
                  type="number"
                  min="0"
                  max="5000"
                  step="0.1"
                  bind:value={item.carbs_g}
                  required
                /></label
              ><label
                >脂肪 / g<input
                  type="number"
                  min="0"
                  max="2000"
                  step="0.1"
                  bind:value={item.fat_g}
                  required
                /></label
              ><label
                >膳食纤维 / g<input type="number" min="0" max="2000" step="0.1" bind:value={item.fiber_g} placeholder="未知留空" /></label
              ><label
                >总糖 / g<input type="number" min="0" max="2000" step="0.1" bind:value={item.sugar_g} placeholder="未知留空" /></label
              ><label
                >钠 / mg<input type="number" min="0" max="100000" step="1" bind:value={item.sodium_mg} placeholder="未知留空" /></label
              >
            </div>
          </div>{/each}
      </div>
      <button
        type="button"
        class="text-button"
        onclick={() => draft!.items.push(blankFood())}
        ><Plus size={16} />补充一种食物</button
      ><div class="meal-ai-entry">
        <label
          >餐食描述<textarea bind:value={mealDescription} rows="2" maxlength="4000" placeholder="例如：一碗米饭、两块煎鸡胸肉，约 150 克，少油"></textarea></label
        ><button type="button" class="secondary" disabled={estimatingMeal || app.busy || mealDescription.trim().length < 3} onclick={estimateManual}><Sparkles size={16} />{estimatingMeal ? "估算中…" : "AI 生成营养草稿"}</button>
      </div>
      {#if draft.items.some((item) => item.fiber_g != null || item.sugar_g != null || item.sodium_mg != null)}<div class="nutrient-summary">
        <span>膳食纤维 <strong>{number(draft.items.every((item) => item.fiber_g != null) ? draft.items.reduce((sum, item) => sum + (item.fiber_g || 0), 0) : null, 1)} g</strong></span>
        <span>总糖 <strong>{number(draft.items.every((item) => item.sugar_g != null) ? draft.items.reduce((sum, item) => sum + (item.sugar_g || 0), 0) : null, 1)} g</strong></span>
        <span>钠 <strong>{number(draft.items.every((item) => item.sodium_mg != null) ? draft.items.reduce((sum, item) => sum + (item.sodium_mg || 0), 0) : null, 0)} mg</strong></span>
      </div>{/if}
      ><label
        >餐食备注<textarea bind:value={draft.note} rows="2" maxlength="2000"
        ></textarea></label
      >
      <div class="two-columns meal-distribution">
        <div>
          <h4>各食物热量占比</h4>
          <Chart
            option={draftFoodChart}
            height={160}
            label="餐内各食物热量比例"
          />
          <div class="small muted">
            {draft.items.map((item) => item.name).join(" · ")}
          </div>
        </div>
        <div>
          <h4>三大营养素供能占比</h4>
          <Chart
            option={draftMacroChart}
            height={160}
            label="蛋白质碳水脂肪供能比例"
          />
          <div class="small muted">
            蛋白质 / 碳水 / 脂肪 · 4 / 4 / 9 kcal 每克
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <strong>合计 {number(draftTotal)} kcal</strong><button
          class="primary"
          disabled={app.busy}
          ><Check size={17} />{draft.id ? "保存修改" : "确认并计入当天"}</button
        >
      </div>
    </form></Modal
  >{/if}
{#if deletingJob}<Modal
    title="删除这条餐食分析记录？"
    onclose={() => {
      if (!app.busy) deletingJob = null;
    }}
    ><p><strong>{deletingJob.date} · {slots[deletingJob.request.slot || "lunch"]}</strong></p>
    <p>删除后无法在页面撤销或恢复。已入账餐食、摄入统计和原图将保留，已有备份不受影响。</p>
    {#if deleteJobError}<p class="goal-error" role="alert">{deleteJobError}</p>{/if}
    <div class="form-actions">
      <button class="secondary" disabled={app.busy} onclick={() => (deletingJob = null)}>取消</button>
      <button class="danger-button" disabled={app.busy} onclick={() => void removeJob()}
        >{#if app.busy}<LoaderCircle size={16} class="spin" />删除中…{:else}确认删除{/if}</button>
    </div></Modal
  >{/if}
{#if deleting}<Modal title="删除这餐记录？" onclose={() => (deleting = null)}
    ><p>删除后，当天摄入与估计热量缺口会重新汇总。</p>
    <div class="form-actions">
      <button class="secondary" onclick={() => (deleting = null)}>取消</button
      ><button
        class="danger-button"
        disabled={app.busy}
        onclick={async () => {
          if (
            await perform(
              () => api.delete(`/meals/${deleting?.id}`),
              "餐食记录已删除",
            )
          )
            deleting = null;
        }}>确认删除</button
      >
    </div></Modal
  >{/if}
