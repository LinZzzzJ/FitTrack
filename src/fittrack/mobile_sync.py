"""Account-bound three-way sync over the existing PC health rows.

Metadata lives beside, never inside, health ZIP tables. PC writes are detected
on pull, so existing Store write paths need no parallel mutation implementation.
"""

import hashlib
import json
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import Field

from fittrack.control import HEALTH_TABLES
from fittrack.models import Model
from fittrack.routes import current_user
from fittrack.storage_ops import validate_rows, verify_store
from fittrack.store import encode, identifier

SCHEMA = """
CREATE TABLE IF NOT EXISTS mobile_sync_rows(resource TEXT PRIMARY KEY,revision INTEGER NOT NULL,data TEXT);
CREATE TABLE IF NOT EXISTS mobile_sync_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mobile_sync_conflicts(id TEXT PRIMARY KEY,resource TEXT NOT NULL,local TEXT,remote TEXT,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS mobile_sync_receipts(id TEXT PRIMARY KEY,result TEXT NOT NULL,created_at REAL NOT NULL);
"""


def key_for(table, row):
    return row.get("id", row.get("date"))


def rows_by_key(store, uid):
    return {
        f"{table}/{key_for(table, row)}": row
        for table in HEALTH_TABLES
        for row in store.rows(f"SELECT * FROM {table} WHERE user_id=?", (uid,))
    }


def refresh(store, uid):
    store.db.executescript(SCHEMA)
    if not store.rows("SELECT value FROM mobile_sync_meta WHERE key='epoch'"):
        store.db.execute("INSERT INTO mobile_sync_meta VALUES('epoch',?)", (identifier(),))
    current = rows_by_key(store, uid)
    known = {r["resource"]: r for r in store.rows("SELECT * FROM mobile_sync_rows")}
    revision = (
        int(store.rows("SELECT value FROM mobile_sync_meta WHERE key='revision'")[0]["value"])
        if store.rows("SELECT value FROM mobile_sync_meta WHERE key='revision'")
        else 0
    )
    for resource in sorted(set(current) | set(known)):
        data = encode(current[resource]) if resource in current else None
        if resource not in known or known[resource]["data"] != data:
            revision += 1
            store.db.execute(
                "INSERT INTO mobile_sync_rows VALUES(?,?,?) ON CONFLICT(resource) DO UPDATE SET revision=excluded.revision,data=excluded.data",
                (resource, revision, data),
            )
    store.db.execute(
        "INSERT INTO mobile_sync_meta VALUES('revision',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(revision),),
    )
    return revision


def merge(base, local, remote):
    """Merge fields changed on one side, keeping both copies on concurrency."""
    if local == remote or remote == base:
        return local, False
    if local == base:
        return remote, False
    if all(isinstance(x, dict) for x in (base, local, remote)):
        result, conflict = {}, False
        missing = object()
        for key in sorted(set(base) | set(local) | set(remote)):
            b, local_value, r = (
                base.get(key, missing),
                local.get(key, missing),
                remote.get(key, missing),
            )
            if key == "user_id":
                result[key] = remote[key]
                continue
            if key == "data" and all(isinstance(x, str) for x in (b, local_value, r)):
                value, bad = merge(json.loads(b), json.loads(local_value), json.loads(r))
                value = encode(value)
            elif local_value is missing or r is missing or b is missing:
                if local_value == r or r == b:
                    value, bad = local_value, False
                elif local_value == b:
                    value, bad = r, False
                else:
                    value, bad = r, True
            else:
                value, bad = merge(b, local_value, r)
            if value is not missing:
                result[key] = value
            conflict |= bad
        return result, conflict
    # Historical exercise/set lists have no stable element ids. Treat them as a
    # single field rather than inventing ids or interleaving unrelated sets.
    return remote, True


class Change(Model):
    id: str = Field(pattern=r"^[a-f0-9]{24}$")
    table: str
    key: str = Field(min_length=1, max_length=100)
    base: dict | None = None
    row: dict | None = None


class Push(Model):
    changes: list[Change] = Field(max_length=200)


def owned_store(request, uid):
    hub = request.app.state.store
    if not hasattr(hub, "for_user"):
        raise HTTPException(409, "移动同步需要受控个人工作区，请使用标准启动入口")
    hub.assert_writable(uid)
    return hub.for_user(uid)


def router():
    api = APIRouter(prefix="/api/mobile")

    @api.get("/sync")
    def pull(
        request: Request,
        cursor: int = 0,
        epoch: str = "",
        limit: int = Query(default=200, ge=1, le=200),
        user=Depends(current_user),
    ):
        store = owned_store(request, user["id"])
        if cursor < 0:
            raise ValueError("同步游标无效")
        with request.app.state.store.lock, store.lock:
            revision = refresh(store, user["id"])
            current_epoch = store.rows("SELECT value FROM mobile_sync_meta WHERE key='epoch'")[0][
                "value"
            ]
            if epoch and epoch != current_epoch:
                raise HTTPException(409, "工作区已恢复，请重新获取快照")
            if cursor > revision:
                raise HTTPException(409, "同步游标已失效，请重新获取快照")
            rows = store.rows(
                "SELECT * FROM mobile_sync_rows WHERE revision>? ORDER BY revision LIMIT ?",
                (cursor, limit),
            )
            return {
                "protocol": 1,
                "epoch": current_epoch,
                "revision": revision,
                "cursor": rows[-1]["revision"] if rows else cursor,
                "more": bool(rows and rows[-1]["revision"] < revision),
                "changes": [
                    {"resource": r["resource"], "row": json.loads(r["data"]) if r["data"] else None}
                    for r in rows
                ],
            }

    @api.post("/sync")
    def push(body: Push, request: Request, user=Depends(current_user)):
        store = owned_store(request, user["id"])
        with request.app.state.store.lock, store.lock:
            refresh(store, user["id"])
            current = rows_by_key(store, user["id"])
            acknowledgements = []
            store.db.execute("BEGIN IMMEDIATE")
            try:
                for change in body.changes:
                    if change.table not in HEALTH_TABLES or not re.fullmatch(
                        r"[a-f0-9]{24}|\d{4}-\d{2}-\d{2}", change.key
                    ):
                        raise ValueError("不支持的同步资源")
                    for row in (change.base, change.row):
                        if row is not None and (
                            row.get("user_id") != user["id"]
                            or key_for(change.table, row) != change.key
                        ):
                            raise ValueError("同步记录归属或ID不符")
                    receipt = store.rows(
                        "SELECT result FROM mobile_sync_receipts WHERE id=?", (change.id,)
                    )
                    if receipt:
                        acknowledgements.append(json.loads(receipt[0]["result"]))
                        continue
                    resource = f"{change.table}/{change.key}"
                    remote = current.get(resource)
                    result, conflict = merge(change.base, change.row, remote)
                    conflict_id = None
                    if conflict:
                        conflict_id = identifier()
                        store.db.execute(
                            "INSERT INTO mobile_sync_conflicts VALUES(?,?,?,?,?)",
                            (
                                conflict_id,
                                resource,
                                encode(change.row) if change.row else None,
                                encode(remote) if remote else None,
                                time.time(),
                            ),
                        )
                    if result is None:
                        current.pop(resource, None)
                    else:
                        current[resource] = result
                    ack = {
                        "id": change.id,
                        "table": change.table,
                        "key": change.key,
                        "row": result,
                        "conflict_id": conflict_id,
                    }
                    acknowledgements.append(ack)
                    store.db.execute(
                        "INSERT INTO mobile_sync_receipts VALUES(?,?,?)",
                        (change.id, encode(ack), time.time()),
                    )
                tables = {
                    table: [
                        row for resource, row in current.items() if resource.startswith(table + "/")
                    ]
                    for table in HEALTH_TABLES
                }
                validate_rows(tables)
                # Normalize Pydantic-only calculations; clients cannot smuggle a
                # forged precise kcal through raw archive/sync rows.
                from fittrack.models import (
                    Meal,
                    Workout,
                    TrainingPlan,
                    Profile,
                    BodyRecord,
                    WorkoutTemplate,
                )

                models = {
                    "profiles": Profile,
                    "bodies": BodyRecord,
                    "workout_templates": WorkoutTemplate,
                }
                for table in HEALTH_TABLES:
                    for row in tables[table]:
                        if table in models:
                            row["data"] = encode(
                                models[table]
                                .model_validate(json.loads(row["data"]))
                                .model_dump(mode="json")
                            )
                        elif table == "entries":
                            model = {"meal": Meal, "workout": Workout, "plan": TrainingPlan}[
                                row["kind"]
                            ]
                            row["data"] = encode(
                                model.model_validate(json.loads(row["data"])).model_dump(
                                    mode="json"
                                )
                            )
                        columns = [r["name"] for r in store.rows(f"PRAGMA table_info({table})")]
                        if set(row) != set(columns):
                            raise ValueError("同步字段不符合 PC 数据合约")
                        if "data" in row and table in {"profiles", "bodies", "entries"}:
                            data = json.loads(row["data"])
                            if row["date"] != data.get("date", data.get("effective_date")):
                                raise ValueError("同步日期与记录内容不一致")
                        if table == "entries":
                            data = json.loads(row["data"])
                            if row["source_job_id"] != data.get("source_job_id") or row[
                                "plan_id"
                            ] != data.get("plan_id"):
                                raise ValueError("同步关联字段与记录内容不一致")
                    store.db.execute(f"DELETE FROM {table} WHERE user_id=?", (user["id"],))
                    for row in tables[table]:
                        columns = [r["name"] for r in store.rows(f"PRAGMA table_info({table})")]
                        store.db.execute(
                            f"INSERT INTO {table} VALUES({','.join('?' for _ in columns)})",
                            [row[k] for k in columns],
                        )
                verify_store(store, user["id"])
                # Historical stale estimates are valid backup/sync records. Do
                # not re-adopt them through save_entry, which correctly requires
                # fresh fingerprints for a new UI adoption.
                for row in tables["entries"]:
                    data = json.loads(row["data"])
                    if data.get("image_id"):
                        store.image(user["id"], data["image_id"])
                    if data.get("source_job_id"):
                        source = store.job(user["id"], data["source_job_id"])
                        if (
                            source["kind"] != "meal"
                            or source["status"] != "done"
                            or source["request"].get("image_id") != data.get("image_id")
                        ):
                            raise ValueError("识餐来源不匹配")
                    if data.get("plan_id"):
                        store.entry(user["id"], "plan", data["plan_id"])
                for row in tables["jobs"]:
                    req = json.loads(row["request"])
                    if req.get("image_id"):
                        store.image(user["id"], req["image_id"])
                store.db.execute("COMMIT")
            except Exception:
                store.db.execute("ROLLBACK")
                raise
            refresh(store, user["id"])
            # Acks use normalized values, never echo untrusted kcal.
            live = rows_by_key(store, user["id"])
            for ack in acknowledgements:
                ack["row"] = live.get(ack["table"] + "/" + ack["key"])
            return {"protocol": 1, "acknowledgements": acknowledgements}

    @api.put("/images/{sha}")
    async def put_image(sha: str, request: Request, user=Depends(current_user)):
        if not re.fullmatch("[a-f0-9]{64}", sha):
            raise ValueError("图片哈希无效")
        data = await request.body()
        if len(data) > 12 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != sha:
            raise ValueError("图片大小或哈希不符")
        store = owned_store(request, user["id"])
        with request.app.state.store.lock, store.lock:
            existing = store.rows(
                "SELECT id FROM images WHERE user_id=? AND sha=?", (user["id"], sha)
            )
            index = store.put_image(user["id"], data)
            if not existing:
                # Upload bytes first; the incoming image row carries the stable
                # device id referenced by jobs and meals in the same batch.
                store.db.execute(
                    "DELETE FROM images WHERE id=? AND user_id=?", (index["id"], user["id"])
                )
            return {"sha": sha, "stored": True}

    @api.get("/conflicts")
    def conflicts(request: Request, user=Depends(current_user)):
        store = owned_store(request, user["id"])
        with request.app.state.store.lock, store.lock:
            refresh(store, user["id"])
            return [
                {
                    **r,
                    "local": json.loads(r["local"]) if r["local"] else None,
                    "remote": json.loads(r["remote"]) if r["remote"] else None,
                }
                for r in store.rows("SELECT * FROM mobile_sync_conflicts ORDER BY created_at DESC")
            ]

    return api
