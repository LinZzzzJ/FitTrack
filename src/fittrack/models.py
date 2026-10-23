from datetime import date
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Credentials(Model):
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=8, max_length=128)


class Profile(Model):
    effective_date: date
    height_cm: float = Field(ge=90, le=240)
    initial_weight_kg: float = Field(ge=20, le=350)
    body_fat_pct: float | None = Field(None, gt=0, le=70)
    sex: Literal["male", "female", "other"] = "male"
    age: int | None = Field(None, ge=13, le=110)
    resting_kcal: float | None = Field(None, ge=500, le=5000)
    activity_factor: float = Field(1.2, ge=1, le=2.5)
    activity_level: Literal["sedentary", "light", "moderate", "high", "very_active"] | None = None
    target_weight_kg: float | None = Field(None, ge=20, le=350)
    calorie_target: float | None = Field(None, gt=0, le=10000)
    protein_target_g: float | None = Field(None, gt=0, le=1000)
    carbs_target_g: float | None = Field(None, gt=0, le=2000)
    fat_target_g: float | None = Field(None, gt=0, le=1000)

    @model_validator(mode="after")
    def resting_source(self):
        if self.resting_kcal is None and self.age is None:
            raise ValueError("静息能量留空时需要填写年龄以生成估算")
        return self


class BodyRecord(Model):
    date: date
    weight_kg: float | None = Field(None, ge=20, le=350)
    body_fat_pct: float | None = Field(None, gt=0, le=70)
    resting_kcal: float | None = Field(None, ge=500, le=5000)
    note: str = Field("", max_length=1000)


class FoodItem(Model):
    name: str = Field(min_length=1, max_length=100)
    consumed_part: str = Field("", max_length=300)
    estimated_edible_grams: float | None = Field(None, ge=0, le=10000)
    kcal: float = Field(ge=0, le=20000)
    protein_g: float = Field(ge=0, le=2000)
    carbs_g: float = Field(ge=0, le=5000)
    fat_g: float = Field(ge=0, le=2000)
    fiber_g: float | None = Field(None, ge=0, le=2000)
    sugar_g: float | None = Field(None, ge=0, le=2000)
    sodium_mg: float | None = Field(None, ge=0, le=100000)


class LabelReadout(Model):
    name: str | None = Field(None, max_length=100)
    basis_kind: Literal["per_100g", "per_serving", "per_pack"] | None = None
    basis_grams: float | None = Field(None, gt=0, le=10000)
    energy_value: float | None = Field(None, ge=0, le=100000)
    energy_unit: Literal["kJ", "kcal"] | None = None
    protein_g: float | None = Field(None, ge=0, le=2000)
    carbs_g: float | None = Field(None, ge=0, le=5000)
    fat_g: float | None = Field(None, ge=0, le=2000)
    fiber_g: float | None = Field(None, ge=0, le=2000)
    sugar_g: float | None = Field(None, ge=0, le=2000)
    sodium_mg: float | None = Field(None, ge=0, le=100000)
    assumptions: list[str] = Field(default_factory=list, max_length=20)


class LabelPortion(Model):
    mode: Literal["grams", "packs"] = "grams"
    grams: float | None = Field(None, gt=0, le=10000)
    pack_grams: float | None = Field(None, gt=0, le=10000)
    packs: float | None = Field(None, gt=0, le=1000)


class NutritionLabel(Model):
    label: LabelReadout
    portion: LabelPortion


class Meal(Model):
    date: date
    slot: Literal["breakfast", "lunch", "dinner", "snack"] = "lunch"
    title: str = Field("", max_length=100)
    note: str = Field("", max_length=2000)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    items: list[FoodItem] = Field(min_length=1, max_length=50)
    meal_description: str | None = Field(None, max_length=4000)
    nutrition_mode: Literal["estimate", "precise"] | None = None
    image_id: str | None = None
    source_job_id: str | None = None
    nutrition_label: NutritionLabel | None = None

    @model_validator(mode="before")
    @classmethod
    def calculate_precise_meal_energy(cls, value):
        if not isinstance(value, dict) or value.get("nutrition_mode") != "precise":
            return value
        if value.get("nutrition_label") is not None:
            raise ValueError("营养标签记录不能使用整餐精确录入模式")
        description = value.get("meal_description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("精确录入需要填写餐食描述")
        items = value.get("items")
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            raise ValueError("精确录入必须提供一组整餐营养总量")
        item = items[0].copy()
        amounts = []
        limits = {"protein_g": 2000, "carbs_g": 5000, "fat_g": 2000}
        for key, maximum in limits.items():
            try:
                amount = float(item[key])
            except (KeyError, TypeError, ValueError):
                raise ValueError("精确录入需要填写蛋白质、碳水和脂肪") from None
            if not math.isfinite(amount) or amount < 0 or amount > maximum:
                raise ValueError("三大营养素必须是允许范围内的有限非负数")
            amounts.append(amount)
        item["kcal"] = round(amounts[0] * 4 + amounts[1] * 4 + amounts[2] * 9, 2)
        if item["kcal"] > 20000:
            raise ValueError("按三大营养素计算的热量超出允许范围")
        item.setdefault("estimated_edible_grams", None)
        value = value.copy()
        value["items"] = [item]
        value["source_job_id"] = None
        value["assumptions"] = []
        return value

    @model_validator(mode="after")
    def estimated_items_require_weight(self):
        if self.nutrition_mode == "precise":
            return self
        if any(item.estimated_edible_grams is None for item in self.items):
            raise ValueError("AI 估算明细必须包含食用重量；精确录入请切换到整餐模式")
        return self


class TrainingSet(Model):
    reps: int = Field(ge=1, le=1000)
    weight_kg: float = Field(0, ge=0, le=1000)


class Exercise(Model):
    name: str = Field(min_length=1, max_length=100)
    sets: list[TrainingSet] = Field(min_length=1, max_length=50)


class Workout(Model):
    date: date
    title: str = Field(min_length=1, max_length=100)
    kind: Literal["strength", "cardio"] = "strength"
    activity: str = Field("strength", max_length=100)
    duration_minutes: float = Field(gt=0, le=1440)
    intensity: Literal["light", "moderate", "vigorous"] = "moderate"
    met: float | None = Field(None, ge=1, le=25)
    net_kcal_override: float | None = Field(None, ge=0, le=10000)
    exercises: list[Exercise] = Field(default_factory=list, max_length=30)
    note: str = Field("", max_length=2000)
    plan_id: str | None = None
    ai_estimate_job_id: str | None = None


class TrainingPlan(Model):
    date: date
    title: str = Field(min_length=1, max_length=100)
    kind: Literal["strength", "cardio"] = "strength"
    activity: str = Field("strength", max_length=100)
    duration_minutes: float = Field(45, gt=0, le=1440)
    intensity: Literal["light", "moderate", "vigorous"] = "moderate"
    status: Literal["planned", "skipped"] = "planned"
    note: str = Field("", max_length=2000)
    exercises: list[Exercise] = Field(default_factory=list, max_length=30)


class WorkoutTemplate(Model):
    title: str = Field(min_length=1, max_length=100)
    category: Literal["back", "chest", "arms", "shoulders", "legs", "core", "full_body", "custom"]
    icon: str = Field("dumbbell", min_length=1, max_length=40)
    kind: Literal["strength"] = "strength"
    duration_minutes: float = Field(45, gt=0, le=1440)
    intensity: Literal["light", "moderate", "vigorous"] = "moderate"
    exercises: list[Exercise] = Field(min_length=1, max_length=30)
    note: str = Field("", max_length=2000)


class GoalProfile(Profile):
    target_weight_kg: float = Field(ge=20, le=350)


class CardioInput(Model):
    kind: Literal["cardio"] = "cardio"
    activity: str = Field(min_length=1, max_length=100)
    duration_minutes: float = Field(gt=0, le=1440)
    intensity: Literal["light", "moderate", "vigorous"] = "moderate"
    description: str = Field("", max_length=2000)


class JobRequest(Model):
    kind: Literal["meal", "feedback", "goals", "cardio_estimate", "weekly_review"]
    date: date
    image_id: str | None = None
    note: str = Field("", max_length=2000)
    slot: Literal["breakfast", "lunch", "dinner", "snack"] = "lunch"
    request_key: str = Field(min_length=8, max_length=100)
    goal_profile: GoalProfile | None = None
    cardio_input: CardioInput | None = None
    week_start: date | None = None
    meal_mode: Literal["photo", "label"] = "photo"
    meal_description: str | None = Field(None, min_length=3, max_length=4000)

    @model_validator(mode="after")
    def validate_goal_input(self):
        if self.kind == "goals" and self.goal_profile is None:
            raise ValueError("生成目标需要身体资料和目标体重")
        if self.kind != "goals" and self.goal_profile is not None:
            raise ValueError("此任务不能包含目标生成资料")
        if (self.kind == "cardio_estimate") != (self.cardio_input is not None):
            raise ValueError("有氧估算任务必须且仅能包含有氧资料")
        if (self.kind == "weekly_review") != (self.week_start is not None):
            raise ValueError("每周复盘任务必须且仅能包含周起始日期")
        if self.kind != "meal" and self.meal_mode != "photo":
            raise ValueError("标签模式仅用于餐食任务")
        if self.kind == "meal" and self.meal_mode == "label" and self.meal_description:
            raise ValueError("标签识别不能同时包含餐食描述")
        if self.kind != "meal" and self.meal_description is not None:
            raise ValueError("餐食描述仅用于餐食任务")
        if self.kind == "meal" and self.meal_mode == "photo" and not (
            self.image_id or self.meal_description
        ):
            raise ValueError("请提供餐食照片或文字描述")
        return self


class AISettings(Model):
    api_key: str | None = Field(None, max_length=500)
    base_url: str | None = Field(None, max_length=500)
    vision_model: str | None = Field(None, min_length=1, max_length=100)
    coach_model: str | None = Field(None, min_length=1, max_length=100)
    remember: bool | None = None
