import asyncio
import json
import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pwdlib import PasswordHash

from fittrack.calculations import ACTIVITIES, ACTIVITY_LEVELS, dates_between, today, workout_energy
from fittrack.exercise_catalog import exercise_catalog
from fittrack.mobile_auth import create_pair, redeem_pair, request_token
from fittrack.models import (
    AISettings,
    BodyRecord,
    Credentials,
    JobRequest,
    Meal,
    NutritionLabel,
    Profile,
    TrainingPlan,
    Workout,
    WorkoutTemplate,
)
from fittrack.store import ActiveJobError

COOKIE = "fittrack_session"
password_hash = PasswordHash.recommended()
dummy_hash = password_hash.hash("fittrack-timing-placeholder")


def current_user(request: Request):
    try:
        return request.app.state.store.session_user(request_token(request))
    except KeyError:
        raise HTTPException(401, "请登录后继续") from None


def admin_user(user=Depends(current_user)):
    if not user["is_admin"]:
        raise HTTPException(403, "此操作仅限本机管理员")
    return user


def router():
    api = APIRouter(prefix="/api")

    @api.get("/version")
    def version(request: Request):
        return request.app.state.build_info.public()

    def session(response, store, uid):
        response.set_cookie(
            COOKIE,
            store.session(uid),
            max_age=14 * 86400,
            httponly=True,
            samesite="strict",
            secure=getattr(store, "secure_cookies", False),
            path="/",
        )

    @api.post("/auth/register", status_code=201)
    def register(body: Credentials, request: Request, response: Response):
        runtime = getattr(request.app.state, "runtime", None)
        if runtime and runtime.config.mode == "server":
            if not runtime.config.allow_registration:
                raise HTTPException(403, "管理员未开放注册，请使用已有账号配对手机")
            request.app.state.auth_limiter.check(
                request.client.host if request.client else "unknown"
            )
        username = body.username.strip().casefold()
        if len(username) < 2:
            raise ValueError("用户名至少为两个字符")
        store = request.app.state.store
        try:
            user = store.register(username, password_hash.hash(body.password))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "用户名已存在") from None
        session(response, store, user["id"])
        return user

    @api.post("/auth/login")
    def login(body: Credentials, request: Request, response: Response):
        runtime = getattr(request.app.state, "runtime", None)
        if runtime and runtime.config.mode == "server":
            request.app.state.auth_limiter.check(
                request.client.host if request.client else "unknown"
            )
        store = request.app.state.store
        rows = store.rows(
            "SELECT id,password_hash FROM users WHERE username=?",
            (body.username.strip().casefold(),),
        )
        candidate = rows[0]["password_hash"] if rows else dummy_hash
        valid = password_hash.verify(body.password, candidate)
        if not rows or not valid:
            raise HTTPException(401, "用户名或密码不正确")
        user = store.user(rows[0]["id"])
        session(response, store, user["id"])
        return user

    @api.post("/auth/logout", status_code=204)
    def logout(request: Request, response: Response, user=Depends(current_user)):
        settings = request.app.state.settings
        token = request_token(request)
        if hasattr(settings, "logout"):
            settings.logout(user["id"], token)
        request.app.state.store.logout(token)
        response.delete_cookie(COOKIE, path="/")

    @api.post("/mobile/pair/create")
    def create_mobile_pair(request: Request, user=Depends(current_user)):
        """Create a short-lived code for a native app without exposing a password."""
        if request.headers.get("authorization"):
            raise HTTPException(403, "请从已登录的 PC 网页生成配对码")
        control = getattr(request.app.state.store, "control", request.app.state.store)
        return create_pair(control, user["id"])

    @api.post("/mobile/pair/redeem")
    def redeem_mobile_pair(body: dict, request: Request):
        request.app.state.pairing_limiter.check(
            request.client.host if request.client else "unknown"
        )
        code = body.get("code")
        if (
            set(body) != {"code"}
            or not isinstance(code, str)
            or len(code) != 8
            or any(c not in "0123456789" for c in code)
        ):
            raise HTTPException(400, "配对码无效或已过期")
        control = getattr(request.app.state.store, "control", request.app.state.store)
        return redeem_pair(control, code)

    @api.get("/mobile/devices")
    def mobile_devices(request: Request, user=Depends(current_user)):
        control = getattr(request.app.state.store, "control", request.app.state.store)
        return control.rows(
            "SELECT token_hash AS id,name,created_at FROM mobile_devices WHERE user_id=?",
            (user["id"],),
        )

    @api.delete("/mobile/devices/{ident}", status_code=204)
    def revoke_mobile_device(ident: str, request: Request, user=Depends(current_user)):
        control = getattr(request.app.state.store, "control", request.app.state.store)
        with control.lock:
            rows = control.rows(
                "SELECT token_hash FROM mobile_devices WHERE token_hash=? AND user_id=?",
                (ident, user["id"]),
            )
            if not rows:
                raise KeyError("设备不存在")
            control.db.execute("DELETE FROM sessions WHERE token_hash=?", (ident,))

    @api.post("/mobile/refresh")
    def refresh_mobile_session(request: Request, user=Depends(current_user)):
        if not request.headers.get("authorization"):
            raise HTTPException(403, "此接口仅供设备令牌使用")
        from fittrack.mobile_auth import digest
        import time

        control = getattr(request.app.state.store, "control", request.app.state.store)
        with control.lock:
            old = request_token(request)
            token = control.session(user["id"])
            control.db.execute(
                "INSERT INTO mobile_devices VALUES(?,?,?,?)",
                (digest(token), user["id"], "Android", time.time()),
            )
            control.logout(old)
        return {"token": token, "expires_in": 14 * 86400, "user": user}

    @api.get("/me")
    def me(request: Request, user=Depends(current_user)):
        return {
            "user": user,
            "today": today(),
            "profile": request.app.state.store.profile(user["id"], today()),
            "ai": request.app.state.settings.public_for(user["id"], request_token(request))
            if hasattr(request.app.state.settings, "public_for")
            else request.app.state.settings.public(),
            "runtime": request.app.state.runtime.config.capabilities(user)
            if hasattr(request.app.state, "runtime")
            else None,
            "activities": ACTIVITIES,
            "activity_levels": ACTIVITY_LEVELS,
            "exercise_catalog_version": 1,
        }

    @api.get("/exercise-catalog")
    def get_exercise_catalog():
        return {"version": 1, "exercises": exercise_catalog()}

    @api.put("/settings")
    def settings(body: AISettings, request: Request, user=Depends(current_user)):
        settings = request.app.state.settings
        values = body.model_dump(exclude_unset=True)
        if hasattr(settings, "save_for"):
            request.app.state.store.assert_writable(user["id"])
            return settings.save_for(user["id"], request_token(request), values)
        admin_user(user)
        return settings.save(values)

    @api.delete("/settings/key", status_code=204)
    def clear_key(request: Request, user=Depends(current_user)):
        request.app.state.store.assert_writable(user["id"])
        request.app.state.settings.clear_for(user["id"])

    @api.post("/settings/test-connection")
    def test_connection(request: Request, user=Depends(current_user)):
        return request.app.state.settings.test_for(user["id"], request_token(request))

    @api.get("/profile")
    def get_profile(request: Request, day: date | None = None, user=Depends(current_user)):
        return request.app.state.store.profile(user["id"], day.isoformat() if day else today())

    @api.put("/profile")
    def profile(body: Profile, request: Request, user=Depends(current_user)):
        return request.app.state.store.save_profile(user["id"], body.model_dump(mode="json"))

    @api.get("/body")
    def bodies(request: Request, start: date, end: date, user=Depends(current_user)):
        dates_between(start.isoformat(), end.isoformat())
        return [
            json.loads(row["data"])
            for row in request.app.state.store.rows(
                "SELECT data FROM bodies WHERE user_id=? AND date BETWEEN ? AND ? ORDER BY date",
                (user["id"], start.isoformat(), end.isoformat()),
            )
        ]

    @api.put("/body")
    def body(body: BodyRecord, request: Request, user=Depends(current_user)):
        return request.app.state.store.save_body(user["id"], body.model_dump(mode="json"))

    @api.delete("/body/{day}", status_code=204)
    def delete_body(day: date, request: Request, user=Depends(current_user)):
        request.app.state.store.delete_body(user["id"], day.isoformat())

    @api.post("/uploads", status_code=201)
    async def upload(request: Request, file: UploadFile = File(), user=Depends(current_user)):
        data = await file.read(12 * 1024 * 1024 + 1)
        await file.close()
        return request.app.state.store.put_image(user["id"], data)

    @api.get("/images/{iid}")
    def image(iid: str, request: Request, thumb: bool = False, user=Depends(current_user)):
        path = request.app.state.store.image_path(user["id"], iid, thumb)
        return FileResponse(
            path,
            headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
        )

    def entry_routes(kind, path, model):
        def create(body, request: Request, user=Depends(current_user)):
            data = body.model_dump(mode="json")
            if kind == "workout":
                workout_energy(data, 75, 1800)
            return request.app.state.store.save_entry(user["id"], kind, data)

        def update(eid: str, body, request: Request, user=Depends(current_user)):
            data = body.model_dump(mode="json")
            if kind == "workout":
                workout_energy(data, 75, 1800)
            return request.app.state.store.save_entry(user["id"], kind, data, eid)

        def remove(eid: str, request: Request, user=Depends(current_user)):
            request.app.state.store.delete_entry(user["id"], kind, eid)
            return Response(status_code=204)

        create.__annotations__["body"] = model
        update.__annotations__["body"] = model
        api.add_api_route(path, create, methods=["POST"], status_code=201)
        api.add_api_route(path + "/{eid}", update, methods=["PUT"])
        api.add_api_route(path + "/{eid}", remove, methods=["DELETE"], status_code=204)

    entry_routes("meal", "/meals", Meal)
    entry_routes("workout", "/workouts", Workout)
    entry_routes("plan", "/plans", TrainingPlan)

    @api.get("/workout-days")
    def workout_days(request: Request, start: date, end: date, user=Depends(current_user)):
        dates_between(start.isoformat(), end.isoformat())
        return request.app.state.store.workout_dates(user["id"], start.isoformat(), end.isoformat())

    @api.get("/workout-templates")
    def workout_templates(request: Request, user=Depends(current_user)):
        return request.app.state.store.templates(user["id"])

    @api.post("/workout-templates", status_code=201)
    def create_workout_template(
        body: WorkoutTemplate, request: Request, user=Depends(current_user)
    ):
        return request.app.state.store.save_template(user["id"], body.model_dump(mode="json"))

    @api.put("/workout-templates/{tid}")
    def update_workout_template(
        tid: str, body: WorkoutTemplate, request: Request, user=Depends(current_user)
    ):
        return request.app.state.store.save_template(user["id"], body.model_dump(mode="json"), tid)

    @api.delete("/workout-templates/{tid}", status_code=204)
    def delete_workout_template(tid: str, request: Request, user=Depends(current_user)):
        request.app.state.store.delete_template(user["id"], tid)
        return Response(status_code=204)

    @api.get("/diet-history")
    def diet_history(request: Request, start: date, end: date, user=Depends(current_user)):
        return request.app.state.store.diet_history(user["id"], start.isoformat(), end.isoformat())

    @api.post("/nutrition-label/preview")
    def preview_label(body: NutritionLabel, user=Depends(current_user)):
        from fittrack.nutrition import label_food

        item = label_food(body.model_dump(mode="json"))
        return {"item": item}

    @api.get("/plans")
    def plans(request: Request, start: date, end: date, user=Depends(current_user)):
        dates_between(start.isoformat(), end.isoformat())
        return request.app.state.store.plans(user["id"], start.isoformat(), end.isoformat())

    @api.post("/plans/{pid}/complete", status_code=201)
    def complete_plan(pid: str, request: Request, user=Depends(current_user)):
        store = request.app.state.store
        plan = store.entry(user["id"], "plan", pid)
        payload = Workout.model_validate(
            {
                key: plan[key]
                for key in (
                    "date",
                    "title",
                    "kind",
                    "activity",
                    "duration_minutes",
                    "intensity",
                    "note",
                    "exercises",
                )
            }
            | {"plan_id": pid}
        ).model_dump(mode="json")
        return store.save_entry(user["id"], "workout", payload)

    @api.get("/days/{day}")
    def day_summary(day: date, request: Request, user=Depends(current_user)):
        store = request.app.state.store
        selected = day.isoformat()
        return store.summary(user["id"], selected) | {
            "feedback": store.feedback(user["id"], selected),
            "jobs": store.jobs(user["id"], selected),
            "plans": store.plans(user["id"], selected, selected),
        }

    @api.post("/days/{day}/complete")
    def complete_day(day: date, request: Request, user=Depends(current_user)):
        request.app.state.store.complete_day(user["id"], day.isoformat())
        return {"completed": True}

    @api.get("/trends")
    def trends(
        request: Request,
        start: date,
        end: date,
        measurement_start: date | None = None,
        user=Depends(current_user),
    ):
        store = request.app.state.store
        days = []
        for day in dates_between(start.isoformat(), end.isoformat()):
            summary = store.summary(user["id"], day)
            days.append(
                {
                    key: summary[key]
                    for key in (
                        "date",
                        "body",
                        "totals",
                        "expenditure_kcal",
                        "deficit_kcal",
                        "exercise_kcal",
                        "duration_minutes",
                        "volume_kg",
                        "completed",
                    )
                }
                | {"meal_count": len(summary["meals"])}
            )
        for index, day in enumerate(days):
            beginning = (date.fromisoformat(day["date"]) - timedelta(days=6)).isoformat()
            if measurement_start:
                beginning = max(beginning, measurement_start.isoformat())
            weights = [
                json.loads(row["data"]).get("weight_kg")
                for row in store.rows(
                    "SELECT data FROM bodies WHERE user_id=? AND date BETWEEN ? AND ?",
                    (user["id"], beginning, day["date"]),
                )
            ]
            weights = [weight for weight in weights if weight is not None]
            days[index]["weight_average_7d"] = (
                round(sum(weights) / len(weights), 2) if weights else None
            )
        return {"days": days, "plans": store.plans(user["id"], start.isoformat(), end.isoformat())}

    @api.get("/weekly-review")
    def weekly_review(request: Request, week_start: date | None = None, user=Depends(current_user)):
        return request.app.state.store.weekly_review(
            user["id"], week_start.isoformat() if week_start else None
        )

    @api.post("/jobs", status_code=202)
    def submit(body: JobRequest, request: Request, user=Depends(current_user)):
        return request.app.state.runner.submit(
            user["id"], body.model_dump(mode="json"), request_token(request)
        )

    @api.get("/jobs/{jid}")
    def job(jid: str, request: Request, user=Depends(current_user)):
        return request.app.state.store.job(user["id"], jid)

    @api.delete("/jobs/{jid}", status_code=204)
    def delete_job(jid: str, request: Request, user=Depends(current_user)):
        try:
            job = request.app.state.store.delete_job(user["id"], jid)
        except ActiveJobError as exc:
            raise HTTPException(409, str(exc)) from None
        request.app.state.bus.publish(
            user["id"], {"type": "job_deleted", "id": jid, "date": job["date"]}
        )

    @api.get("/events")
    async def events(request: Request, user=Depends(current_user)):
        bus, store = request.app.state.bus, request.app.state.store
        uid = user["id"]
        queue = bus.subscribe(uid)

        async def stream():
            try:
                yield "event: ready\ndata: {}\n\n"
                while not bus.closed and not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        try:
                            store.session_user(request_token(request))
                        except KeyError:
                            break
                        yield ": heartbeat\n\n"
                        continue
                    if event is None:
                        break
                    yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            finally:
                bus.unsubscribe(uid, queue)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return api
