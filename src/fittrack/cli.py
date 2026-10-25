"""Explicit-root GUI launcher. Heavy imports happen only after root setup."""

import argparse
import json
import logging
import logging.handlers
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from fittrack.distribution import (
    FROZEN,
    app_command,
    independent_environment,
    open_browser as browse,
)


def bind(host, port):
    sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return sock
    except OSError:
        sock.close()
        raise ValueError("端口已被其他程序或其他数据根目录占用；不会另开隐藏实例") from None


def local_request(url, token=None):
    headers = {"x-fittrack-management": token} if token else {}
    request = urllib.request.Request(url, data=b"{}" if token else None, headers=headers)
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


def existing(paths, stop=False, open_browser=True):
    file = paths.root / "runtime" / "service.json"
    if not file.exists():
        return False
    state = json.loads(file.read_text(encoding="utf-8"))
    try:
        current = local_request(state["url"] + "/_local/health")
    except (OSError, ValueError, urllib.error.URLError):
        return False
    if current.get("root_id") != paths.identity or current.get("instance") != state["instance"]:
        raise ValueError("运行实例与所选根目录不匹配，不会操作其他进程")
    if stop:
        try:
            local_request(state["url"] + "/_local/stop", state["token"])
        except urllib.error.HTTPError:
            raise
        except OSError:
            # A successful stop can close the connection before its reply is read.
            # Restart callers still wait for state removal and port release.
            pass
    elif open_browser:
        browse(state["url"])
    return True


def restart_existing(paths, timeout=150):
    """Drain the owned service; never kill or start over an unreleased instance."""
    file = paths.root / "runtime" / "service.json"
    if not file.exists():
        return
    original = json.loads(file.read_text(encoding="utf-8"))
    if not existing(paths, stop=True, open_browser=False):
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not file.exists():
            from urllib.parse import urlparse

            target = urlparse(original["url"])
            with socket.socket(
                socket.AF_INET6 if ":" in target.hostname else socket.AF_INET
            ) as check:
                check.settimeout(0.25)
                if check.connect_ex((target.hostname, target.port)) != 0:
                    return
        else:
            try:
                current = json.loads(file.read_text(encoding="utf-8"))
            except FileNotFoundError:
                continue
            if current["instance"] != original["instance"]:
                raise ValueError("已有另一个实例接管，请使用现有实例；未重复启动")
        time.sleep(0.25)
    raise ValueError("旧服务尚未完成退出，可能仍在处理任务；未强制终止，请稍后再次启动")


def configure_logging(paths, background):
    handler = logging.handlers.RotatingFileHandler(
        paths.root / "logs" / "fittrack.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=4,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger = logging.getLogger()
    logger.handlers[:] = [handler]
    logger.setLevel(logging.WARNING)
    if background:
        stream = open(paths.root / "logs" / "launcher.log", "a", encoding="utf-8")
        sys.stdout = sys.stderr = stream


def main():
    sys.dont_write_bytecode = True
    if "--desktop-pick" in sys.argv[1:]:
        from fittrack.desktop import picker_main

        return picker_main()
    parser = argparse.ArgumentParser(description="FitTrack · 受控数据根目录")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--mode", choices=["local", "server"], default="local")
    parser.add_argument("--background", action="store_true", default=FROZEN)
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--self-check", action="store_true", help="离线检查运行库，结果保存到指定根目录缓存"
    )
    parser.add_argument(
        "--no-shortcuts", action="store_true", help="自动验收时不改写安装目录的启动入口"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--public-url", default="")
    parser.add_argument(
        "--allow-registration", action="store_true", help="显式允许服务器新账号注册（默认关闭）"
    )
    parser.add_argument("--allowed-provider", action="append")
    parser.add_argument("--trusted-proxy", default="127.0.0.1")
    parser.add_argument("--import-legacy", type=Path)
    parser.add_argument("--legacy-env", type=Path)
    args = parser.parse_args()
    handle, hub, app, paths = None, None, None, None
    owns_service_file = False
    from fittrack.desktop import PROJECT, create_shortcuts, message, pick_directory

    try:
        from fittrack.paths import RuntimePaths, private, write_json

        if not 1 <= args.port <= 65535:
            raise ValueError("端口必须介于 1 与 65535")
        if args.restart and (args.stop or args.mode != "local" or args.data_root is None):
            raise ValueError("重启入口仅支持绑定根目录的本机模式，不能同时指定停止")
        if args.mode == "local" and args.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("本机模式仅允许监听回环地址")
        first_setup = args.data_root is None
        if first_setup:
            if args.mode == "server" or args.stop or os.name != "nt":
                raise ValueError("请使用 --data-root 明确指定数据根目录")
            selected = pick_directory()
            if not selected:
                return 0
            args.data_root = Path(selected)
        elif not args.data_root.exists():
            raise ValueError("绑定的数据根目录不存在，请连接原磁盘或重新运行首次设置入口")
        paths = RuntimePaths.initialize(args.data_root)
        paths.configure_process()
        if args.self_check:
            from fittrack.portable_check import check

            check(paths)
            return 0
        if args.restart:
            restart_existing(paths)
        if args.mode == "local" and existing(paths, args.stop, not args.no_browser):
            return 0
        if args.stop:
            raise ValueError("该根目录的 FitTrack 服务未运行")
        configure_logging(paths, args.background)
        from fittrack.config import lock_home

        handle = lock_home(paths.root / "runtime")
        from fittrack.control import WorkspaceHub
        from fittrack.credentials import CredentialStore
        from fittrack.runtime import RuntimeConfig

        runtime_config = RuntimeConfig(
            args.mode,
            args.public_url,
            args.allowed_provider or ["https://api.deepseek.com"],
            args.allow_registration,
        )
        hub = WorkspaceHub(paths)
        vault = CredentialStore(hub.control, paths, args.mode, runtime_config.providers)
        legacy = args.import_legacy
        if (
            not legacy
            and hub.control.metadata("legacy_source")
            and not hub.control.metadata("legacy_complete")
        ):
            legacy = Path(hub.control.metadata("legacy_source"))
            saved_env = hub.control.metadata("legacy_env")
            args.legacy_env = Path(saved_env) if saved_env else None
        if (
            first_setup
            and (PROJECT / "data" / "fittrack.sqlite3").exists()
            and not hub.control.rows("SELECT id FROM users")
        ):
            legacy = PROJECT / "data"
            args.legacy_env = PROJECT / ".env"
        if legacy:
            from fittrack.upgrade import import_legacy

            import_legacy(hub, vault, legacy, args.legacy_env)
        from fittrack.app import create_app
        import uvicorn

        app = create_app(hub, vault, runtime_config=runtime_config)
        sock = bind(args.host, args.port)

        class Server(uvicorn.Server):
            async def shutdown(self, sockets=None):
                app.state.bus.close()
                await super().shutdown(sockets=sockets)

        server = Server(
            uvicorn.Config(
                app,
                host=args.host,
                port=args.port,
                log_config=None,
                access_log=False,
                proxy_headers=args.mode == "server",
                forwarded_allow_ips=args.trusted_proxy,
                timeout_graceful_shutdown=3,
            )
        )
        app.state.runtime.stop_callback = lambda: setattr(server, "should_exit", True)
        url = f"http://{'[::1]' if ':' in args.host else '127.0.0.1'}:{args.port}"
        if args.mode == "local":
            write_json(
                paths.root / "runtime" / "service.json",
                {
                    "url": url,
                    "instance": app.state.runtime.instance,
                    "token": app.state.runtime.management_token,
                },
            )
            owns_service_file = True
            private(paths.root / "runtime" / "service.json")
            if args.background and not args.no_shortcuts:
                create_shortcuts(paths.root)
        if not args.no_browser and args.mode == "local":
            import threading

            def ready():
                while not server.started and not server.should_exit:
                    time.sleep(0.05)
                if server.started:
                    browse(url)

            threading.Thread(target=ready, daemon=True).start()
        if not args.background:
            print(
                f"FitTrack\n  URL: {runtime_config.public_url or url}\n  Data: {paths.root}\n  Ctrl+C to stop.",
                flush=True,
            )
        try:
            server.run(sockets=[sock])
        except KeyboardInterrupt:
            pass
    except Exception as exc:
        safe = (
            str(exc)
            if isinstance(exc, (ValueError, RuntimeError))
            else "启动或文件操作失败，请检查根目录权限与空间"
        )
        if paths:
            logging.getLogger("fittrack").error(safe)
        if args.background or os.name == "nt" and sys.stdout is None:
            message(safe, error=True)
        else:
            print(safe, file=sys.stderr)
        return 1
    finally:
        if app:
            app.state.bus.close()
            app.state.storage_ops.shutdown()
            app.state.runner.shutdown()
        if hub:
            hub.close()
        if handle and not (app and app.state.runtime.next_root):
            handle.close()
        if paths and owns_service_file:
            (paths.root / "runtime" / "service.json").unlink(missing_ok=True)
    if app and app.state.runtime.next_root:
        from fittrack.relocation import relocate_root

        try:
            logging.shutdown()
            if args.background:
                sys.stdout.close()
            new_paths = relocate_root(
                paths.root,
                app.state.runtime.next_root,
                None if args.no_shortcuts else create_shortcuts,
            )
            import subprocess

            child = subprocess.Popen(
                app_command(args.background)
                + [
                    "--data-root",
                    str(new_paths.root),
                    "--port",
                    str(args.port),
                    *(["--background"] if args.background else []),
                    *(["--no-shortcuts"] if args.no_shortcuts else []),
                    *(["--no-browser"] if args.no_browser else []),
                ],
                cwd=PROJECT,
                env=independent_environment(),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if existing(new_paths, open_browser=False):
                    break
                if child.poll() is not None:
                    raise RuntimeError("新根目录服务未能就绪")
                time.sleep(0.2)
            else:
                child.terminate()
                child.wait(timeout=10)
                raise RuntimeError("新根目录服务启动超时")
        except Exception:
            # Rebind the retained original; never leave a failed destination as the only entrypoint.
            try:
                marker = json.loads((paths.root / "fittrack-root.json").read_text(encoding="utf-8"))
                marker.pop("moved_to", None)
                write_json(paths.root / "fittrack-root.json", marker)
                if not args.no_shortcuts:
                    create_shortcuts(paths.root)
            except OSError:
                pass
            message("根目录迁移未完成，原数据已保留。请重新打开原启动入口查看日志。", error=True)
            return 1
        finally:
            if handle:
                handle.close()
    return 0
