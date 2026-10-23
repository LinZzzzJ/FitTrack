export type Page =
  "dashboard" | "body" | "meals" | "training" | "trends" | "settings";
export interface User {
  id: string;
  username: string;
  is_admin: boolean;
}
export type ActivityLevel =
  | "sedentary"
  | "light"
  | "moderate"
  | "high"
  | "very_active";
export interface Profile {
  effective_date: string;
  height_cm: number;
  initial_weight_kg: number;
  body_fat_pct: number | null;
  sex: "male" | "female" | "other";
  age: number | null;
  resting_kcal: number | null;
  estimated_resting_kcal: number | null;
  estimated_maintenance_kcal: number | null;
  activity_factor: number;
  activity_level: ActivityLevel | null;
  target_weight_kg: number | null;
  calorie_target: number | null;
  protein_target_g: number | null;
  carbs_target_g: number | null;
  fat_target_g: number | null;
}
export interface BodyRecord {
  date: string;
  weight_kg: number | null;
  body_fat_pct: number | null;
  resting_kcal: number | null;
  note: string;
}
export interface Food {
  name: string;
  consumed_part: string;
  estimated_edible_grams: number;
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g?: number | null;
  sugar_g?: number | null;
  sodium_mg?: number | null;
}
export interface Nutrients {
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number | null;
  sugar_g: number | null;
  sodium_mg: number | null;
  macro_percent: { protein: number; carbs: number; fat: number };
  food_percent: number[];
}
export interface Meal {
  id?: string;
  date: string;
  slot: "breakfast" | "lunch" | "dinner" | "snack";
  title: string;
  note: string;
  assumptions?: string[];
  items: Food[];
  image_id: string | null;
  source_job_id: string | null;
  totals?: Nutrients;
  nutrition_label?: NutritionLabel | null;
}
export interface LabelReadout {
  name: string | null;
  basis_kind: "per_100g" | "per_serving" | "per_pack" | null;
  basis_grams: number | null;
  energy_value: number | null;
  energy_unit: "kJ" | "kcal" | null;
  protein_g: number | null;
  carbs_g: number | null;
  fat_g: number | null;
  fiber_g: number | null;
  sugar_g: number | null;
  sodium_mg: number | null;
  assumptions: string[];
}
export interface NutritionLabel {
  label: LabelReadout;
  portion: {
    mode: "grams" | "packs";
    grams: number | null;
    pack_grams: number | null;
    packs: number | null;
  };
}
export interface DietHistory {
  start: string;
  end: string;
  days: { date: string; meals: Meal[]; jobs: Job[]; totals: Nutrients }[];
}
export interface TrainingSet {
  reps: number;
  weight_kg: number;
}
export interface Exercise {
  name: string;
  sets: TrainingSet[];
}
export interface Workout {
  id?: string;
  date: string;
  title: string;
  kind: "strength" | "cardio";
  activity: string;
  duration_minutes: number;
  intensity: "light" | "moderate" | "vigorous";
  met: number | null;
  net_kcal_override: number | null;
  exercises: Exercise[];
  note: string;
  plan_id: string | null;
  ai_estimate_job_id?: string | null;
  energy?: {
    met: number;
    net_kcal: number;
    gross_kcal: number;
    volume_kg: number;
    set_count: number;
    rep_count: number;
    source: string;
    ai_stale?: boolean;
  };
}
export interface Plan {
  id?: string;
  date: string;
  title: string;
  kind: "strength" | "cardio";
  activity: string;
  duration_minutes: number;
  intensity: "light" | "moderate" | "vigorous";
  status: "planned" | "completed" | "skipped";
  note: string;
  exercises: Exercise[];
  workout_id?: string | null;
}
export interface WorkoutTemplate {
  id?: string;
  title: string;
  category: "back" | "chest" | "arms" | "shoulders" | "legs" | "core" | "full_body" | "custom";
  icon: string;
  kind: "strength";
  duration_minutes: number;
  intensity: Workout["intensity"];
  exercises: Exercise[];
  note: string;
}
export interface Feedback {
  summary: string;
  positives: string[];
  adjustments: string[];
  next_day_advice: string;
}
export interface JobRequest {
  kind: "meal" | "feedback" | "goals" | "cardio_estimate" | "weekly_review";
  date: string;
  image_id?: string | null;
  note?: string;
  slot?: Meal["slot"];
  request_key: string;
  goal_profile?: Profile;
  cardio_input?: CardioInput;
  week_start?: string;
  meal_mode?: "photo" | "label";
  meal_description?: string | null;
}
export interface CardioInput {
  kind: "cardio";
  activity: string;
  duration_minutes: number;
  intensity: Workout["intensity"];
  description: string;
}
export interface CardioEstimate {
  effective_met: number;
  rationale: string;
  assumptions: string[];
  gross_kcal: number;
  net_kcal: number;
  weight_kg: number;
  resting_kcal: number;
}
export interface WeeklyAdvice {
  summary: string;
  diet_findings: string[];
  training_findings: string[];
  next_week_plan: string[];
  limitations: string[];
}
export interface WeeklyStatistics {
  intake_total_kcal: number;
  average_intake_kcal: number;
  average_protein_g: number;
  average_carbs_g: number;
  average_fat_g: number;
  expenditure_total_kcal: number | null;
  deficit_total_kcal: number | null;
  training_sessions: number;
  training_days: number;
  rest_days: number;
  duration_minutes: number;
  volume_kg: number;
  weight_change_kg: number | null;
  body_fat_change_pct: number | null;
  weight_measurements: number;
  body_fat_measurements: number;
}
export interface WeeklyStatus {
  week_start: string;
  week_end: string;
  week_number: number;
  earliest_generation_date: string;
  today: string;
  closed: boolean;
  completed_days: number;
  missing_dates: { date: string; reasons: string[] }[];
  can_generate: boolean;
  reason: string;
  available_weeks: string[];
  statistics: WeeklyStatistics;
  report: Job | null;
  active_job: Job | null;
  latest_job: Job | null;
}
export interface GoalSuggestion {
  calorie_target: number;
  protein_target_g: number;
  carbs_target_g: number;
  fat_target_g: number;
  rationale: string;
  assumptions: string[];
}
export interface Job {
  id: string;
  kind: JobRequest["kind"];
  date: string;
  status: "queued" | "running" | "done" | "failed" | "interrupted";
  request: JobRequest;
  result: {
    label?: LabelReadout;
    items?: Food[];
    assumptions?: string[];
    summary?: string;
    total_kcal?: number;
    goals?: GoalSuggestion;
    estimate?: CardioEstimate;
    review?: WeeklyAdvice;
    statistics?: WeeklyStatistics;
    basis?: {
      current_weight_kg: number;
      resting_kcal: number;
      estimated_maintenance_kcal: number;
      average_exercise_net_kcal_7d: number;
      recorded_training_days_7d: number;
    };
    stale?: boolean;
  } | null;
  error: string | null;
  created_at: number;
}
export interface Day {
  date: string;
  profile: Profile | null;
  body: BodyRecord | null;
  effective_weight_kg: number | null;
  resting_kcal: number | null;
  meals: Meal[];
  workouts: Workout[];
  totals: Nutrients;
  exercise_kcal: number;
  baseline_kcal: number | null;
  expenditure_kcal: number | null;
  deficit_kcal: number | null;
  duration_minutes: number;
  volume_kg: number;
  completed: boolean;
  feedback: { data: Feedback; stale: boolean; created_at: number } | null;
  jobs: Job[];
  plans: Plan[];
}
export interface TrendDay {
  date: string;
  body: BodyRecord | null;
  totals: Nutrients;
  expenditure_kcal: number | null;
  deficit_kcal: number | null;
  exercise_kcal: number;
  duration_minutes: number;
  volume_kg: number;
  weight_average_7d: number | null;
  completed: boolean;
  meal_count: number;
}
export interface AIConfig {
  api_key_set: boolean;
  base_url: string;
  vision_model: string;
  coach_model: string;
  environment_override: boolean;
  remember?: boolean;
  credential_scope?: "account" | "session" | "none";
  credential_error?: string;
}
export interface RuntimeCapabilities {
  mode: "local" | "server";
  choose_directory: boolean;
  open_directory: boolean;
  migrate_workspace: boolean;
  migrate_root: boolean;
  stop_service: boolean;
  allowed_providers: string[];
}
export interface StorageOperation {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "failed" | "interrupted";
  progress: number;
  error: string | null;
  result: {
    workspace?: string;
    retained?: string;
    backup_id?: string;
    name?: string;
  } | null;
}
export interface StorageInfo {
  root: string;
  workspace: string;
  workspace_relative: string;
  workspace_bytes: number;
  account_db: string;
  key_file: string;
  areas: { name: string; label: string; path: string; bytes: number }[];
  archives: string[];
  legacy_paths: string[];
  operations: StorageOperation[];
}
export interface BackupInfo {
  id: string;
  name: string;
  size: number;
  created_at: number;
}
export interface Activity {
  id: string;
  name: string;
  kind: "strength" | "cardio";
  mets: Record<string, number>;
  source: string;
}
export interface Me {
  user: User;
  today: string;
  profile: Profile | null;
  ai: AIConfig;
  activities: Activity[];
  activity_levels: Record<ActivityLevel, { label: string; factor: number }>;
  runtime?: RuntimeCapabilities | null;
}
