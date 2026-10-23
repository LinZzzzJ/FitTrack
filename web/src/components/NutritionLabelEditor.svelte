<script lang="ts">
  import { untrack } from "svelte";
  import { Sparkles, Calculator, Check } from "@lucide/svelte";
  import Modal from "./Modal.svelte";
  import { api } from "../lib/api";
  import { app, number, perform } from "../lib/state.svelte";
  import type { Food, Meal, NutritionLabel } from "../lib/types";
  let { meal, onclose }: { meal: Meal; onclose: () => void } = $props();
  let record = $state<Meal>(
    untrack(() => structuredClone($state.snapshot(meal))),
  );
  let snapshot = $state<NutritionLabel>(
    untrack(() => structuredClone($state.snapshot(meal.nutrition_label!))),
  );
  let result = $state<Food | null>(null),
    resultKey = $state(""),
    error = $state(""),
    loading = $state(false);
  let key = $derived(JSON.stringify(snapshot));
  let ready = $derived(!!result && resultKey === key);
  async function calculate() {
    if (loading) return;
    loading = true;
    error = "";
    const requested = key;
    try {
      const value = await api.post<{ item: Food }>(
        "/nutrition-label/preview",
        JSON.parse(requested),
      );
      if (key === requested) {
        result = value.item;
        resultKey = requested;
      }
    } catch (e) {
      error = e instanceof Error ? e.message : "标签计算失败";
    } finally {
      loading = false;
    }
  }
  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!ready || !result) return;
    const { id, date, slot, title, note, assumptions, image_id, source_job_id } =
      $state.snapshot(record);
    const payload = {
      date, slot, title, note, assumptions, image_id, source_job_id,
      items: [result],
      nutrition_label: $state.snapshot(snapshot),
    };
    if (
      await perform(
        () =>
          id
            ? api.put(`/meals/${id}`, payload)
            : api.post("/meals", payload),
        "标签餐食已确认入账",
      )
    )
      onclose();
  }
</script>

<Modal
  title={record.id ? "修改包装食品记录" : "确认营养标签与实际份量"}
  wide
  {onclose}
>
  <form onsubmit={save}>
    <div class="section-heading">
      <h3><Sparkles size={18} />先核对标签，再确认份量</h3>
      <span class="badge subtle">预览不入账</span>
    </div>
    <div class="form-grid">
      <label
        >记录日期<input
          aria-label="标签记录日期"
          type="date"
          bind:value={record.date}
          required
        /></label
      >
      <label
        >餐次<select aria-label="标签餐次" bind:value={record.slot}
          ><option value="breakfast">早餐</option><option value="lunch"
            >午餐</option
          ><option value="dinner">晚餐</option><option value="snack"
            >加餐</option
          ></select
        ></label
      >
    </div>
    <label
      >商品名称<input
        aria-label="标签商品名称"
        bind:value={snapshot.label.name}
        required
        maxlength="100"
        placeholder="例如：低脂鸡胸肉丸"
      /></label
    >
    <div class="label-section">
      <h4>包装上写的是</h4>
      <div class="form-grid">
        <label
          >营养标示基准<select
            aria-label="营养标示基准"
            bind:value={snapshot.label.basis_kind}
            onchange={() => {
              snapshot.label.basis_grams =
                snapshot.label.basis_kind === "per_100g" ? 100 : null;
            }}
            required
            ><option value={null} disabled>请选择标签基准</option><option
              value="per_100g">每100克</option
            ><option value="per_serving">每份</option><option value="per_pack"
              >每包</option
            ></select
          ></label
        >
        <label
          >基准重量 / g<input
            aria-label="标签基准重量"
            type="number"
            min="0.01"
            max="10000"
            step="any"
            value={snapshot.label.basis_kind === "per_100g"
              ? 100
              : snapshot.label.basis_grams}
            oninput={(event) => {
              snapshot.label.basis_grams =
                event.currentTarget.valueAsNumber || null;
            }}
            disabled={snapshot.label.basis_kind === "per_100g"}
            required
          /></label
        >
        <label
          >标签能量<input
            aria-label="标签能量"
            type="number"
            min="0"
            max="100000"
            step="any"
            bind:value={snapshot.label.energy_value}
            required
          /></label
        >
        <label
          >能量单位<select
            aria-label="标签能量单位"
            bind:value={snapshot.label.energy_unit}
            required
            ><option value={null} disabled>请选择能量单位</option><option
              value="kJ">千焦 kJ</option
            ><option value="kcal">千卡 kcal</option></select
          ></label
        >
      </div>
      <div class="form-grid three">
        <label
          >蛋白质 / g<input
            aria-label="标签蛋白质"
            type="number"
            min="0"
            max="2000"
            step="any"
            bind:value={snapshot.label.protein_g}
            required
          /></label
        >
        <label
          >碳水 / g<input
            aria-label="标签碳水"
            type="number"
            min="0"
            max="5000"
            step="any"
            bind:value={snapshot.label.carbs_g}
            required
          /></label
        >
        <label
          >脂肪 / g<input
            aria-label="标签脂肪"
            type="number"
            min="0"
            max="2000"
            step="any"
            bind:value={snapshot.label.fat_g}
            required
          /></label
        >
        <label>膳食纤维 / g<input type="number" min="0" max="2000" step="any" bind:value={snapshot.label.fiber_g} placeholder="标签未列可留空" /></label>
        <label>总糖 / g<input type="number" min="0" max="2000" step="any" bind:value={snapshot.label.sugar_g} placeholder="标签未列可留空" /></label>
        <label>钠 / mg<input type="number" min="0" max="100000" step="any" bind:value={snapshot.label.sodium_mg} placeholder="标签未列可留空" /></label>
      </div>
      <p class="small muted">
        以上数值使用同一个标签基准。NRV%不是克数；识别缺项保持空白，请按包装补充。
      </p>
      {#if snapshot.label.assumptions.length}<details class="weekly-missing">
          <summary>AI读取时的不确定信息</summary
          >{#each snapshot.label.assumptions as value}<p>{value}</p>{/each}
        </details>{/if}
    </div>
    <div class="label-section">
      <h4>你实际吃了多少</h4>
      <label
        >份量录入方式<select
          aria-label="标签份量方式"
          bind:value={snapshot.portion.mode}
          ><option value="grams">实际食用克数</option><option value="packs"
            >每袋重量 × 实际袋数</option
          ></select
        ></label
      >
      {#if snapshot.portion.mode === "grams"}<label
          >实际食用克数 / g<input
            aria-label="标签实际克数"
            type="number"
            min="0.01"
            max="10000"
            step="any"
            bind:value={snapshot.portion.grams}
            required
          /></label
        >
      {:else}<div class="form-grid">
          <label
            >每袋重量 / g<input
              aria-label="标签每袋重量"
              type="number"
              min="0.01"
              max="10000"
              step="any"
              bind:value={snapshot.portion.pack_grams}
              required
            /></label
          ><label
            >实际食用袋数<input
              aria-label="标签实际袋数"
              type="number"
              min="0.01"
              max="1000"
              step="any"
              bind:value={snapshot.portion.packs}
              required
              placeholder="支持0.5袋"
            /></label
          >
        </div>{/if}
    </div>
    {#if error}<p class="goal-error" role="alert">{error}</p>{/if}
    <button
      type="button"
      class="secondary"
      disabled={loading || app.busy}
      onclick={calculate}
      ><Calculator size={16} />{loading ? "正在计算…" : "计算实际摄入"}</button
    >
    {#if result}<div class="label-result" aria-label="标签摄入预览">
        <strong>{number(result.kcal, 2)} kcal</strong>
        <p>
          {number(result.estimated_edible_grams, 2)} g · 蛋白质 {number(
            result.protein_g,
            2,
          )} g · 碳水 {number(result.carbs_g, 2)} g · 脂肪 {number(
            result.fat_g,
            2,
          )} g · 纤维 {number(result.fiber_g, 2)} g · 糖 {number(result.sugar_g, 2)} g · 钠 {number(result.sodium_mg, 0)} mg
        </p>
        {#if !ready}<p class="goal-stale">
            标签或份量已变化，请重新计算。
          </p>{/if}<span class="small muted"
          >千焦 ÷ 4.184，按实际克数缩放；确认保存后计入所选日期。</span
        >
      </div>{/if}
    <label
      >餐食备注<textarea bind:value={record.note} rows="2" maxlength="2000"
      ></textarea></label
    >
    <div class="modal-footer">
      <span class="small muted">入账日期：{record.date}</span><button
        class="primary"
        disabled={!ready || app.busy || loading}
        ><Check size={16} />{record.id
          ? "保存标签修改"
          : "确认标签并计入当天"}</button
      >
    </div>
  </form>
</Modal>
