"""SQLite journal + immutable image files. All access is scoped by user_id."""

import hashlib
import io
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from fittrack.calculations import (
    activity_factor,
    dates_between,
    nutrients,
    resting_estimate,
    workout_energy,
)
from fittrack.config import atomic_bytes

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS profiles(user_id TEXT NOT NULL REFERENCES users(id), date TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(user_id,date));
CREATE TABLE IF NOT EXISTS bodies(user_id TEXT NOT NULL REFERENCES users(id), date TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(user_id,date));
CREATE TABLE IF NOT EXISTS images(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), sha TEXT NOT NULL, ext TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS entries(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL, date TEXT NOT NULL, data TEXT NOT NULL, source_job_id TEXT, plan_id TEXT, created_at REAL NOT NULL, UNIQUE(user_id,source_job_id), UNIQUE(user_id,plan_id));
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL, date TEXT NOT NULL, request_key TEXT NOT NULL, request TEXT NOT NULL, status TEXT NOT NULL, result TEXT, error TEXT, source_hash TEXT, created_at REAL NOT NULL, finished_at REAL, UNIQUE(user_id,request_key));
CREATE TABLE IF NOT EXISTS feedback(user_id TEXT NOT NULL REFERENCES users(id), date TEXT NOT NULL, data TEXT NOT NULL, source_hash TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(user_id,date));
CREATE TABLE IF NOT EXISTS days(user_id TEXT NOT NULL REFERENCES users(id), date TEXT NOT NULL, completed INTEGER NOT NULL, PRIMARY KEY(user_id,date));
CREATE TABLE IF NOT EXISTS workout_templates(user_id TEXT NOT NULL REFERENCES users(id), id TEXT NOT NULL, data TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(user_id,id));
CREATE INDEX IF NOT EXISTS entry_lookup ON entries(user_id,kind,date);
CREATE INDEX IF NOT EXISTS jobs_lookup ON jobs(user_id,date,created_at);
CREATE INDEX IF NOT EXISTS image_lookup ON images(user_id,sha);
"""


def identifier() -> str:
    return secrets.token_hex(12)


def encode(data) -> str:
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


class ActiveJobError(ValueError):
    pass


class Store:
    def __init__(self, home: Path, owner_id: str | None = None):
        self.home = home
        self.images = home / "images"
        self.thumbs = home / "thumbs"
        for directory in (home, self.images, self.thumbs):
            directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(
            home / "fittrack.sqlite3", check_same_thread=False, isolation_level=None, timeout=10
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=10000")
        if self.db.execute("PRAGMA user_version").fetchone()[0] > 1:
            raise RuntimeError("数据库版本较新，请升级 FitTrack")
        schema = SCHEMA
        if owner_id:
            schema = "\n".join(
                line
                for line in SCHEMA.splitlines()
                if not line.startswith(
                    ("CREATE TABLE IF NOT EXISTS users(", "CREATE TABLE IF NOT EXISTS sessions(")
                )
            )
            schema = "CREATE TABLE IF NOT EXISTS owners(id TEXT PRIMARY KEY);\n" + schema.replace(
                "REFERENCES users(id)", "REFERENCES owners(id)"
            )
        self.db.executescript(schema)
        if owner_id:
            prior = self.rows("SELECT id FROM owners")
            if prior and prior[0]["id"] != owner_id:
                self.db.close()
                raise ValueError("此工作区属于其他账号")
            self.db.execute("INSERT OR IGNORE INTO owners VALUES(?)", (owner_id,))
        self.db.execute("PRAGMA temp_store=MEMORY")
        self.db.execute("PRAGMA user_version=1")

    def close(self):
        with self.lock:
            self.db.close()

    def rows(self, sql, args=()) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.db.execute(sql, args)]

    def one(self, sql, args=()) -> dict:
        rows = self.rows(sql, args)
        if not rows:
            raise KeyError("记录不存在")
        return rows[0]

    def register(self, username, password_hash) -> dict:
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                uid = identifier()
                admin = self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
                self.db.execute(
                    "INSERT INTO users VALUES(?,?,?,?,?)",
                    (uid, username, password_hash, int(admin), time.time()),
                )
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
        return self.user(uid)

    def user(self, uid):
        result = self.one("SELECT id,username,is_admin FROM users WHERE id=?", (uid,))
        result["is_admin"] = bool(result["is_admin"])
        return result

    def session(self, uid) -> str:
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.db.execute(
                "INSERT INTO sessions VALUES(?,?,?)",
                (hashlib.sha256(token.encode()).hexdigest(), uid, time.time() + 14 * 86400),
            )
        return token

    def session_user(self, token):
        row = self.one(
            "SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?",
            (hashlib.sha256(token.encode()).hexdigest(), time.time()),
        )
        return self.user(row["user_id"])

    def logout(self, token):
        with self.lock:
            self.db.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )

    def save_profile(self, uid, data):
        with self.lock:
            self.db.execute(
                "INSERT INTO profiles VALUES(?,?,?) ON CONFLICT(user_id,date) DO UPDATE SET data=excluded.data",
                (uid, data["effective_date"], encode(data)),
            )
        return self.profile(uid, data["effective_date"])

    def profile(self, uid, day):
        rows = self.rows(
            "SELECT data FROM profiles WHERE user_id=? AND date<=? ORDER BY date DESC LIMIT 1",
            (uid, day),
        )
        if not rows:
            rows = self.rows(
                "SELECT data FROM profiles WHERE user_id=? ORDER BY date LIMIT 1", (uid,)
            )
        if not rows:
            return None
        value = json.loads(rows[0]["data"])
        value.setdefault("age", None)
        value.setdefault("activity_level", None)
        value.setdefault("estimated_resting_kcal", None)
        value.setdefault("estimated_maintenance_kcal", None)
        weight = self.effective_weight(uid, day, value.get("initial_weight_kg"))
        estimate = resting_estimate(value, weight)
        value["estimated_resting_kcal"] = estimate
        if value.get("resting_kcal") is None:
            value["estimated_maintenance_kcal"] = (
                round(estimate * activity_factor(value), 1) if estimate is not None else None
            )
        else:
            value["estimated_maintenance_kcal"] = round(
                value["resting_kcal"] * activity_factor(value), 1
            )
        return value

    def templates(self, uid):
        return [
            json.loads(row["data"])
            | {"id": row["id"]}
            for row in self.rows(
                "SELECT id,data FROM workout_templates WHERE user_id=? ORDER BY created_at,id",
                (uid,),
            )
        ]

    def save_template(self, uid, data, ident=None):
        with self.lock:
            if ident is not None and not self.rows(
                "SELECT id FROM workout_templates WHERE user_id=? AND id=?", (uid, ident)
            ):
                raise KeyError("训练模板不存在")
            ident = ident or identifier()
            self.db.execute(
                "INSERT INTO workout_templates VALUES(?,?,?,?) "
                "ON CONFLICT(user_id,id) DO UPDATE SET data=excluded.data",
                (uid, ident, encode(data), time.time()),
            )
        return data | {"id": ident}

    def delete_template(self, uid, ident):
        with self.lock:
            cursor = self.db.execute(
                "DELETE FROM workout_templates WHERE user_id=? AND id=?", (uid, ident)
            )
            if not cursor.rowcount:
                raise KeyError("训练模板不存在")

    def save_body(self, uid, data):
        if all(data.get(key) is None for key in ("weight_kg", "body_fat_pct", "resting_kcal")):
            raise ValueError("请至少填写一项身体数据")
        with self.lock:
            self.db.execute(
                "INSERT INTO bodies VALUES(?,?,?) ON CONFLICT(user_id,date) DO UPDATE SET data=excluded.data",
                (uid, data["date"], encode(data)),
            )
        return data

    def body(self, uid, day):
        rows = self.rows("SELECT data FROM bodies WHERE user_id=? AND date=?", (uid, day))
        return json.loads(rows[0]["data"]) if rows else None

    def delete_body(self, uid, day):
        with self.lock:
            self.db.execute("DELETE FROM bodies WHERE user_id=? AND date=?", (uid, day))

    def effective_weight(self, uid, day, fallback):
        for row in self.rows(
            "SELECT data FROM bodies WHERE user_id=? AND date<=? ORDER BY date DESC", (uid, day)
        ):
            data = json.loads(row["data"])
            if data.get("weight_kg") is not None:
                return data["weight_kg"]
        return fallback

    def image(self, uid, image_id):
        return self.one("SELECT * FROM images WHERE id=? AND user_id=?", (image_id, uid))

    def put_image(self, uid, data):
        if len(data) > 12 * 1024 * 1024:
            raise ValueError("图片不能超过 12 MB")
        try:
            with Image.open(io.BytesIO(data)) as image:
                fmt = image.format
                if (
                    fmt not in {"JPEG", "PNG", "WEBP", "GIF"}
                    or image.width * image.height > 40_000_000
                ):
                    raise ValueError("请使用不超过 4000 万像素的 JPEG、PNG、WebP 或 GIF")
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError("无法读取这张图片") from exc
        sha = hashlib.sha256(data).hexdigest()
        ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}[fmt]
        atomic_bytes(self.images / f"{sha}.{ext}", data)
        with self.lock:
            existing = self.rows("SELECT * FROM images WHERE user_id=? AND sha=?", (uid, sha))
            if existing:
                return existing[0]
            iid = identifier()
            self.db.execute(
                "INSERT INTO images VALUES(?,?,?,?,?,?,?)",
                (iid, uid, sha, ext, width, height, time.time()),
            )
        return self.image(uid, iid)

    def image_path(self, uid, iid, thumbnail=False):
        image = self.image(uid, iid)
        path = self.images / f"{image['sha']}.{image['ext']}"
        if thumbnail:
            thumb = self.thumbs / f"{image['sha']}.jpg"
            if not thumb.exists():
                with Image.open(path) as original:
                    normalized = ImageOps.exif_transpose(original).convert("RGB")
                    normalized.thumbnail((480, 480))
                    output = io.BytesIO()
                    normalized.save(output, "JPEG", quality=85)
                    atomic_bytes(thumb, output.getvalue())
            return thumb
        return path

    @staticmethod
    def unpack(row):
        data = json.loads(row["data"])
        return data | {"id": row["id"], "created_at": row["created_at"]}

    def entry(self, uid, kind, eid):
        return self.unpack(
            self.one("SELECT * FROM entries WHERE id=? AND user_id=? AND kind=?", (eid, uid, kind))
        )

    def entries(self, uid, kind, start, end):
        return [
            self.unpack(row)
            for row in self.rows(
                "SELECT * FROM entries WHERE user_id=? AND kind=? AND date BETWEEN ? AND ? ORDER BY date,created_at",
                (uid, kind, start, end),
            )
        ]

    def workout_dates(self, uid, start, end):
        return [
            row["date"]
            for row in self.rows(
                "SELECT DISTINCT date FROM entries WHERE user_id=? AND kind='workout' "
                "AND date BETWEEN ? AND ? ORDER BY date",
                (uid, start, end),
            )
        ]

    def save_entry(self, uid, kind, data, eid=None):
        with self.lock:
            if eid:
                self.entry(uid, kind, eid)
            if kind == "workout":
                from fittrack.coaching import validate_cardio_source

                validate_cardio_source(self, uid, data)
            if kind == "meal":
                if data.get("nutrition_label"):
                    from fittrack.nutrition import label_food

                    data = data | {"items": [label_food(data["nutrition_label"])]}
                if data.get("image_id"):
                    self.image(uid, data["image_id"])
                if data.get("source_job_id"):
                    job = self.job(uid, data["source_job_id"])
                    if (
                        job["kind"] != "meal"
                        or job["status"] != "done"
                        or data.get("image_id") != job["request"].get("image_id")
                    ):
                        raise ValueError("识图任务与照片不匹配")
                    prior = self.rows(
                        "SELECT * FROM entries WHERE user_id=? AND source_job_id=?",
                        (uid, data["source_job_id"]),
                    )
                    if prior and eid is None:
                        return self.unpack(prior[0])
            if kind == "workout" and data.get("plan_id"):
                plan = self.entry(uid, "plan", data["plan_id"])
                if plan["status"] == "skipped":
                    raise ValueError("请先将跳过的排期改为待完成")
                prior = self.rows(
                    "SELECT * FROM entries WHERE user_id=? AND plan_id=?", (uid, data["plan_id"])
                )
                if prior and eid is None:
                    return self.unpack(prior[0])
            ident = eid or identifier()
            payload = encode(data)
            if eid:
                self.db.execute(
                    "UPDATE entries SET date=?,data=?,source_job_id=?,plan_id=? WHERE id=? AND user_id=?",
                    (
                        data["date"],
                        payload,
                        data.get("source_job_id"),
                        data.get("plan_id") if kind == "workout" else None,
                        eid,
                        uid,
                    ),
                )
            else:
                self.db.execute(
                    "INSERT INTO entries VALUES(?,?,?,?,?,?,?,?)",
                    (
                        ident,
                        uid,
                        kind,
                        data["date"],
                        payload,
                        data.get("source_job_id"),
                        data.get("plan_id") if kind == "workout" else None,
                        time.time(),
                    ),
                )
        return self.entry(uid, kind, ident)

    def delete_entry(self, uid, kind, eid):
        with self.lock:
            self.entry(uid, kind, eid)
            if kind == "plan" and self.rows(
                "SELECT id FROM entries WHERE user_id=? AND plan_id=?", (uid, eid)
            ):
                raise ValueError("已有训练记录引用该排期，请先删除或解除关联")
            self.db.execute(
                "DELETE FROM entries WHERE id=? AND user_id=? AND kind=?", (eid, uid, kind)
            )

    def plans(self, uid, start, end):
        plans = self.entries(uid, "plan", start, end)
        for plan in plans:
            matches = self.rows(
                "SELECT id FROM entries WHERE user_id=? AND plan_id=?", (uid, plan["id"])
            )
            plan["workout_id"] = matches[0]["id"] if matches else None
            if matches:
                plan["status"] = "completed"
        return plans

    def summary(self, uid, day):
        with self.lock:
            profile = self.profile(uid, day)
            body = self.body(uid, day)
            meals = self.entries(uid, "meal", day, day)
            workouts = self.entries(uid, "workout", day, day)
            totals = nutrients([item for meal in meals for item in meal["items"]])
            for meal in meals:
                meal["totals"] = nutrients(meal["items"])
            weight = (
                self.effective_weight(uid, day, profile["initial_weight_kg"]) if profile else None
            )
            resting = (
                (body or {}).get("resting_kcal")
                or (profile or {}).get("resting_kcal")
                or (profile or {}).get("estimated_resting_kcal")
            )
            if profile:
                for workout in workouts:
                    workout["energy"] = workout_energy(workout, weight, resting)
                    if workout.get("ai_estimate_job_id"):
                        source = self.job(uid, workout["ai_estimate_job_id"])
                        if source["kind"] != "cardio_estimate" or source["status"] != "done":
                            raise ValueError("有氧记录的 AI 来源无效")
                        workout["energy"]["source"] = "AI 辅助 MET；热量按有效身体资料计算"
                        workout["energy"]["ai_stale"] = source["result"].get("stale", True)
            exercise = sum(workout.get("energy", {}).get("net_kcal", 0) for workout in workouts)
            base = resting * activity_factor(profile) if profile and resting else None
            expenditure = base + exercise if profile else None
            completed = bool(
                self.rows(
                    "SELECT 1 FROM days WHERE user_id=? AND date=? AND completed=1", (uid, day)
                )
            )
        return {
            "date": day,
            "profile": profile,
            "body": body,
            "effective_weight_kg": weight,
            "resting_kcal": resting,
            "meals": meals,
            "workouts": workouts,
            "totals": totals,
            "exercise_kcal": round(exercise, 2),
            "baseline_kcal": round(base, 2) if base is not None else None,
            "expenditure_kcal": round(expenditure, 2) if expenditure is not None else None,
            "deficit_kcal": round(expenditure - totals["kcal"], 2)
            if expenditure is not None
            else None,
            "duration_minutes": sum(workout["duration_minutes"] for workout in workouts),
            "volume_kg": round(
                sum(workout.get("energy", {}).get("volume_kg", 0) for workout in workouts), 2
            ),
            "completed": completed,
        }

    def diet_history(self, uid, start, end):
        from fittrack.calculations import dates_between

        days = []
        selected = dates_between(start, end)
        if len(selected) > 7:
            raise ValueError("饮食历史每次最多查询7天")
        with self.lock:
            for day in selected:
                meals = self.entries(uid, "meal", day, day)
                for meal in meals:
                    meal["totals"] = nutrients(meal["items"])
                days.append(
                    {
                        "date": day,
                        "meals": meals,
                        "totals": nutrients([item for meal in meals for item in meal["items"]]),
                        "jobs": [
                            self.decode_job(row)
                            for row in self.rows(
                                "SELECT * FROM jobs WHERE user_id=? AND kind='meal' AND date=? ORDER BY created_at DESC",
                                (uid, day),
                            )
                        ],
                    }
                )
        return {"start": start, "end": end, "days": days}

    def context(self, uid, day):
        from datetime import date, timedelta

        first = (date.fromisoformat(day) - timedelta(days=6)).isoformat()
        last = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        summaries = [self.summary(uid, item) for item in dates_between(first, day)]
        # No username, credentials, image bytes or unrelated user data in coach input.
        days = []
        for summary in summaries:
            entry = {
                key: summary[key]
                for key in (
                    "date",
                    "body",
                    "profile",
                    "effective_weight_kg",
                    "totals",
                    "exercise_kcal",
                    "expenditure_kcal",
                    "deficit_kcal",
                    "duration_minutes",
                    "volume_kg",
                )
            }
            entry["meals"] = [
                {"slot": meal["slot"], "items": meal["items"], "note": meal["note"]}
                for meal in summary["meals"]
            ]
            entry["workouts"] = [
                {
                    key: workout[key]
                    for key in ("title", "duration_minutes", "intensity", "exercises")
                }
                for workout in summary["workouts"]
            ]
            days.append(entry)
        return {"date": day, "days": days, "plans": self.plans(uid, day, last)}

    def fingerprint(self, uid, day):
        return hashlib.sha256(encode(self.context(uid, day)).encode()).hexdigest()

    def goal_context(self, uid, day, profile):
        from datetime import date, timedelta

        # Use the validated form draft without saving it or inheriting its old targets.
        with self.lock:
            weight = self.effective_weight(uid, day, profile["initial_weight_kg"])
            body = self.body(uid, day)
            resting = (
                (body or {}).get("resting_kcal")
                or profile.get("resting_kcal")
                or resting_estimate(profile, weight)
            )
            first = (date.fromisoformat(day) - timedelta(days=6)).isoformat()
            recent = []
            workout_days = 0
            for item in dates_between(first, day):
                measured = self.body(uid, item)
                meals = self.entries(uid, "meal", item, item)
                workouts = self.entries(uid, "workout", item, item)
                daily_weight = self.effective_weight(uid, item, profile["initial_weight_kg"])
                daily_rest = (
                    (measured or {}).get("resting_kcal")
                    or profile.get("resting_kcal")
                    or resting_estimate(profile, daily_weight)
                )
                if daily_rest is None:
                    daily_rest = 1800
                exercise = sum(
                    workout_energy(workout, daily_weight, daily_rest)["net_kcal"]
                    for workout in workouts
                )
                workout_days += bool(workouts)
                recent.append(
                    {
                        "date": item,
                        "weight_kg": (measured or {}).get("weight_kg"),
                        "body_fat_pct": (measured or {}).get("body_fat_pct"),
                        "recorded_intake_kcal": nutrients(
                            [food for meal in meals for food in meal["items"]]
                        )["kcal"]
                        if meals
                        else None,
                        "recorded_exercise_net_kcal": round(exercise, 1),
                        "recorded_training_minutes": sum(w["duration_minutes"] for w in workouts),
                    }
                )
            exercise_average = round(sum(d["recorded_exercise_net_kcal"] for d in recent) / 7, 1)
            return {
                "date": day,
                "profile": {
                    key: profile[key]
                    for key in (
                        "height_cm",
                        "initial_weight_kg",
                        "sex",
                        "body_fat_pct",
                        "resting_kcal",
                        "age",
                        "activity_level",
                        "activity_factor",
                        "target_weight_kg",
                    )
                },
                "current_weight_kg": weight,
                "resting_kcal": resting,
                "average_exercise_net_kcal_7d": exercise_average,
                "recorded_training_days_7d": workout_days,
                "estimated_maintenance_kcal": round(
                    resting * activity_factor(profile) + exercise_average, 1
                ),
                "recent_days": recent,
            }

    def goal_fingerprint(self, uid, day, profile):
        return hashlib.sha256(encode(self.goal_context(uid, day, profile)).encode()).hexdigest()

    def cardio_context(self, uid, day, values):
        from fittrack.coaching import cardio_context

        return cardio_context(self, uid, day, values)

    def weekly_context(self, uid, start):
        from fittrack.coaching import weekly_context

        return weekly_context(self, uid, start)

    def weekly_review(self, uid, start=None):
        from fittrack.coaching import weekly_status

        return weekly_status(self, uid, start)

    def request_fingerprint(self, uid, request):
        from fittrack.coaching import fingerprint

        if request["kind"] == "goals":
            return self.goal_fingerprint(uid, request["date"], request["goal_profile"])
        if request["kind"] == "feedback":
            return self.fingerprint(uid, request["date"])
        if request["kind"] == "cardio_estimate":
            return fingerprint(self.cardio_context(uid, request["date"], request["cardio_input"]))
        if request["kind"] == "weekly_review":
            return fingerprint(self.weekly_context(uid, request["week_start"]))
        return None

    def create_job(self, uid, request):
        with self.lock:
            prior = self.rows(
                "SELECT * FROM jobs WHERE user_id=? AND request_key=?",
                (uid, request["request_key"]),
            )
            if prior:
                return self.decode_job(prior[0]), False
            jid = identifier()
            source_hash = self.request_fingerprint(uid, request)
            if request["kind"] in {"weekly_review", "cardio_estimate"}:
                sql = "SELECT * FROM jobs WHERE user_id=? AND kind=? AND date=? AND status IN ('queued','running')"
                args = (uid, request["kind"], request["date"])
                pending = self.rows(sql, args)
                for row in pending:
                    if request["kind"] == "weekly_review" or row["source_hash"] == source_hash:
                        return self.decode_job(row), False
            self.db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    jid,
                    uid,
                    request["kind"],
                    request["date"],
                    request["request_key"],
                    encode(request),
                    "queued",
                    None,
                    None,
                    source_hash,
                    time.time(),
                    None,
                ),
            )
            return self.job(uid, jid), True

    @staticmethod
    def decode_job(row):
        result = dict(row)
        for key in ("request", "result"):
            if result.get(key):
                result[key] = json.loads(result[key])
        result.pop("user_id", None)
        return result

    def job(self, uid, jid):
        return self.goal_job_state(
            uid,
            self.decode_job(self.one("SELECT * FROM jobs WHERE id=? AND user_id=?", (jid, uid))),
        )

    def delete_job(self, uid, jid):
        with self.lock:
            job = self.job(uid, jid)
            if job["kind"] != "meal":
                raise KeyError("记录不存在")
            if job["status"] in {"queued", "running"}:
                raise ActiveJobError("请等待照片分析结束后再删除记录")
            self.db.execute("BEGIN IMMEDIATE")
            try:
                for row in self.rows(
                    "SELECT id,data FROM entries WHERE user_id=? AND kind='meal' AND source_job_id=?",
                    (uid, jid),
                ):
                    data = json.loads(row["data"])
                    data["source_job_id"] = None
                    self.db.execute(
                        "UPDATE entries SET source_job_id=NULL,data=? WHERE id=? AND user_id=?",
                        (encode(data), row["id"], uid),
                    )
                self.db.execute("DELETE FROM jobs WHERE id=? AND user_id=?", (jid, uid))
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            return job

    def goal_job_state(self, uid, job):
        if (
            job["kind"] in {"goals", "cardio_estimate", "weekly_review"}
            and job["status"] == "done"
            and job["result"]
        ):
            try:
                job["result"]["stale"] = job["source_hash"] != self.request_fingerprint(
                    uid, job["request"]
                )
            except ValueError:
                job["result"]["stale"] = True
        return job

    def jobs(self, uid, day):
        return [
            self.goal_job_state(uid, self.decode_job(row))
            for row in self.rows(
                "SELECT * FROM jobs WHERE user_id=? AND date=? ORDER BY created_at DESC LIMIT 50",
                (uid, day),
            )
        ]

    def update_job(self, uid, jid, status, result=None, error=None):
        with self.lock:
            self.db.execute(
                "UPDATE jobs SET status=?,result=?,error=?,finished_at=? WHERE id=? AND user_id=?",
                (
                    status,
                    encode(result) if result is not None else None,
                    error,
                    time.time() if status in {"done", "failed", "interrupted"} else None,
                    jid,
                    uid,
                ),
            )

    def recover_jobs(self):
        with self.lock:
            self.db.execute(
                "UPDATE jobs SET status='interrupted',error='服务重启中断了任务，可手动重试',finished_at=? WHERE status IN ('queued','running')",
                (time.time(),),
            )

    def save_feedback(self, uid, day, data, fingerprint, created_at):
        with self.lock:
            self.db.execute(
                "INSERT INTO feedback VALUES(?,?,?,?,?) ON CONFLICT(user_id,date) DO UPDATE SET data=excluded.data,source_hash=excluded.source_hash,created_at=excluded.created_at WHERE excluded.created_at >= feedback.created_at",
                (uid, day, encode(data), fingerprint, created_at),
            )

    def feedback(self, uid, day):
        rows = self.rows("SELECT * FROM feedback WHERE user_id=? AND date=?", (uid, day))
        if not rows:
            return None
        row = rows[0]
        return {
            "data": json.loads(row["data"]),
            "created_at": row["created_at"],
            "stale": row["source_hash"] != self.fingerprint(uid, day),
        }

    def complete_day(self, uid, day):
        with self.lock:
            self.db.execute(
                "INSERT INTO days VALUES(?,?,1) ON CONFLICT(user_id,date) DO UPDATE SET completed=1",
                (uid, day),
            )
