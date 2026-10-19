"""Explicit, offline environment check; writes only to the chosen data root."""

import io
import ssl
import sqlite3
import sys
from pathlib import Path

import certifi
import pydantic_core
import _cffi_backend
from cryptography.fernet import Fernet
from PIL import Image, _imaging
from pwdlib import PasswordHash

from fittrack.paths import write_json
from fittrack.version import BuildInfo


def check(paths):
    password = PasswordHash.recommended()
    assert password.verify("offline-check", password.hash("offline-check"))
    cipher = Fernet(Fernet.generate_key())
    assert cipher.decrypt(cipher.encrypt(b"offline-check")) == b"offline-check"
    ssl.create_default_context(cafile=certifi.where())
    connection = sqlite3.connect(":memory:")
    assert connection.execute("SELECT 1").fetchone()[0] == 1
    connection.close()
    formats = []
    for format_name in ("JPEG", "PNG", "WEBP", "GIF"):
        data = io.BytesIO()
        Image.new("RGB", (20, 30), "green").save(data, format_name)
        with Image.open(io.BytesIO(data.getvalue())) as image:
            image.load()
            assert image.size == (20, 30)
        formats.append(format_name)
    modules = [_cffi_backend, _imaging, pydantic_core]
    result = {
        "version": BuildInfo().public(),
        "python": sys.version,
        "executable": sys.executable,
        "password_hash": True,
        "encryption": True,
        "tls_certificates": True,
        "sqlite": True,
        "image_formats": formats,
        "module_locations": [str(Path(module.__file__).resolve()) for module in modules],
    }
    write_json(paths.root / "caches/portable-check.json", result)
    return result
