"""Owned, deterministic coaching contexts and weekly eligibility; no AI calls here."""

from datetime import date, timedelta
import hashlib

from fittrack import calculations as calc
from fittrack.models import CardioInput


def fingerprint(context):
    from fittrack.store import encode

    return hashlib.sha256(encode(context).encode()).hexdigest()


def cardio_input(workout):
    return CardioInput.model_validate(
        {
            "kind": workout["kind"],
            "activity": workout["activity"],
            "duration_minutes": workout["duration_minutes"],
            "intensity": workout["intensity"],
            "description": workout.get("note", ""),
        }
    ).model_dump(mode="json")


def cardio_context(store, uid, day, values):
    data = CardioInput.model_validate(values).model_dump(mode="json")
    activity = next(
        (a for a in calc.ACTIVITIES if a["id"] == data["activity"] and a["kind"] == "cardio"), None
    )
    if activity is None:
        raise ValueError("AI 估算仅支持已列出的有氧类型，不支持力量训练")
    profile = store.profile(uid, day)
    if profile is None:
        raise ValueError("请先填写身体资料、初始体重和静息能量")
    body = store.body(uid, day)
    return {
        "date": day,
        "input": data,
        "activity_name": activity["name"],
        "reference_met": activity["mets"][data["intensity"]],
        "reference_source": activity["source"],
        "weight_kg": store.effective_weight(uid, day, profile["initial_weight_kg"]),
        "resting_kcal": (body or {}).get("resting_kcal") or profile["resting_kcal"],
    }


def week_bounds(start=None):
    anchor = date.fromisoformat(calc.TRACKING_START)
    now = date.fromisoformat(calc.today())
    current_index = max(0, (now - anchor).days // 7)
    first = (
        date.fromisoformat(start)
        if start
        else anchor + timedelta(days=max(0, current_index - 1) * 7)
    )
    if first < anchor or (first - anchor).days % 7:
        raise ValueError("周起始日期必须从 2026-10-15 起每隔 7 天")
    return first, first + timedelta(days=6), now, current_index


def weekly_context(store, uid, start):
    first, last, _, _ = week_bounds(start)
    days = []
    for day in calc.dates_between(first.isoformat(), last.isoformat()):
        summary = store.summary(uid, day)
        days.append(
            {
                key: summary[key]
                for key in (
                    "date",
                    "profile",
                    "body",
                    "totals",
                    "meals",
                    "workouts",
                    "completed",
                    "exercise_kcal",
                    "expenditure_kcal",
                    "deficit_kcal",
                    "duration_minutes",
                    "volume_kg",
                )
            }
        )

    def complete_sum(key):
        values = [row[key] for row in days]
        return round(sum(values), 2) if all(v is not None for v in values) else None

    weights = [
        d["body"]["weight_kg"] for d in days if d["body"] and d["body"].get("weight_kg") is not None
    ]
    fats = [
        d["body"]["body_fat_pct"]
        for d in days
        if d["body"] and d["body"].get("body_fat_pct") is not None
    ]
    totals = {
        key: round(sum(d["totals"][key] for d in days), 2)
        for key in ("kcal", "protein_g", "carbs_g", "fat_g")
    }
    statistics = {
        "intake_total_kcal": totals["kcal"],
        "average_intake_kcal": round(totals["kcal"] / 7, 2),
        "average_protein_g": round(totals["protein_g"] / 7, 2),
        "average_carbs_g": round(totals["carbs_g"] / 7, 2),
        "average_fat_g": round(totals["fat_g"] / 7, 2),
        "expenditure_total_kcal": complete_sum("expenditure_kcal"),
        "deficit_total_kcal": complete_sum("deficit_kcal"),
        "training_sessions": sum(len(d["workouts"]) for d in days),
        "training_days": sum(bool(d["workouts"]) for d in days),
        "rest_days": sum(not d["workouts"] for d in days),
        "duration_minutes": complete_sum("duration_minutes"),
        "volume_kg": complete_sum("volume_kg"),
        "weight_change_kg": round(weights[-1] - weights[0], 2) if len(weights) >= 2 else None,
        "body_fat_change_pct": round(fats[-1] - fats[0], 2) if len(fats) >= 2 else None,
        "weight_measurements": len(weights),
        "body_fat_measurements": len(fats),
    }
    return {
        "week_start": first.isoformat(),
        "week_end": last.isoformat(),
        "days": days,
        "statistics": statistics,
    }


def weekly_status(store, uid, start=None):
    first, last, now, current = week_bounds(start)
    context = weekly_context(store, uid, first.isoformat())
    missing = [
        {
            "date": row["date"],
            "reasons": (["缺少已确认饮食"] if not row["meals"] else [])
            + (["尚未完成当日记录"] if not row["completed"] else []),
        }
        for row in context["days"]
        if not row["meals"] or not row["completed"]
    ]
    closed = last < now
    rows = store.rows(
        "SELECT * FROM jobs WHERE user_id=? AND kind='weekly_review' AND date=? ORDER BY created_at DESC,id DESC",
        (uid, last.isoformat()),
    )
    report = next((store.job(uid, row["id"]) for row in rows if row["status"] == "done"), None)
    active = next(
        (store.job(uid, row["id"]) for row in rows if row["status"] in {"queued", "running"}), None
    )
    latest = store.job(uid, rows[0]["id"]) if rows else None
    return {
        "week_start": first.isoformat(),
        "week_end": last.isoformat(),
        "week_number": (first - date.fromisoformat(calc.TRACKING_START)).days // 7 + 1,
        "earliest_generation_date": (last + timedelta(days=1)).isoformat(),
        "today": now.isoformat(),
        "closed": closed,
        "completed_days": 7 - len(missing),
        "missing_dates": missing,
        "can_generate": closed and not missing and active is None,
        "reason": "本周尚未结束，需完整一周后才能生成"
        if not closed
        else "请补齐并完成缺失日期的饮食记录"
        if missing
        else "本周复盘正在生成"
        if active
        else "已具备完整一周记录",
        "available_weeks": [
            (date.fromisoformat(calc.TRACKING_START) + timedelta(days=i * 7)).isoformat()
            for i in range(current, -1, -1)
        ],
        "statistics": context["statistics"],
        "report": report,
        "active_job": active,
        "latest_job": latest,
    }


def validate_cardio_source(store, uid, workout):
    ident = workout.get("ai_estimate_job_id")
    if not ident:
        return
    job = store.job(uid, ident)
    if workout["kind"] != "cardio" or job["kind"] != "cardio_estimate" or job["status"] != "done":
        raise ValueError("AI 估算来源与有氧训练不匹配")
    context = cardio_context(store, uid, workout["date"], cardio_input(workout))
    if job["source_hash"] != fingerprint(context) or job["result"].get("stale"):
        raise ValueError("AI 有氧估算已过期，请重新估算或改用手动 MET")
    estimate = job["result"]["estimate"]
    if (
        workout.get("met") != estimate["effective_met"]
        or workout.get("net_kcal_override") is not None
    ):
        raise ValueError("采用 AI 估算时需使用推荐 MET 并清空净消耗覆盖；手动调整请解除 AI 来源")
