import {
  activities,
  canonical,
  dates,
  factor,
  labelFood,
  nutrients,
  restingEstimate,
  round,
  sha,
  shanghaiToday,
  shift,
  trackingStart,
  validate,
  workoutEnergy,
  type Data,
} from "./ledger";
export const tableNames = [
  "profiles",
  "bodies",
  "images",
  "entries",
  "jobs",
  "feedback",
  "days",
  "workout_templates",
] as const;
export type Table = (typeof tableNames)[number];
export type Tables = Record<Table, Data[]>;
export const emptyTables = (): Tables =>
  Object.fromEntries(tableNames.map((t) => [t, []])) as unknown as Tables;
export function identifier() {
  return [...crypto.getRandomValues(new Uint8Array(12))]
    .map((x) => x.toString(16).padStart(2, "0"))
    .join("");
}
export const rowKey = (table: Table, row: Data) => row.id ?? row.date;
export const unpack = (row: Data) => ({
  ...JSON.parse(row.data),
  ...(row.id ? { id: row.id, created_at: row.created_at } : {}),
});
export const payloadModel: Record<string, string> = {
  profiles: "Profile",
  bodies: "BodyRecord",
  workout_templates: "WorkoutTemplate",
  meal: "Meal",
  workout: "Workout",
  plan: "TrainingPlan",
};
export class Health {
  constructor(
    public tables: Tables,
    public owner: string,
    public storageScope: string = "",
  ) {}
  rows(table: Table) {
    return this.tables[table];
  }
  find(table: Table, id: string) {
    const value = this.rows(table).find((x) => rowKey(table, x) === id);
    if (!value) throw new Error("记录不存在或不属于当前账号");
    return value;
  }
  upsert(table: Table, row: Data) {
    const index = this.rows(table).findIndex(
      (x) => rowKey(table, x) === rowKey(table, row),
    );
    if (index < 0) this.rows(table).push(row);
    else this.rows(table)[index] = row;
  }
  remove(table: Table, key: string) {
    this.find(table, key);
    this.tables[table] = this.rows(table).filter(
      (x) => rowKey(table, x) !== key,
    );
  }
  body(day: string) {
    const row = this.rows("bodies").find((x) => x.date === day);
    return row ? unpack(row) : null;
  }
  weight(day: string, fallback: number) {
    const row = [...this.rows("bodies")]
      .filter((x) => x.date <= day)
      .sort((a, b) => b.date.localeCompare(a.date))
      .find((x) => unpack(x).weight_kg != null);
    return row ? unpack(row).weight_kg : fallback;
  }
  profile(day: string) {
    const sorted = [...this.rows("profiles")].sort((a, b) =>
      a.date.localeCompare(b.date),
    );
    const row = sorted.filter((x) => x.date <= day).at(-1) || sorted[0];
    if (!row) return null;
    const p = unpack(row);
    p.estimated_resting_kcal = restingEstimate(
      p,
      this.weight(day, p.initial_weight_kg),
    );
    p.estimated_maintenance_kcal =
      (p.resting_kcal ?? p.estimated_resting_kcal) == null
        ? null
        : round((p.resting_kcal ?? p.estimated_resting_kcal) * factor(p), 1);
    return p;
  }
  entries(kind: string, start: string, end = start): Data[] {
    return this.rows("entries")
      .filter((x) => x.kind === kind && x.date >= start && x.date <= end)
      .sort(
        (a, b) => a.date.localeCompare(b.date) || a.created_at - b.created_at,
      )
      .map(unpack);
  }
  plans(start: string, end = start) {
    return this.entries("plan", start, end).map((p) => {
      const workout = this.rows("entries").find(
        (x) => x.kind === "workout" && x.plan_id === p.id,
      );
      return {
        ...p,
        status: workout ? "completed" : p.status,
        workout_id: workout?.id || null,
      };
    });
  }
  saveProfile(raw: Data) {
    const data = validate("Profile", raw);
    this.upsert("profiles", {
      user_id: this.owner,
      date: data.effective_date,
      data: canonical(data),
    });
    return this.profile(data.effective_date);
  }
  saveBody(raw: Data) {
    const data = validate("BodyRecord", raw);
    this.upsert("bodies", {
      user_id: this.owner,
      date: data.date,
      data: canonical(data),
    });
    return data;
  }
  saveTemplate(raw: Data, id?: string) {
    if (id) this.find("workout_templates", id);
    const data = validate("WorkoutTemplate", raw);
    const key = id || identifier();
    this.upsert("workout_templates", {
      user_id: this.owner,
      id: key,
      data: canonical(data),
      created_at: id
        ? this.find("workout_templates", id).created_at
        : Date.now() / 1000,
    });
    return { ...data, id: key };
  }
  saveEntry(kind: string, raw: Data, id?: string): Data {
    if (id && this.find("entries", id).kind !== kind)
      throw new Error("记录类型不匹配");
    const data = validate(payloadModel[kind], raw);
    if (kind === "meal") {
      if (data.image_id) this.find("images", data.image_id);
      if (data.source_job_id) {
        const j = this.job(data.source_job_id);
        if (
          j.kind !== "meal" ||
          j.status !== "done" ||
          (j.request.image_id ?? null) !== data.image_id
        )
          throw new Error("识餐任务与照片不匹配");
        const prior = this.rows("entries").find(
          (x) => x.source_job_id === data.source_job_id,
        );
        if (prior && !id) return unpack(prior);
      }
    }
    if (kind === "workout") {
      workoutEnergy(data, 75, 1800);
      if (data.ai_estimate_job_id) {
        const source = this.job(data.ai_estimate_job_id);
        const input = {
          kind: data.kind,
          activity: data.activity,
          duration_minutes: data.duration_minutes,
          intensity: data.intensity,
          description: data.note,
        };
        if (
          source.kind !== "cardio_estimate" ||
          source.status !== "done" ||
          source.date !== data.date ||
          canonical(source.request.cardio_input) !== canonical(input) ||
          source.result.estimate.effective_met !== data.met ||
          data.net_kcal_override != null
        )
          throw new Error("有氧估算来源与记录不匹配");
      }
      if (data.plan_id) {
        const plan = unpack(this.find("entries", data.plan_id));
        if (
          this.find("entries", data.plan_id).kind !== "plan" ||
          plan.status === "skipped"
        )
          throw new Error("排期未就绪");
        const prior = this.rows("entries").find(
          (x) => x.plan_id === data.plan_id,
        );
        if (prior && !id) return unpack(prior);
      }
    }
    const key = id || identifier();
    this.upsert("entries", {
      id: key,
      user_id: this.owner,
      kind,
      date: data.date,
      data: canonical(data),
      source_job_id: data.source_job_id ?? null,
      plan_id: kind === "workout" ? (data.plan_id ?? null) : null,
      created_at: id ? this.find("entries", id).created_at : Date.now() / 1000,
    });
    return unpack(this.find("entries", key));
  }
  deleteEntry(kind: string, key: string) {
    if (this.find("entries", key).kind !== kind)
      throw new Error("记录类型不匹配");
    if (kind === "plan" && this.rows("entries").some((x) => x.plan_id === key))
      throw new Error("已有训练引用该排期，请先删除或解除关联");
    this.remove("entries", key);
  }
  job(key: string): Data {
    const row = this.find("jobs", key);
    return {
      ...row,
      request: JSON.parse(row.request),
      result: row.result ? JSON.parse(row.result) : null,
    };
  }
  summary(day: string) {
    const profile = this.profile(day),
      body = this.body(day);
    const meals = this.entries("meal", day),
      workouts = this.entries("workout", day);
    const weight = profile ? this.weight(day, profile.initial_weight_kg) : null;
    const resting =
      body?.resting_kcal ??
      profile?.resting_kcal ??
      profile?.estimated_resting_kcal ??
      null;
    meals.forEach((m) => (m.totals = nutrients(m.items)));
    if (profile)
      workouts.forEach((w) => (w.energy = workoutEnergy(w, weight!, resting!)));
    const total = nutrients(meals.flatMap((m) => m.items));
    const exercise = workouts.reduce(
      (n, w) => n + (w.energy?.net_kcal || 0),
      0,
    );
    const base = profile && resting ? resting * factor(profile) : null;
    const expenditure = base == null ? null : base + exercise;
    const feedback = this.rows("feedback").find((x) => x.date === day);
    return {
      date: day,
      profile,
      body,
      effective_weight_kg: weight,
      resting_kcal: resting,
      meals,
      workouts,
      totals: total,
      exercise_kcal: round(exercise),
      baseline_kcal: base == null ? null : round(base),
      expenditure_kcal: expenditure == null ? null : round(expenditure),
      deficit_kcal:
        expenditure == null ? null : round(expenditure - total.kcal),
      duration_minutes: workouts.reduce((n, w) => n + w.duration_minutes, 0),
      volume_kg: round(
        workouts.reduce((n, w) => n + (w.energy?.volume_kg || 0), 0),
      ),
      completed: this.rows("days").some(
        (x) => x.date === day && x.completed === 1,
      ),
      jobs: this.rows("jobs")
        .filter((x) => x.date === day)
        .sort((a, b) => b.created_at - a.created_at)
        .map((j) => this.job(j.id)),
      feedback: feedback
        ? {
            data: JSON.parse(feedback.data),
            stale: false,
            created_at: feedback.created_at,
          }
        : null,
      plans: this.plans(day),
    };
  }
  trends(start: string, end: string, measurementStart?: string) {
    return {
      days: dates(start, end).map((day) => {
        const s = this.summary(day);
        const beginning = [shift(day, -6), measurementStart || "0000-01-01"]
          .sort()
          .at(-1)!;
        const weights = this.rows("bodies")
          .filter((x) => x.date >= beginning && x.date <= day)
          .map(unpack)
          .map((x) => x.weight_kg)
          .filter((x) => x != null);
        return {
          ...s,
          meal_count: s.meals.length,
          weight_average_7d: weights.length
            ? round(weights.reduce((a, b) => a + b, 0) / weights.length)
            : null,
        };
      }),
      plans: this.plans(start, end),
    };
  }
  context(day: string) {
    return {
      date: day,
      days: dates(shift(day, -6), day).map((d) => {
        const { jobs: _j, feedback: _f, ...s } = this.summary(d);
        return s;
      }),
      plans: this.plans(day, shift(day, 1)),
    };
  }
  cardioContext(day: string, input: Data) {
    const activity = activities.find(
      (x) => x.id === input.activity && x.kind === "cardio",
    );
    const p = this.profile(day);
    if (!activity || !p)
      throw new Error("AI 有氧估算需要已列出的有氧类型和身体资料");
    return {
      date: day,
      input,
      activity_name: activity.name,
      reference_met: (activity.mets as Data)[input.intensity],
      reference_source: activity.source,
      weight_kg: this.weight(day, p.initial_weight_kg),
      resting_kcal:
        this.body(day)?.resting_kcal ??
        p.resting_kcal ??
        p.estimated_resting_kcal,
    };
  }
  goalContext(day: string, draft: Data) {
    const weight = this.weight(day, draft.initial_weight_kg);
    const resting =
      this.body(day)?.resting_kcal ??
      draft.resting_kcal ??
      restingEstimate(draft, weight);
    let trainingDays = 0;
    const recent = dates(shift(day, -6), day).map((date) => {
      const measured = this.body(date),
        meals = this.entries("meal", date),
        workouts = this.entries("workout", date);
      const dailyWeight = this.weight(date, draft.initial_weight_kg);
      const dailyRest =
        measured?.resting_kcal ??
        draft.resting_kcal ??
        restingEstimate(draft, dailyWeight) ??
        1800;
      const exercise = workouts.reduce(
        (sum, w) => sum + workoutEnergy(w, dailyWeight, dailyRest).net_kcal,
        0,
      );
      if (workouts.length) trainingDays++;
      return {
        date,
        weight_kg: measured?.weight_kg ?? null,
        body_fat_pct: measured?.body_fat_pct ?? null,
        recorded_intake_kcal: meals.length
          ? nutrients(meals.flatMap((m) => m.items)).kcal
          : null,
        recorded_exercise_net_kcal: round(exercise, 1),
        recorded_training_minutes: workouts.reduce(
          (sum, w) => sum + w.duration_minutes,
          0,
        ),
      };
    });
    const average = round(
      recent.reduce((sum, d) => sum + d.recorded_exercise_net_kcal, 0) / 7,
      1,
    );
    const profile = Object.fromEntries(
      [
        "height_cm",
        "initial_weight_kg",
        "sex",
        "body_fat_pct",
        "resting_kcal",
        "age",
        "activity_level",
        "activity_factor",
        "target_weight_kg",
      ].map((key) => [key, draft[key] ?? null]),
    );
    return {
      date: day,
      profile,
      current_weight_kg: weight,
      resting_kcal: resting,
      average_exercise_net_kcal_7d: average,
      recorded_training_days_7d: trainingDays,
      estimated_maintenance_kcal: round(resting * factor(draft) + average, 1),
      recent_days: recent,
    };
  }
  weekly(start?: string): Data {
    const today = shanghaiToday();
    const current = Math.max(
      0,
      Math.floor((Date.parse(today) - Date.parse(trackingStart)) / 604800000),
    );
    const first = start || shift(trackingStart, Math.max(0, current - 1) * 7);
    if (
      first < trackingStart ||
      (Date.parse(first) - Date.parse(trackingStart)) % 604800000
    )
      throw new Error("周起始日期必须从 2026-10-15 起每隔7天");
    const end = shift(first, 6),
      rows = dates(first, end).map((d) => this.summary(d));
    const complete = (key: string) =>
      rows.every((d) => (d as Data)[key] != null)
        ? round(rows.reduce((n, d) => n + (d as Data)[key], 0))
        : null;
    const weights = rows.map((d) => d.body?.weight_kg).filter((x) => x != null),
      fats = rows.map((d) => d.body?.body_fat_pct).filter((x) => x != null);
    const sum = (key: string) =>
      round(rows.reduce((n, d) => n + d.totals[key], 0));
    const statistics = {
      intake_total_kcal: sum("kcal"),
      average_intake_kcal: round(sum("kcal") / 7),
      average_protein_g: round(sum("protein_g") / 7),
      average_carbs_g: round(sum("carbs_g") / 7),
      average_fat_g: round(sum("fat_g") / 7),
      expenditure_total_kcal: complete("expenditure_kcal"),
      deficit_total_kcal: complete("deficit_kcal"),
      training_sessions: rows.reduce((n, d) => n + d.workouts.length, 0),
      training_days: rows.filter((d) => d.workouts.length).length,
      rest_days: rows.filter((d) => !d.workouts.length).length,
      duration_minutes: complete("duration_minutes"),
      volume_kg: complete("volume_kg"),
      weight_change_kg:
        weights.length >= 2 ? round(weights.at(-1) - weights[0]) : null,
      body_fat_change_pct:
        fats.length >= 2 ? round(fats.at(-1) - fats[0]) : null,
      weight_measurements: weights.length,
      body_fat_measurements: fats.length,
    };
    const missing = rows
      .filter((d) => !d.meals.length || !d.completed)
      .map((d) => ({
        date: d.date,
        reasons: [
          ...(!d.meals.length ? ["缺少已确认饮食"] : []),
          ...(!d.completed ? ["尚未完成当日记录"] : []),
        ],
      }));
    const jobs = this.rows("jobs")
      .filter((j) => j.kind === "weekly_review" && j.date === end)
      .sort((a, b) => b.created_at - a.created_at)
      .map((j) => this.job(j.id));
    return {
      week_start: first,
      week_end: end,
      week_number:
        Math.floor(
          (Date.parse(first) - Date.parse(trackingStart)) / 604800000,
        ) + 1,
      earliest_generation_date: shift(end, 1),
      today,
      closed: end < today,
      completed_days: 7 - missing.length,
      missing_dates: missing,
      can_generate:
        end < today &&
        !missing.length &&
        !jobs.some((j) => ["queued", "running"].includes(j.status)),
      reason:
        end >= today
          ? "本周尚未结束"
          : missing.length
            ? "请补齐7天饮食并完成记录"
            : "",
      available_weeks: Array.from({ length: current + 1 }, (_, i) =>
        shift(trackingStart, i * 7),
      ).reverse(),
      statistics,
      report: jobs.find((j) => j.status === "done") || null,
      active_job:
        jobs.find((j) => ["queued", "running"].includes(j.status)) || null,
      latest_job: jobs[0] || null,
      days: rows,
    };
  }
  async fingerprint(request: Data) {
    return sha(
      canonical(
        request.kind === "goals"
          ? this.goalContext(request.date, request.goal_profile)
          : request.kind === "cardio_estimate"
            ? this.cardioContext(request.date, request.cardio_input)
            : request.kind === "weekly_review"
              ? this.weekly(request.week_start).days
              : this.context(request.date),
      ),
    );
  }
}

export const columns: Record<Table, string[]> = {
  profiles: ["user_id", "date", "data"],
  bodies: ["user_id", "date", "data"],
  images: ["id", "user_id", "sha", "ext", "width", "height", "created_at"],
  entries: [
    "id",
    "user_id",
    "kind",
    "date",
    "data",
    "source_job_id",
    "plan_id",
    "created_at",
  ],
  jobs: [
    "id",
    "user_id",
    "kind",
    "date",
    "request_key",
    "request",
    "status",
    "result",
    "error",
    "source_hash",
    "created_at",
    "finished_at",
  ],
  feedback: ["user_id", "date", "data", "source_hash", "created_at"],
  days: ["user_id", "date", "completed"],
  workout_templates: ["user_id", "id", "data", "created_at"],
};
export function validateTables(raw: unknown, owner: string): Tables {
  if (!raw || typeof raw !== "object" || Array.isArray(raw))
    throw new Error("备份数据表无效");
  const tables = structuredClone(raw) as Tables;
  const names = Object.keys(tables);
  if (
    names.some((t) => !tableNames.includes(t as Table)) ||
    tableNames
      .filter((t) => t !== "workout_templates")
      .some((t) => !names.includes(t))
  )
    throw new Error("备份表白名单不匹配");
  tables.workout_templates ||= [];
  const ownerIds = new Set<string>();
  for (const table of tableNames) {
    if (!Array.isArray(tables[table]) || tables[table].length > 100000)
      throw new Error("备份记录数量异常");
    const keys = new Set();
    for (const row of tables[table]) {
      if (
        !row ||
        canonical(Object.keys(row).sort()) !==
          canonical([...columns[table]].sort())
      )
        throw new Error("备份字段与 PC v2 合约不匹配");
      if (
        typeof row.user_id !== "string" ||
        !/^[a-f0-9]{24}$/.test(row.user_id)
      )
        throw new Error("备份归属标记无效");
      ownerIds.add(row.user_id);
      const key = rowKey(table, row);
      if (
        typeof key !== "string" ||
        keys.has(key) ||
        (row.id && !/^[a-f0-9]{24}$/.test(row.id))
      )
        throw new Error("备份记录ID重复或无效");
      keys.add(key);
      if (row.date) dates(row.date, row.date);
      if (row.data) {
        const data = JSON.parse(row.data);
        if (table === "feedback") validate("CoachFeedback", data);
        else {
          const model = payloadModel[table === "entries" ? row.kind : table];
          if (!model) throw new Error("不支持的记录类型");
          const result = validate(model, data);
          if (
            table === "entries" &&
            row.kind === "meal" &&
            result.nutrition_mode === "precise"
          )
            row.data = canonical(result);
          if (row.date && (result.date || result.effective_date) !== row.date)
            throw new Error("记录日期不一致");
          if (
            table === "entries" &&
            row.kind === "meal" &&
            data.nutrition_label &&
            canonical(data.items) !==
              canonical([labelFood(data.nutrition_label)])
          )
            throw new Error("标签换算与明细不一致");
        }
      }
      if (
        table === "images" &&
        (!/^[a-f0-9]{64}$/.test(row.sha) ||
          !["jpg", "png", "gif", "webp"].includes(row.ext) ||
          !Number.isInteger(row.width) ||
          !Number.isInteger(row.height) ||
          row.width < 1 ||
          row.height < 1 ||
          row.width * row.height > 40000000)
      )
        throw new Error("照片索引无效");
      if (table === "jobs") {
        const req = validate("JobRequest", JSON.parse(row.request));
        if (
          req.date !== row.date ||
          req.kind !== row.kind ||
          !["queued", "running", "done", "failed", "interrupted"].includes(
            row.status,
          )
        )
          throw new Error("任务状态或请求无效");
        if (["queued", "running"].includes(row.status)) {
          row.status = "interrupted";
          row.error = "应用已重启或恢复，需手动重试";
        }
      }
      if (table === "days" && ![0, 1].includes(row.completed))
        throw new Error("当日完成标记无效");
      row.user_id = owner;
    }
  }
  if (ownerIds.size > 1) throw new Error("备份包含多个账号");
  const health = new Health(tables, owner);
  for (const entry of tables.entries) {
    const value = unpack(entry);
    if (value.image_id) health.find("images", value.image_id);
    if (
      entry.source_job_id !== (value.source_job_id ?? null) ||
      entry.plan_id !== (value.plan_id ?? null)
    )
      throw new Error("记录关联字段不一致");
    if (value.plan_id && health.find("entries", value.plan_id).kind !== "plan")
      throw new Error("排期关联无效");
    if (value.source_job_id && health.job(value.source_job_id).kind !== "meal")
      throw new Error("识餐关联无效");
    if (
      value.ai_estimate_job_id &&
      health.job(value.ai_estimate_job_id).kind !== "cardio_estimate"
    )
      throw new Error("有氧关联无效");
  }
  return tables;
}
