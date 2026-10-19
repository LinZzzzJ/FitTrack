"""Deterministic ledger calculations; amounts are estimates, not measured TDEE."""

from datetime import date, datetime, timedelta, timezone

SHANGHAI = timezone(timedelta(hours=8))
TRACKING_START = "2026-10-15"
SOURCE = "https://pacompendium.com/conditioning-exercise/"
ACTIVITIES = [
    {
        "id": "badminton",
        "name": "羽毛球",
        "kind": "cardio",
        "mets": {"light": 5.5, "moderate": 7.0, "vigorous": 9.0},
        "source": "https://pacompendium.com/sports/",
    },
    {
        "id": "strength",
        "name": "力量训练",
        "kind": "strength",
        "mets": {"light": 3.5, "moderate": 3.5, "vigorous": 6.0},
        "source": SOURCE,
    },
    {
        "id": "bodyweight",
        "name": "自重训练",
        "kind": "strength",
        "mets": {"light": 3.0, "moderate": 3.0, "vigorous": 6.5},
        "source": SOURCE,
    },
    {
        "id": "circuit",
        "name": "循环训练",
        "kind": "strength",
        "mets": {"light": 3.5, "moderate": 5.0, "vigorous": 7.5},
        "source": SOURCE,
    },
    {
        "id": "elliptical",
        "name": "椭圆机",
        "kind": "cardio",
        "mets": {"light": 5.0, "moderate": 5.0, "vigorous": 9.0},
        "source": SOURCE,
    },
    {
        "id": "rowing",
        "name": "划船机",
        "kind": "cardio",
        "mets": {"light": 5.0, "moderate": 5.0, "vigorous": 7.5},
        "source": SOURCE,
    },
    {
        "id": "yoga",
        "name": "瑜伽 / 拉伸",
        "kind": "cardio",
        "mets": {"light": 2.3, "moderate": 2.3, "vigorous": 4.0},
        "source": SOURCE,
    },
    {
        "id": "running",
        "name": "跑步",
        "kind": "cardio",
        "mets": {"light": 6.5, "moderate": 8.5, "vigorous": 11.0},
        "source": "https://pacompendium.com/running/",
    },
    {
        "id": "walking",
        "name": "步行",
        "kind": "cardio",
        "mets": {"light": 2.8, "moderate": 3.8, "vigorous": 4.8},
        "source": "https://pacompendium.com/walking/",
    },
    {
        "id": "cycling",
        "name": "骑行",
        "kind": "cardio",
        "mets": {"light": 4.3, "moderate": 7.0, "vigorous": 9.0},
        "source": "https://pacompendium.com/bicycling/",
    },
]


def today() -> str:
    return datetime.now(SHANGHAI).date().isoformat()


def dates_between(start: str, end: str) -> list[str]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    length = (last - first).days
    if length < 0 or length > 365:
        raise ValueError("日期范围应为 0 至 365 天")
    return [(first + timedelta(days=i)).isoformat() for i in range(length + 1)]


def nutrients(items: list[dict]) -> dict:
    result = {
        key: round(sum(item[key] for item in items), 2)
        for key in ("kcal", "protein_g", "carbs_g", "fat_g")
    }
    energy = {
        "protein": result["protein_g"] * 4,
        "carbs": result["carbs_g"] * 4,
        "fat": result["fat_g"] * 9,
    }
    total = sum(energy.values())
    result["macro_percent"] = {
        key: round(value / total * 100, 2) if total else 0 for key, value in energy.items()
    }
    result["food_percent"] = [
        round(item["kcal"] / result["kcal"] * 100, 2) if result["kcal"] else 0 for item in items
    ]
    return result


def workout_energy(workout: dict, weight: float, resting: float) -> dict:
    activity = next((entry for entry in ACTIVITIES if entry["id"] == workout["activity"]), None)
    if activity is None and workout.get("met") is None:
        raise ValueError("未知运动类型，请填写 MET")
    met = workout.get("met") or activity["mets"][workout["intensity"]]
    minutes = workout["duration_minutes"]
    gross = met * weight * minutes / 60
    net = max(0, gross - resting * minutes / 1440)
    if workout.get("net_kcal_override") is not None:
        net = workout["net_kcal_override"]
    sets = [group for exercise in workout.get("exercises", []) for group in exercise["sets"]]
    return {
        "met": met,
        "gross_kcal": round(gross, 2),
        "net_kcal": round(net, 2),
        "volume_kg": round(sum(group["weight_kg"] * group["reps"] for group in sets), 2),
        "set_count": len(sets),
        "rep_count": sum(group["reps"] for group in sets),
        "source": activity["source"] if activity else "手动 MET",
    }
