import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import Field

from fittrack.desktop import choose_from_service
from fittrack.models import Model
from fittrack.routes import admin_user, current_user
from fittrack.runtime import storage_view
from fittrack.storage_ops import MAX_ARCHIVE
from fittrack.store import identifier


class Location(Model):
    path: str = Field(min_length=1, max_length=2000)


class BackupChoice(Model):
    backup_id: str


def management_router():
    api = APIRouter(prefix="/api")

    def local(request):
        if request.app.state.runtime.config.mode != "local":
            raise HTTPException(404, "此操作仅限本机版本")

    @api.get("/runtime")
    def runtime(request: Request, user=Depends(current_user)):
        return request.app.state.runtime.config.capabilities(user)

    @api.get("/storage")
    def storage(request: Request, user=Depends(current_user)):
        state = request.app.state
        return storage_view(state.store, user["id"], state.runtime.config.mode) | {
            "operations": state.storage_ops.recent(user["id"])
        }

    @api.post("/storage/pick-directory")
    def pick(request: Request, user=Depends(current_user)):
        local(request)
        path = choose_from_service(request.app.state.store.paths.root)
        return {"path": path}

    @api.post("/storage/migrate", status_code=202)
    def migrate(body: Location, request: Request, user=Depends(current_user)):
        local(request)
        state, uid = request.app.state, user["id"]
        # Canonicalize absolute input too; the same root-only guard applies.
        relative = (
            state.store.paths.workspace(body.path).relative_to(state.store.paths.root).as_posix()
        )
        state.storage_ops._target(uid, relative)
        return state.storage_ops.submit(
            uid,
            "workspace-migration",
            lambda progress: state.storage_ops.migrate(uid, relative, progress),
        )

    @api.get("/storage/operations/{oid}")
    def operation(oid: str, request: Request, user=Depends(current_user)):
        return request.app.state.storage_ops.get(user["id"], oid)

    @api.post("/storage/open")
    def open_folder(body: Location, request: Request, user=Depends(current_user)):
        import os
        from fittrack.distribution import open_folder as show_folder

        local(request)
        hub, uid = request.app.state.store, user["id"]
        allowed = {"workspace": hub.for_user(uid).home, "backups": hub.paths.root / "backups" / uid}
        if user["is_admin"]:
            allowed.update({"root": hub.paths.root, "logs": hub.paths.root / "logs"})
        if body.path not in allowed or os.name != "nt":
            raise ValueError("不允许打开此目录")
        path = allowed[body.path]
        path.mkdir(parents=True, exist_ok=True)
        show_folder(path)
        return {"opened": True}

    @api.get("/backups")
    def backups(request: Request, user=Depends(current_user)):
        return request.app.state.storage_ops.backups(user["id"])

    @api.post("/backups", status_code=202)
    def backup(request: Request, user=Depends(current_user)):
        ops, uid = request.app.state.storage_ops, user["id"]
        return ops.submit(uid, "backup", lambda progress: ops.backup(uid, progress))

    @api.post("/backups/restore", status_code=202)
    def restore(body: BackupChoice, request: Request, user=Depends(current_user)):
        ops, uid = request.app.state.storage_ops, user["id"]
        source = ops.backup_path(uid, body.backup_id)
        return ops.submit(uid, "restore", lambda progress: ops.restore(uid, source, progress))

    @api.post("/backups/import", status_code=202)
    async def import_backup(
        request: Request, file: UploadFile = File(), user=Depends(current_user)
    ):
        state, uid = request.app.state, user["id"]
        temp = state.store.paths.root / "tmp" / (identifier() + ".zip")
        size = 0
        try:
            with temp.open("xb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_ARCHIVE:
                        raise ValueError("备份导入不能超过 512 MiB")
                    output.write(chunk)

            def work(progress):
                try:
                    return state.storage_ops.restore(uid, temp, progress)
                finally:
                    temp.unlink(missing_ok=True)

            return state.storage_ops.submit(uid, "import", work)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

    @api.get("/backups/{bid}/download")
    def download(bid: str, request: Request, user=Depends(current_user)):
        if request.app.state.runtime.config.mode != "server":
            raise HTTPException(404, "本机备份已保存在根目录，请使用打开备份目录")
        path = request.app.state.storage_ops.backup_path(user["id"], bid)
        return FileResponse(path, filename=path.name, media_type="application/zip")

    @api.post("/local/stop")
    def stop(request: Request, user=Depends(admin_user)):
        local(request)
        state = request.app.state
        if state.storage_ops._active:
            raise ValueError("请等待数据操作结束后再停止")
        state.store.frozen = True
        state.runtime.stop()
        return {"stopping": True}

    @api.post("/local/root-migration", status_code=202)
    def root_migration(body: Location, request: Request, user=Depends(admin_user)):
        from fittrack.relocation import validate_target

        local(request)
        state = request.app.state
        if state.runtime.stop_callback is None:
            raise ValueError("当前运行器不支持根目录迁移")
        with state.store.lock:
            if state.storage_ops._active or state.store.pending():
                raise ValueError("请等待全部 AI 和数据操作完成后迁移根目录")
            target = validate_target(state.store.paths.root, Path(body.path))
            state.store.frozen = True
            state.runtime.next_root = target
            state.runtime.stop()
        return {
            "restarting": True,
            "message": "服务将停止并核验迁移，完成后自动打开网页；原根目录保留",
        }

    return api


def local_router():
    api = APIRouter(prefix="/_local")

    def check(request, token=None):
        state = request.app.state
        if state.runtime.config.mode != "local" or request.client.host not in {
            "127.0.0.1",
            "::1",
            "testclient",
        }:
            raise HTTPException(404)
        if token is not None and not secrets.compare_digest(token, state.runtime.management_token):
            raise HTTPException(403)
        return state

    @api.get("/health")
    def health(request: Request):
        state = check(request)
        return {
            "app": "fittrack",
            "root_id": state.store.paths.identity,
            "instance": state.runtime.instance,
        }

    @api.post("/stop")
    def stop(request: Request):
        token = request.headers.get("x-fittrack-management", "")
        state = check(request, token)
        if state.storage_ops._active:
            raise ValueError("请等待数据操作结束")
        state.store.frozen = True
        state.runtime.stop()
        return {"stopping": True}

    return api
