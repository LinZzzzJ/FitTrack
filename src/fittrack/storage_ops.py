"""Owned workspaces, portable health-only backups, and observable operations."""

import hashlib
import json
import re
import shutil
import sqlite3
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from PIL import Image

from fittrack.ai import CardioEstimate, WeeklyReview
from fittrack.coaching import cardio_input, week_bounds
from fittrack.control import HEALTH_TABLES
from fittrack.models import (
    BodyRecord,
    JobRequest,
    LabelReadout,
    Meal,
    Profile,
    TrainingPlan,
    WorkoutTemplate,
    Workout,
)
from fittrack.paths import write_json, read_json
from fittrack.store import Store, encode, identifier

MAX_ARCHIVE = 512 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024


def tree_bytes(path):
    if not path.exists():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())


def verify_store(store, uid):
    if store.db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("数据库完整性校验失败")
    counts = {}
    for table in HEALTH_TABLES:
        rows = store.rows(f"SELECT * FROM {table} WHERE user_id=?", (uid,))
        counts[table] = len(rows)
        if store.rows(f"SELECT 1 FROM {table} WHERE user_id<>? LIMIT 1", (uid,)):
            raise ValueError("工作区包含其他账号数据")
    for image in store.rows("SELECT * FROM images WHERE user_id=?", (uid,)):
        path = store.images / f"{image['sha']}.{image['ext']}"
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != image["sha"]:
            raise ValueError("照片文件缺失或哈希不符")
    validate_coaching_links(store, uid)
    return counts


def validate_coaching_links(store, uid):
    """Validate saved provenance without rejecting legitimately stale historical estimates."""
    for row in store.rows("SELECT data FROM entries WHERE user_id=? AND kind='workout'", (uid,)):
        workout = json.loads(row["data"])
        if not workout.get("ai_estimate_job_id"):
            continue
        sources = store.rows(
            "SELECT * FROM jobs WHERE id=? AND user_id=?", (workout["ai_estimate_job_id"], uid)
        )
        if not sources:
            raise ValueError("有氧记录的 AI 来源任务缺失")
        source = sources[0]
        request = json.loads(source["request"])
        result = json.loads(source["result"] or "null")
        if (
            source["kind"] != "cardio_estimate"
            or source["status"] != "done"
            or workout["kind"] != "cardio"
            or source["date"] != workout["date"]
            or request.get("cardio_input") != cardio_input(workout)
            or not result
            or workout.get("met") != result.get("estimate", {}).get("effective_met")
            or workout.get("net_kcal_override") is not None
        ):
            raise ValueError("有氧记录的 AI 来源与保存内容不一致")


def validate_rows(tables):
    legacy_tables = set(HEALTH_TABLES) - {"workout_templates"}
    if set(tables) not in (set(HEALTH_TABLES), legacy_tables):
        raise ValueError("备份缺少必要的数据表")
    tables.setdefault("workout_templates", [])
    models = {"profiles": Profile, "bodies": BodyRecord}
    for table, rows in tables.items():
        if not isinstance(rows, list) or len(rows) > 100000:
            raise ValueError("备份记录格式或数量异常")
        for row in rows:
            if "date" in row:
                date.fromisoformat(row["date"])
            if table in models:
                models[table].model_validate(json.loads(row["data"]))
            elif table == "entries":
                model = {"meal": Meal, "workout": Workout, "plan": TrainingPlan}.get(row["kind"])
                if model is None:
                    raise ValueError("记录类型不支持")
                model.model_validate(json.loads(row["data"]))
                entry = json.loads(row["data"])
                if row["kind"] == "meal" and entry.get("nutrition_label"):
                    from fittrack.nutrition import label_food

                    expected = Meal.model_validate(
                        {
                            "date": entry["date"],
                            "slot": entry["slot"],
                            "title": entry.get("title", ""),
                            "note": entry.get("note", ""),
                            "items": [label_food(entry["nutrition_label"])],
                        }
                    ).model_dump(mode="json")["items"]
                    actual = Meal.model_validate(entry).model_dump(mode="json")["items"]
                    if actual != expected:
                        raise ValueError("标签记录与营养计算结果不一致")
            elif table == "workout_templates":
                WorkoutTemplate.model_validate(json.loads(row["data"]))
            elif table == "jobs":
                request = JobRequest.model_validate(json.loads(row["request"]))
                if request.kind != row["kind"] or request.date.isoformat() != row["date"]:
                    raise ValueError("任务类型或日期与内容不一致")
                if row["status"] not in {"queued", "running", "done", "failed", "interrupted"}:
                    raise ValueError("任务状态不支持")
                if (
                    request.kind == "meal"
                    and request.meal_mode == "label"
                    and row["status"] == "done"
                ):
                    LabelReadout.model_validate(json.loads(row["result"])["label"])
                if request.kind == "weekly_review":
                    _, last, _, _ = week_bounds(request.week_start.isoformat())
                    if last.isoformat() != row["date"]:
                        raise ValueError("周复盘周期与任务日期不一致")
                    if row["status"] == "done":
                        WeeklyReview.model_validate(json.loads(row["result"])["review"])
                elif request.kind == "cardio_estimate" and row["status"] == "done":
                    estimate = json.loads(row["result"])["estimate"]
                    CardioEstimate.model_validate(
                        {key: estimate[key] for key in CardioEstimate.model_fields}
                    )
            elif table == "images":
                if not re.fullmatch(r"[a-f0-9]{64}", row["sha"]) or row["ext"] not in {
                    "png",
                    "jpg",
                    "webp",
                    "gif",
                }:
                    raise ValueError("图片索引不合法")


def import_rows(store, uid, tables):
    validate_rows(tables)
    with store.lock:
        store.db.execute("BEGIN IMMEDIATE")
        try:
            for table in HEALTH_TABLES:
                store.db.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
                columns = [row["name"] for row in store.rows(f"PRAGMA table_info({table})")]
                for row in tables[table]:
                    if set(row) != set(columns):
                        raise ValueError("备份字段与当前版本不兼容")
                    values = [uid if key == "user_id" else row[key] for key in columns]
                    store.db.execute(
                        f"INSERT INTO {table} VALUES({','.join('?' for _ in columns)})", values
                    )
            store.db.execute("COMMIT")
        except Exception:
            store.db.execute("ROLLBACK")
            raise
    store.recover_jobs()


class StorageOperations:
    def __init__(self, hub, bus=None, mode="local"):
        self.hub, self.paths, self.bus, self.mode = hub, hub.paths, bus, mode
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fittrack-storage")
        self.lock = threading.RLock()
        self._active = False
        folder = self.paths.root / "runtime" / "operations"
        folder.mkdir(exist_ok=True)
        for file in folder.glob("*.json"):
            item = read_json(file)
            if item["status"] in {"queued", "running"}:
                item.update(
                    status="interrupted", error="服务已重启，原目录仍保留，请重新检查或操作"
                )
                write_json(file, item)

    def path(self, ident):
        if not re.fullmatch(r"[a-f0-9]{24}", ident):
            raise KeyError("操作不存在")
        return self.paths.root / "runtime" / "operations" / f"{ident}.json"

    def get(self, uid, ident):
        try:
            item = read_json(self.path(ident))
        except FileNotFoundError:
            raise KeyError("操作不存在") from None
        if item["user_id"] != uid:
            raise KeyError("操作不存在")
        return {k: v for k, v in item.items() if k != "user_id"}

    def recent(self, uid):
        files = sorted(
            (self.paths.root / "runtime" / "operations").glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        result = []
        for file in files:
            item = read_json(file)
            if item["user_id"] == uid:
                result.append(self.get(uid, item["id"]))
            if len(result) == 10:
                break
        return result

    def submit(self, uid, kind, work):
        with self.lock:
            if self._active or self.hub.frozen:
                raise ValueError("已有数据管理操作，请等待完成")
            if self.hub.pending(uid):
                raise ValueError("请等待当前 AI 任务结束后再操作数据")
            ident = identifier()
            item = {
                "id": ident,
                "user_id": uid,
                "kind": kind,
                "status": "queued",
                "progress": 0,
                "error": None,
                "created_at": time.time(),
                "result": None,
            }
            write_json(self.path(ident), item)
            self._active = True

            def run():
                def progress(amount):
                    item.update(status="running", progress=amount)
                    write_json(self.path(ident), item)

                try:
                    progress(5)
                    result = work(progress)
                    item.update(status="done", progress=100, result=result)
                except (ValueError, OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
                    # Values contain local validation descriptions, never provider bodies or keys.
                    message = (
                        str(exc)
                        if isinstance(exc, ValueError)
                        else "文件或数据库操作失败，原数据已保留，请检查空间与权限"
                        + f"（{getattr(exc, 'sqlite_errorname', None) or getattr(exc, 'winerror', None) or type(exc).__name__}）"
                    )
                    item.update(status="failed", error=message)
                except Exception:
                    item.update(status="failed", error="数据操作失败，原目录未删除")
                finally:
                    try:
                        write_json(self.path(ident), item)
                    finally:
                        with self.lock:
                            self._active = False
                    if self.bus:
                        self.bus.publish(uid, {"type": "storage", "status": item["status"]})

            self.pool.submit(run)
            return self.get(uid, ident)

    def _target(self, uid, relative):
        target = self.paths.workspace(relative)
        current = self.hub.for_user(uid).home
        if target == current or target.is_relative_to(current) or current.is_relative_to(target):
            raise ValueError("目标不能与当前工作区相同、包含或嵌套")
        for row in self.hub.control.rows("SELECT path FROM workspaces"):
            other = self.paths.workspace(row["path"])
            if target == other or target.is_relative_to(other) or other.is_relative_to(target):
                raise ValueError("目标与现有账号工作区重叠")
        if target.exists() and any(target.iterdir()):
            raise ValueError("请选择空的专用子目录，不能覆盖已有文件或旧档案")
        return target

    def _switch(self, uid, target):
        with self.hub.lock:
            return self._switch_locked(uid, target)

    def _switch_locked(self, uid, target):
        previous = self.hub.for_user(uid)
        old = previous.home
        relative = target.relative_to(self.paths.root).as_posix()
        candidate = Store(target, owner_id=uid)
        try:
            verify_store(candidate, uid)
            write_json(target / "workspace.json", {"format": "fittrack-workspace", "owner": uid})
            with self.hub.control.lock:
                control = self.hub.control
                archives = control.metadata("archives:" + uid, [])
                control.db.execute("BEGIN IMMEDIATE")
                try:
                    control.db.execute(
                        "UPDATE workspaces SET path=? WHERE user_id=?", (relative, uid)
                    )
                    control.set_metadata(
                        "archives:" + uid, archives + [old.relative_to(self.paths.root).as_posix()]
                    )
                    control.db.execute("COMMIT")
                except Exception:
                    control.db.execute("ROLLBACK")
                    raise
            self.hub._stores[uid] = candidate
        except Exception:
            candidate.close()
            raise
        previous.close()
        try:
            write_json(
                old / "workspace.json",
                {
                    "format": "fittrack-workspace",
                    "owner": uid,
                    "retired": True,
                    "replaced_by": relative,
                },
            )
        except OSError:
            # The committed mapping and archive registry remain authoritative.
            pass
        return {"workspace": relative, "retained": old.relative_to(self.paths.root).as_posix()}

    def migrate(self, uid, relative, progress=lambda amount: None):
        with self.hub.maintenance(uid) as source:
            target = self._target(uid, relative)
            counts = verify_store(source, uid)
            target.mkdir(parents=True, exist_ok=True)
            write_json(
                target / "workspace.json",
                {"format": "fittrack-workspace", "owner": uid, "incomplete": True},
            )
            candidate = Store(target, owner_id=uid)
            try:
                source.db.backup(candidate.db)
                progress(40)
                for image in source.rows("SELECT * FROM images WHERE user_id=?", (uid,)):
                    name = f"{image['sha']}.{image['ext']}"
                    shutil.copyfile(source.images / name, candidate.images / name)
                if verify_store(candidate, uid) != counts:
                    raise ValueError("复制后的记录数量不一致，原目录继续使用")
            finally:
                candidate.close()
            progress(90)
            return self._switch(uid, target)

    def backups(self, uid):
        self.hub.user(uid)
        folder = self.paths.root / "backups" / uid
        if not folder.exists():
            return []
        return [
            {
                "id": p.stem,
                "name": p.name,
                "size": p.stat().st_size,
                "created_at": p.stat().st_mtime,
            }
            for p in sorted(folder.glob("*.zip"), reverse=True)
        ]

    def backup_path(self, uid, ident):
        self.hub.user(uid)
        if not re.fullmatch(r"[a-f0-9]{24}", ident):
            raise KeyError("备份不存在")
        path = self.paths.root / "backups" / uid / f"{ident}.zip"
        if not path.is_file():
            raise KeyError("备份不存在")
        return path

    def backup(self, uid, progress=lambda amount: None):
        with self.hub.maintenance(uid) as source:
            verify_store(source, uid)
            tables = {
                table: source.rows(f"SELECT * FROM {table} WHERE user_id=?", (uid,))
                for table in HEALTH_TABLES
            }
            manifest = {"format": "fittrack-health", "version": 2, "tables": tables}
            folder = self.paths.root / "backups" / uid
            folder.mkdir(exist_ok=True)
            ident = identifier()
            temp = self.paths.root / "tmp" / f"{ident}.zip.part"
            try:
                with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("manifest.json", encode(manifest))
                    for image in tables["images"]:
                        name = f"{image['sha']}.{image['ext']}"
                        archive.write(source.images / name, "images/" + name)
                progress(90)
                if temp.stat().st_size > MAX_ARCHIVE:
                    raise ValueError("备份超过 512 MiB，请使用停服后的根目录复制备份")
                temp.replace(folder / f"{ident}.zip")
            finally:
                temp.unlink(missing_ok=True)
            return {"backup_id": ident, "name": f"{ident}.zip"}

    def restore(self, uid, archive_path, progress=lambda amount: None):
        with self.hub.maintenance(uid):
            if archive_path.stat().st_size > MAX_ARCHIVE:
                raise ValueError("备份超过 512 MiB 限制")
            target = self._target(uid, f"records/restored-{uid}-{identifier()}")
            with zipfile.ZipFile(archive_path) as archive:
                infos = archive.infolist()
                names = [i.filename for i in infos]
                if (
                    len(names) > 10002
                    or len(set(names)) != len(names)
                    or sum(i.file_size for i in infos) > MAX_EXPANDED
                ):
                    raise ValueError("备份体积、文件数量或重复路径异常")
                if (
                    "manifest.json" not in names
                    or archive.getinfo("manifest.json").file_size > 32 * 1024 * 1024
                ):
                    raise ValueError("备份清单缺失或过大")
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("format") != "fittrack-health" or manifest.get("version") not in {1, 2}:
                    raise ValueError("不支持此备份格式")
                tables = manifest["tables"]
                validate_rows(tables)
                expected = {"manifest.json"} | {
                    f"images/{row['sha']}.{row['ext']}" for row in tables["images"]
                }
                if set(names) != expected or any(
                    i.is_dir() or (i.external_attr >> 16) & 0o170000 == 0o120000 for i in infos
                ):
                    raise ValueError("备份包含越界、额外路径或链接")
                target.mkdir(parents=True, exist_ok=True)
                candidate = Store(target, owner_id=uid)
                try:
                    for image in tables["images"]:
                        name = f"{image['sha']}.{image['ext']}"
                        if archive.getinfo("images/" + name).file_size > 12 * 1024 * 1024:
                            raise ValueError("备份照片过大")
                        data = archive.read("images/" + name)
                        if hashlib.sha256(data).hexdigest() != image["sha"]:
                            raise ValueError("备份照片哈希不符")
                        import io

                        with Image.open(io.BytesIO(data)) as img:
                            if img.width * img.height > 40_000_000:
                                raise ValueError("备份照片尺寸过大")
                            img.verify()
                        (candidate.images / name).write_bytes(data)
                    import_rows(candidate, uid, tables)
                    verify_store(candidate, uid)
                finally:
                    candidate.close()
            progress(90)
            return self._switch(uid, target)

    def shutdown(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
