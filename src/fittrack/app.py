import asyncio
import mimetypes
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import HTTPConnection
from starlette.middleware.cors import CORSMiddleware

from fittrack.mobile_auth import NATIVE_ORIGINS, PairingLimiter

from fittrack.events import EventBus
from fittrack.jobs import JobRunner
from fittrack.routes import router
from fittrack.version import API_REVISION, APP_VERSION, BuildInfo

STATIC = Path(__file__).parent / "static"
LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})


class Guard:
    def __init__(self, app, allowed_hosts, development=True, public_url="", build_info=None):
        self.app, self.allowed_hosts = app, allowed_hosts
        self.development, self.public_url = development, public_url
        self.build_info = build_info

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        connection = HTTPConnection(scope)
        hostname = connection.url.hostname
        if hostname not in self.allowed_hosts:
            return await JSONResponse({"detail": "不允许的访问地址"}, status_code=403)(
                scope, receive, send
            )
        path = connection.url.path
        if (
            scope["method"] not in {"GET", "HEAD", "OPTIONS"}
            and path.startswith("/api/")
            and not path.startswith(("/api/auth/", "/api/local/"))
        ):
            revision = connection.headers.get("x-fittrack-api")
            if (
                revision not in {None, str(API_REVISION)}
                or self.build_info
                and self.build_info.public()["restart_required"]
            ):
                return await JSONResponse(
                    {
                        "detail": "后台版本已变化，请使用重启 FitTrack 入口后刷新网页；当前表单尚未提交"
                    },
                    status_code=409,
                )(scope, receive, send)
        origin = connection.headers.get("origin")
        if origin:
            same = origin.rstrip("/") == f"{connection.url.scheme}://{connection.url.netloc}"
            development = self.development and origin in {
                "http://127.0.0.1:5173",
                "http://localhost:5173",
            }
            if self.public_url and origin.rstrip("/") != self.public_url:
                same = False
            native_origin = origin in NATIVE_ORIGINS and not same
            if (
                native_origin
                and path not in {"/api/mobile/pair/redeem", "/api/version", "/api/exercise-catalog"}
                and not connection.headers.get("authorization", "").startswith("Bearer ")
            ):
                return await JSONResponse({"detail": "移动来源必须使用设备令牌"}, status_code=403)(
                    scope, receive, send
                )
            if not same and not development and not native_origin:
                return await JSONResponse({"detail": "请求来源不允许"}, status_code=403)(
                    scope, receive, send
                )
            if urlparse(origin).hostname not in self.allowed_hosts:
                return await JSONResponse({"detail": "请求来源不允许"}, status_code=403)(
                    scope, receive, send
                )
        limit = (513 if connection.url.path == "/api/backups/import" else 13) * 1024 * 1024
        length = connection.headers.get("content-length", "0")
        if length.isdigit() and int(length) > limit:
            return await JSONResponse({"detail": "上传图片不能超过 12 MB"}, status_code=413)(
                scope, receive, send
            )
        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > limit:
                raise HTTPException(413, "上传图片不能超过 12 MB")
            return message

        async def protected_send(message):
            if message["type"] == "http.response.start" and connection.url.path.startswith("/api/"):
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"cache-control"
                ]
                headers.append((b"cache-control", b"private, no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, limited_receive, protected_send)


def create_app(store, settings, *, ai=None, allowed_hosts=None, runtime_config=None):
    managed = hasattr(store, "paths")
    runtime = None
    storage_ops = None
    if managed:
        from fittrack.credentials import CredentialStore
        from fittrack.runtime import RuntimeConfig, RuntimeState
        from fittrack.storage_ops import StorageOperations

        if not isinstance(settings, CredentialStore):
            raise ValueError("受控根目录必须使用每账号独立的凭据管理")
        runtime = RuntimeState(runtime_config or RuntimeConfig())
        store.secure_cookies = runtime.config.mode == "server"
        if store.secure_cookies and not store.control.rows("SELECT id FROM users LIMIT 1"):
            raise ValueError("请先在本机模式初始化管理员账号，再启动服务器模式")
        storage_ops = StorageOperations(store, mode=runtime.config.mode)
    bus = EventBus()
    if storage_ops:
        storage_ops.bus = bus
    runner = JobRunner(store, settings, bus, ai)
    store.recover_jobs()

    @asynccontextmanager
    async def lifespan(app):
        bus.bind(asyncio.get_running_loop())

        async def purge():
            while True:
                await asyncio.sleep(30)
                settings.purge_expired()

        maintenance = asyncio.create_task(purge()) if managed else None
        try:
            yield
        finally:
            if maintenance:
                maintenance.cancel()
                try:
                    await maintenance
                except asyncio.CancelledError:
                    pass
            bus.close()
            if storage_ops:
                storage_ops.shutdown()
            runner.shutdown()

    app = FastAPI(
        title="FitTrack",
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.build_info = BuildInfo()
    app.state.pairing_limiter = PairingLimiter()
    app.state.auth_limiter = PairingLimiter("登录尝试过于频繁，请稍后再试")
    app.state.store, app.state.settings, app.state.bus, app.state.runner = (
        store,
        settings,
        bus,
        runner,
    )
    if managed:
        app.state.runtime, app.state.storage_ops = runtime, storage_ops
    app.add_middleware(
        Guard,
        allowed_hosts=allowed_hosts or (runtime.config.allowed_hosts if runtime else LOOPBACK),
        development=not runtime or runtime.config.mode == "local",
        public_url=runtime.config.public_url if runtime else "",
        build_info=app.state.build_info,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["capacitor://localhost", "http://localhost", "https://localhost"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Fittrack-Api"],
        expose_headers=["Content-Type"],
    )

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": "记录不存在或不属于当前用户"}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(sqlite3.IntegrityError)
    async def conflict(request, exc):
        return JSONResponse({"detail": "记录发生冲突，请刷新后重试"}, status_code=409)

    @app.exception_handler(RequestValidationError)
    async def validation(request, exc):
        fields = list(
            dict.fromkeys(
                ".".join(str(part) for part in error["loc"][1:]) for error in exc.errors()
            )
        )
        return JSONResponse({"detail": "请检查字段：" + "、".join(fields)}, status_code=422)

    app.include_router(router())
    from fittrack.mobile_sync import router as mobile_sync_router

    app.include_router(mobile_sync_router())
    if managed:
        from fittrack.management_routes import local_router, management_router

        app.include_router(management_router())
        app.include_router(local_router())
    # Windows registry can identify .js as text/plain; browser ES modules require JS MIME.
    # This is also enforced by BrushGraft's original local static server (MIT).
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/javascript", ".mjs")
    mimetypes.add_type("text/css", ".css")
    if (STATIC / "index.html").exists():
        app.mount("/", StaticFiles(directory=STATIC, html=True), name="web")
    else:

        @app.get("/")
        def setup():
            return HTMLResponse("<h1>FitTrack</h1><p>请运行 scripts/setup.ps1 构建界面。</p>")

    return app
