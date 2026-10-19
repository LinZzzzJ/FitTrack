from concurrent.futures import ThreadPoolExecutor

from fittrack.ai import AIClient, AIError, CardioEstimate, WeeklyReview
from fittrack.calculations import nutrients, workout_energy
from fittrack.models import LabelReadout


class JobRunner:
    def __init__(self, store, settings, bus, ai=None):
        self.store, self.settings, self.bus = store, settings, bus
        self.ai = ai or AIClient()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fittrack-ai")

    def submit(self, uid, request, session_token=""):
        with self.store.lock:
            prior = self.store.rows(
                "SELECT id FROM jobs WHERE user_id=? AND request_key=?",
                (uid, request["request_key"]),
            )
            if prior:
                return self.store.job(uid, prior[0]["id"])
            if request["kind"] == "meal":
                if not request.get("image_id"):
                    raise ValueError("请先上传餐食照片")
                path = self.store.image_path(uid, request["image_id"])
                context = None
            elif request["kind"] == "goals":
                if not request.get("goal_profile"):
                    raise ValueError("请先填写身体资料和目标体重")
                path = None
                context = self.store.goal_context(uid, request["date"], request["goal_profile"])
            elif request["kind"] == "cardio_estimate":
                path = None
                context = self.store.cardio_context(uid, request["date"], request["cardio_input"])
            elif request["kind"] == "weekly_review":
                status = self.store.weekly_review(uid, request["week_start"])
                if request["date"] != status["week_end"]:
                    raise ValueError("周复盘任务日期必须为该周的结束日期")
                if status["active_job"]:
                    return status["active_job"]
                if not status["can_generate"]:
                    raise ValueError(
                        status["reason"]
                        + f"（已完成 {status['completed_days']}/7 天；{status['earliest_generation_date']} 起可生成）"
                    )
                path = None
                context = self.store.weekly_context(uid, request["week_start"])
            else:
                if not self.store.profile(uid, request["date"]):
                    raise ValueError("请先填写身体资料和静息能量")
                path = None
                context = self.store.context(uid, request["date"])
            config = (
                self.settings.snapshot_for(uid, session_token)
                if hasattr(self.settings, "snapshot_for")
                else self.settings.snapshot()
            )
            if not config["api_key"]:
                raise ValueError("请在“我的 AI 配置”中填写你自己的密钥；手动记录不受影响")
            job, created = self.store.create_job(uid, request)
        if created:
            self.pool.submit(self._run, uid, job, path, context, config)
        return job

    def _run(self, uid, job, path, context, config):
        jid = job["id"]
        self.store.update_job(uid, jid, "running")
        self.bus.publish(uid, {"type": "job", "id": jid, "date": job["date"], "status": "running"})
        try:
            if job["kind"] == "meal":
                if job["request"].get("meal_mode", "photo") == "label":
                    label, usage = self.ai.meal_label(config, path, job["request"]["note"])
                    result = {"label": LabelReadout.model_validate(label).model_dump()}
                else:
                    result, usage = self.ai.meal(config, path, job["request"]["note"])
                    result["totals"] = nutrients(result["items"])
            elif job["kind"] == "goals":
                goals, usage = self.ai.goals(config, context)
                result = {
                    "goals": goals,
                    "basis": {
                        key: context[key]
                        for key in (
                            "current_weight_kg",
                            "resting_kcal",
                            "estimated_maintenance_kcal",
                            "average_exercise_net_kcal_7d",
                            "recorded_training_days_7d",
                        )
                    },
                    "stale": job["source_hash"]
                    != self.store.goal_fingerprint(
                        uid, job["date"], job["request"]["goal_profile"]
                    ),
                }
            elif job["kind"] == "cardio_estimate":
                estimate, usage = self.ai.cardio_estimate(config, context)
                estimate = CardioEstimate.model_validate(estimate).model_dump()
                energy = workout_energy(
                    context["input"] | {"met": estimate["effective_met"]},
                    context["weight_kg"],
                    context["resting_kcal"],
                )
                result = {
                    "estimate": estimate
                    | {key: energy[key] for key in ("gross_kcal", "net_kcal")}
                    | {"weight_kg": context["weight_kg"], "resting_kcal": context["resting_kcal"]}
                }
                result["stale"] = job["source_hash"] != self.store.request_fingerprint(
                    uid, job["request"]
                )
            elif job["kind"] == "weekly_review":
                review, usage = self.ai.weekly_review(config, context)
                result = {
                    "review": WeeklyReview.model_validate(review).model_dump(),
                    "statistics": context["statistics"],
                }
                result["stale"] = job["source_hash"] != self.store.request_fingerprint(
                    uid, job["request"]
                )
            else:
                result, usage = self.ai.feedback(config, context)
                self.store.save_feedback(
                    uid, job["date"], result, job["source_hash"], job["created_at"]
                )
                result["stale"] = job["source_hash"] != self.store.fingerprint(uid, job["date"])
            result["usage"] = usage
            self.store.update_job(uid, jid, "done", result=result)
        except AIError as exc:
            self.store.update_job(uid, jid, "failed", error=str(exc))
        except Exception:
            # Do not expose provider responses, credentials, paths or request content.
            self.store.update_job(uid, jid, "failed", error="任务处理失败，记录已保留，可手动重试")
        try:
            status = self.store.job(uid, jid)["status"]
        except KeyError:
            # A completed meal analysis may have been deleted before this notification.
            return
        self.bus.publish(
            uid,
            {
                "type": "job",
                "id": jid,
                "date": job["date"],
                "status": status,
            },
        )

    def shutdown(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.store.recover_jobs()
