import secrets
from dataclasses import dataclass, field
from urllib.parse import urlparse
import json

from fittrack.paths import AREAS
from fittrack.storage_ops import tree_bytes


@dataclass
class RuntimeConfig:
    mode: str = "local"
    public_url: str = ""
    providers: list[str] = field(default_factory=lambda: ["https://api.deepseek.com"])
    allow_registration: bool = False

    def __post_init__(self):
        if self.mode not in {"local", "server"}:
            raise ValueError("运行模式必须为 local 或 server")
        if self.mode == "server":
            url = urlparse(self.public_url)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.path not in {"", "/"}
                or url.query
                or url.fragment
            ):
                raise ValueError("服务器模式必须指定有效的 HTTPS 对外地址")
            self.public_url = self.public_url.rstrip("/")

    @property
    def allowed_hosts(self):
        hosts = {"localhost", "127.0.0.1", "::1"}
        if self.public_url:
            hosts.add(urlparse(self.public_url).hostname)
        return frozenset(hosts)

    def capabilities(self, user):
        local = self.mode == "local"
        return {
            "mode": self.mode,
            "choose_directory": local,
            "open_directory": local,
            "migrate_workspace": local,
            "migrate_root": local and user["is_admin"],
            "stop_service": local and user["is_admin"],
            "allowed_providers": self.providers if not local else [],
        }


class RuntimeState:
    def __init__(self, config):
        self.config = config
        self.instance = secrets.token_hex(16)
        self.management_token = secrets.token_urlsafe(32)
        self.stop_callback = None
        self.next_root = None

    def stop(self):
        if self.stop_callback is None:
            raise ValueError("当前运行器不支持通过网页停止服务")
        self.stop_callback()


def storage_view(hub, uid, mode):
    root = hub.paths.root
    current = hub.for_user(uid)
    relative = current.home.relative_to(root).as_posix()
    labels = {
        "control": "账号库与加密凭据",
        "secrets": "主加密密钥",
        "records": "默认健康工作区",
        "logs": "脱敏运行日志",
        "tmp": "临时文件与迁移暂存",
        "caches": "可重建缓存",
        "backups": "个人健康备份",
        "runtime": "实例状态与管理操作",
    }
    areas = [
        {
            "name": key,
            "label": labels[key],
            "path": str(root / key) if mode == "local" else key,
            "bytes": tree_bytes(root / key)
            if key not in {"records", "backups"}
            else tree_bytes(current.home if key == "records" else root / "backups" / uid),
        }
        for key in AREAS
    ]
    legacy = hub.control.metadata("legacy_paths", [])
    relocation = root / "runtime" / "relocated-from.json"
    if relocation.is_file():
        legacy = legacy + [json.loads(relocation.read_text(encoding="utf-8"))["source"]]
    return {
        "root": str(root) if mode == "local" else "服务器受控数据根目录",
        "workspace": str(current.home) if mode == "local" else relative,
        "workspace_relative": relative,
        "workspace_bytes": tree_bytes(current.home),
        "account_db": str(root / "control" / "accounts.sqlite3")
        if mode == "local"
        else "control/accounts.sqlite3",
        "key_file": str(root / "secrets" / "master.key")
        if mode == "local"
        else "secrets/master.key",
        "areas": areas,
        "archives": hub.control.metadata("archives:" + uid, []),
        "legacy_paths": legacy if mode == "local" and hub.user(uid)["is_admin"] else [],
    }
