/** Android service calculations; parity-tested against the Python ledger. */
import contracts from "./mobile-contracts.json";
import * as compiledValidators from "./mobile-validators.js";
export type Data = Record<string, any>;
const validators: Record<string, (data: unknown) => boolean> =
  compiledValidators;
export const activities = contracts.activities;
export const levels: Record<string, { label: string; factor: number }> =
  contracts.activity_levels;
export const trackingStart = "2026-10-15";

export function round(value: number, places = 2) {
  if (!Number.isFinite(value)) throw new Error("计算值必须为有限数");
  if (value === 0) return value;
  // Python rounds the exact IEEE-754 value, not value*10**places. Keeping
  // the binary significand avoids the 2.675 -> 2.68 double-rounding trap.
  const buffer = new ArrayBuffer(8),
    view = new DataView(buffer);
  view.setFloat64(0, Math.abs(value));
  const bits = view.getBigUint64(0),
    exponent = Number((bits >> 52n) & 2047n);
  let numerator = (bits & ((1n << 52n) - 1n)) + (exponent ? 1n << 52n : 0n);
  const shift = (exponent ? exponent - 1023 : -1022) - 52;
  let denominator = 1n;
  numerator *= 10n ** BigInt(places);
  if (shift >= 0) numerator <<= BigInt(shift);
  else denominator <<= BigInt(-shift);
  let integral = numerator / denominator;
  const twice = (numerator % denominator) * 2n;
  if (twice > denominator || (twice === denominator && integral % 2n === 1n))
    integral++;
  return (Math.sign(value) * Number(integral)) / 10 ** places;
}
export const shanghaiToday = () =>
  new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10);
export function shift(day: string, amount: number) {
  return new Date(Date.parse(day + "T12:00:00Z") + amount * 86400000)
    .toISOString()
    .slice(0, 10);
}
export function dates(start: string, end: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end))
    throw new Error("日期格式无效");
  if (
    !Number.isFinite(Date.parse(start + "T12:00:00Z")) ||
    new Date(start + "T12:00:00Z").toISOString().slice(0, 10) !== start ||
    !Number.isFinite(Date.parse(end + "T12:00:00Z")) ||
    new Date(end + "T12:00:00Z").toISOString().slice(0, 10) !== end
  )
    throw new Error("日期不存在");
  const length = (Date.parse(end) - Date.parse(start)) / 86400000;
  if (!Number.isInteger(length) || length < 0 || length > 365)
    throw new Error("日期范围应为 0 至 365 天");
  return Array.from({ length: length + 1 }, (_, i) => shift(start, i));
}
export function validate(name: string, raw: Data): Data {
  const value = structuredClone(raw);
  if (name === "Meal" && value.nutrition_mode === "precise") {
    if (
      value.nutrition_label ||
      !value.meal_description?.trim() ||
      value.items?.length !== 1
    )
      throw new Error("精确录入需要整餐描述和一组营养总量");
    const item = value.items[0];
    for (const key of ["protein_g", "carbs_g", "fat_g"])
      if (!Number.isFinite(item[key]) || item[key] < 0)
        throw new Error("三大营养素必须为有效非负数");
    item.kcal = round(item.protein_g * 4 + item.carbs_g * 4 + item.fat_g * 9);
    value.source_job_id = null;
    value.assumptions = [];
  }
  const valid: boolean = !!validators[name]?.(value);
  if (!valid) throw new Error("数据格式或数值不符合 " + name + " 合约");
  if (name === "Profile" && value.resting_kcal == null && value.age == null)
    throw new Error("静息能量留空时需要填写年龄");
  if (
    name === "BodyRecord" &&
    ["weight_kg", "body_fat_pct", "resting_kcal"].every((k) => value[k] == null)
  )
    throw new Error("请至少填写一项身体数据");
  if (
    ["Meal", "MealEstimate"].includes(name) &&
    value.nutrition_mode !== "precise" &&
    value.items.some((v: Data) => v.estimated_edible_grams == null)
  )
    throw new Error("估算明细必须包含食用重量");
  if (name === "Meal" && value.nutrition_label)
    value.items = [labelFood(value.nutrition_label)];
  if (name === "GoalSuggestion") {
    const energy =
      value.protein_target_g * 4 +
      value.carbs_target_g * 4 +
      value.fat_target_g * 9;
    if (
      Math.abs(energy - value.calorie_target) >
      Math.max(20, value.calorie_target * 0.02)
    )
      throw new Error("营养素供能与热量目标不一致");
  }
  return value;
}
export function factor(profile: Data) {
  return (
    levels[profile.activity_level]?.factor ?? profile.activity_factor ?? 1.2
  );
}
export function restingEstimate(profile: Data, weight?: number | null) {
  if (!profile.age || !profile.height_cm) return null;
  const kg = weight || profile.initial_weight_kg;
  if (!kg) return null;
  return round(
    10 * kg +
      6.25 * profile.height_cm -
      5 * profile.age +
      ({ male: 5, female: -161, other: -78 }[profile.sex as string] ?? 5),
    0,
  );
}
export function nutrients(items: Data[]) {
  const result: Data = {};
  for (const key of ["kcal", "protein_g", "carbs_g", "fat_g"])
    result[key] = round(items.reduce((n, x) => n + x[key], 0));
  for (const key of ["fiber_g", "sugar_g", "sodium_mg"])
    result[key] =
      items.length && items.every((x) => x[key] != null)
        ? round(items.reduce((n, x) => n + x[key], 0))
        : null;
  const energy = {
    protein: result.protein_g * 4,
    carbs: result.carbs_g * 4,
    fat: result.fat_g * 9,
  };
  const total = Object.values(energy).reduce((a, b) => a + b, 0);
  result.macro_percent = Object.fromEntries(
    Object.entries(energy).map(([k, v]) => [
      k,
      total ? round((v / total) * 100) : 0,
    ]),
  );
  result.food_percent = items.map((x) =>
    result.kcal ? round((x.kcal / result.kcal) * 100) : 0,
  );
  return result;
}
export function workoutEnergy(workout: Data, weight: number, resting: number) {
  const activity = activities.find((x) => x.id === workout.activity);
  if (!activity && workout.met == null)
    throw new Error("未知运动类型，请填写 MET");
  const met = workout.met ?? (activity?.mets as Data)[workout.intensity];
  const minutes = workout.duration_minutes;
  const gross = (met * weight * minutes) / 60;
  const sets: Data[] = (workout.exercises || []).flatMap((x: Data) => x.sets);
  return {
    met,
    gross_kcal: round(gross),
    net_kcal: round(
      workout.net_kcal_override ??
        Math.max(0, gross - (resting * minutes) / 1440),
    ),
    volume_kg: round(sets.reduce((n, x) => n + x.weight_kg * x.reps, 0)),
    set_count: sets.length,
    rep_count: sets.reduce((n, x) => n + x.reps, 0),
    source: activity?.source ?? "手动 MET",
  };
}
export function labelFood(raw: Data) {
  const { label, portion } = validate("NutritionLabel", raw);
  for (const key of [
    "name",
    "basis_kind",
    "energy_value",
    "energy_unit",
    "protein_g",
    "carbs_g",
    "fat_g",
  ])
    if (label[key] == null || label[key] === "")
      throw new Error("请补充或确认标签必要字段");
  if (
    label.basis_kind === "per_100g" &&
    label.basis_grams != null &&
    label.basis_grams !== 100
  )
    throw new Error("每100克标签基准必须为100克");
  const basis = label.basis_kind === "per_100g" ? 100 : label.basis_grams;
  const grams =
    portion.mode === "grams"
      ? portion.grams
      : portion.pack_grams != null && portion.packs != null
        ? portion.pack_grams * portion.packs
        : null;
  if (!basis || !grams) throw new Error("请补充标签基准克数和实际食用份量");
  const ratio = grams / basis;
  const item: Data = {
    name: label.name,
    consumed_part:
      portion.mode === "grams"
        ? "按实际食用克数"
        : `每袋${portion.pack_grams}g × ${portion.packs}袋`,
    estimated_edible_grams: round(grams, 4),
    kcal: round(
      (label.energy_unit === "kJ"
        ? label.energy_value / 4.184
        : label.energy_value) * ratio,
    ),
  };
  for (const key of [
    "protein_g",
    "carbs_g",
    "fat_g",
    "fiber_g",
    "sugar_g",
    "sodium_mg",
  ])
    item[key] = label[key] == null ? null : round(label[key] * ratio);
  return validate("FoodItem", item);
}
export function canonical(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object")
    return (
      "{" +
      Object.keys(value)
        .filter((key) => (value as Data)[key] !== undefined)
        .sort()
        .map(
          (key) => JSON.stringify(key) + ":" + canonical((value as Data)[key]),
        )
        .join(",") +
      "}"
    );
  return JSON.stringify(value);
}
export async function sha(bytes: Uint8Array | string) {
  const data =
    typeof bytes === "string" ? new TextEncoder().encode(bytes) : bytes;
  return [
    ...new Uint8Array(
      await crypto.subtle.digest("SHA-256", data as Uint8Array<ArrayBuffer>),
    ),
  ]
    .map((x) => x.toString(16).padStart(2, "0"))
    .join("");
}
