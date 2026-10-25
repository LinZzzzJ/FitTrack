"""Export deterministic Python contracts for the Android service layer (offline)."""

import ast
import inspect
import json
from pathlib import Path

from fittrack import ai, models
from fittrack.calculations import ACTIVITIES, ACTIVITY_LEVELS
from fittrack.exercise_catalog import exercise_catalog


def export():
    names = [
        "Profile",
        "BodyRecord",
        "Meal",
        "Workout",
        "TrainingPlan",
        "WorkoutTemplate",
        "NutritionLabel",
        "JobRequest",
        "AISettings",
        "FoodItem",
        "LabelReadout",
    ]
    schemas = {name: getattr(models, name).model_json_schema() for name in names}
    for name in [
        "MealEstimate",
        "CoachFeedback",
        "CardioEstimate",
        "WeeklyReview",
        "GoalSuggestion",
    ]:
        schemas[name] = getattr(ai, name).model_json_schema()
    prompts = {}
    tree = ast.parse(inspect.getsource(ai.AIClient))
    for method in tree.body[0].body:
        if not isinstance(method, ast.FunctionDef):
            continue
        for node in ast.walk(method):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "prompt" for t in node.targets
            ):
                try:
                    prompts[method.name] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    pass
    return {
        "version": 1,
        "schemas": schemas,
        "activities": ACTIVITIES,
        "activity_levels": ACTIVITY_LEVELS,
        "exercises": exercise_catalog(),
        "prompts": prompts,
    }


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "web/src/lib/mobile-contracts.json"
    target.write_text(json.dumps(export(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
