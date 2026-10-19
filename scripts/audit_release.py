"""Verify the distributable's manifest, GUI executable, legal notices and boundaries."""

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

import pefile


def main(archive):
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert archive.with_suffix(".zip.sha256").read_text(encoding="ascii").split()[0] == digest
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        assert len(names) == len(set(names)), "Duplicate archive entries"
        assert all(name.startswith("FitTrack/") and ".." not in Path(name).parts for name in names)
        files = {name.removeprefix("FitTrack/"): zipped.read(name) for name in names}
        manifest = json.loads(files["文件清单.json"])
        assert {item["file"] for item in manifest} == set(files) - {"文件清单.json"}
        for item in manifest:
            content = files[item["file"]]
            assert len(content) == item["bytes"]
            assert hashlib.sha256(content).hexdigest() == item["sha256"]
        forbidden = []
        secrets = []
        for name, content in files.items():
            path = Path(name)
            if (
                path.name in {".env", "master.key", "service.json"}
                or path.suffix.lower() in {".sqlite3", ".sqlite", ".db", ".log", ".lnk"}
                or any(
                    part.lower() in {"node_modules", ".venv", "playwright", "tests", "backups"}
                    for part in path.parts
                )
            ):
                forbidden.append(name)
            if path.suffix in {".txt", ".json", ".html", ".js", ".css", ".pem"}:
                if re.search(
                    rb"\bsk-[a-zA-Z0-9]{28,}\b|-----BEGIN (?:RSA |EC |ENCRYPTED )?PRIVATE KEY-----",
                    content,
                ):
                    secrets.append(name)
        assert not forbidden, forbidden
        assert not secrets, "Sensitive content detected in: " + ", ".join(secrets)
        notices = files["第三方许可.txt"].decode("utf-8-sig")
        for name in (
            "CPython 3.13.16",
            "pyinstaller",
            "svelte",
            "echarts",
            "zrender",
            "@lucide/svelte",
            "tslib",
            "clsx",
            "esm-env",
            "Apache",
        ):
            assert name in notices, f"Missing notice: {name}"
        exe = pefile.PE(data=files["FitTrack.exe"])
        assert exe.FILE_HEADER.Machine == 0x8664, "Executable is not AMD64"
        assert exe.OPTIONAL_HEADER.Subsystem == 2, "Executable uses a console subsystem"
        build = json.loads(files["_internal/fittrack/build-info.json"])
        report = {
            "archive": archive.name,
            "sha256": digest,
            "version": build["version"],
            "build_id": build["build_id"],
            "python": build["python"],
            "pyinstaller": build["pyinstaller"],
            "zip_bytes": archive.stat().st_size,
            "unpacked_bytes": sum(len(content) for content in files.values()),
            "files": len(files),
            "manifest_verified": True,
            "sensitive_file_scan": "passed",
            "executable": "AMD64 Windows GUI, unsigned",
            "largest_components": [
                {"file": name, "bytes": len(content)}
                for name, content in sorted(
                    files.items(), key=lambda pair: len(pair[1]), reverse=True
                )[:12]
            ],
        }
    (archive.parent / "发布核验.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    main(parser.parse_args().archive.resolve())
