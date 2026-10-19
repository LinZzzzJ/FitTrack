"""Build and assemble the standalone Windows ZIP using an explicit build root."""

import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fittrack.version import APP_VERSION, source_fingerprint  # noqa: E402


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assemble(build, output):
    bundle = build / "dist/FitTrack"
    for filename in ("先读我.txt", "首次使用指南.html", "发布说明.txt"):
        if filename.endswith(".txt"):
            (bundle / filename).write_text(
                (ROOT / "release-docs" / filename).read_text(encoding="utf-8"), encoding="utf-8-sig"
            )
        else:
            shutil.copyfile(ROOT / "release-docs" / filename, bundle / filename)
    shutil.copyfile(ROOT / "LICENSE", bundle / "LICENSE.txt")
    notices = []
    runtime_names = [
        line.split("==")[0]
        for line in (ROOT / "requirements-runtime.lock").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    for name in runtime_names + ["pyinstaller"]:
        dist = metadata.distribution(name)
        notices.append(f"\n{'=' * 60}\n{name} {dist.version}\n")
        for item in dist.files or []:
            if "license" in str(item).lower() or "copying" in str(item).lower():
                location = dist.locate_file(item)
                if location.is_file() and location.stat().st_size < 400000:
                    notices.append(location.read_text(encoding="utf-8", errors="replace"))
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        notices += ["\nCPython 3.13.16\n", python_license.read_text(encoding="utf-8")]
    # These libraries contribute code to the compiled frontend, even though Node
    # itself and the build tools are intentionally absent from the distribution.
    for name in ("svelte", "@lucide/svelte", "echarts", "zrender", "tslib", "clsx", "esm-env"):
        package = ROOT / "web/node_modules" / name
        version = json.loads((package / "package.json").read_text(encoding="utf-8"))["version"]
        notices.append(f"\n{'=' * 60}\n{name} {version} (frontend)\n")
        legal_files = [
            item
            for item in package.iterdir()
            if item.is_file() and item.name.lower().startswith(("license", "notice", "copyright"))
        ]
        if not legal_files:
            raise ValueError(f"Missing frontend license: {name}")
        for item in sorted(legal_files):
            notices.append(item.name + "\n" + item.read_text(encoding="utf-8"))
    (bundle / "第三方许可.txt").write_text("\n".join(notices), encoding="utf-8-sig")
    files = [path for path in bundle.rglob("*") if path.is_file() and path.name != "文件清单.json"]
    manifest = [
        {
            "file": path.relative_to(bundle).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha(path),
        }
        for path in sorted(files)
    ]
    (bundle / "文件清单.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    output.mkdir(parents=True, exist_ok=True)
    for filename in ("先读我.txt", "首次使用指南.html", "发布说明.txt"):
        shutil.copyfile(bundle / filename, output / filename)
    archive = output / f"FitTrack-v{APP_VERSION}-windows-x64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                zipped.write(path, "FitTrack/" + path.relative_to(bundle).as_posix())
    (output / (archive.name + ".sha256")).write_text(
        sha(archive) + "  " + archive.name + "\n", encoding="ascii"
    )
    size = {
        "zip_bytes": archive.stat().st_size,
        "unpacked_bytes": sum(p.stat().st_size for p in bundle.rglob("*") if p.is_file()),
        "files": len(manifest) + 1,
        "unsigned": True,
    }
    (output / "体积报告.json").write_text(json.dumps(size, indent=2), encoding="utf-8")
    print(json.dumps({"archive": str(archive), **size}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assemble-only", action="store_true")
    args = parser.parse_args()
    if not args.build_root.is_absolute() or not args.output.is_absolute():
        raise ValueError("Build and output directories must be absolute")
    build = args.build_root.resolve()
    meta = build / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    (build / "tmp").mkdir(exist_ok=True)
    env = dict(
        os.environ,
        PYTHONDONTWRITEBYTECODE="1",
        PYINSTALLER_CONFIG_DIR=str(build / "pyinstaller-cache"),
        FITTRACK_BUILD_META=str(meta),
    )
    for name in ("TMP", "TEMP", "TMPDIR"):
        env[name] = str(build / "tmp")
    if not args.assemble_only:
        frontend = {
            p.relative_to(ROOT / "src/fittrack/static").as_posix(): sha(p)
            for p in (ROOT / "src/fittrack/static").rglob("*")
            if p.is_file()
        }
        info = {
            "version": APP_VERSION,
            "backend_sha256": source_fingerprint(),
            "frontend": frontend,
            "python": "3.13.16",
            "pyinstaller": "6.22.3",
            "packaging": {
                name: sha(ROOT / name)
                for name in (
                    "tools/portable.spec",
                    "tools/portable_entry.py",
                    "tools/hooks/hook-PIL.Image.py",
                    "requirements-runtime.lock",
                    "requirements-build.lock",
                )
            },
        }
        info["build_id"] = hashlib.sha256(json.dumps(info, sort_keys=True).encode()).hexdigest()[
            :20
        ]
        (meta / "build-info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        numeric = ", ".join(APP_VERSION.split(".") + ["0"])
        (meta / "windows-version.txt").write_text(
            f"VSVersionInfo(ffi=FixedFileInfo(filevers=({numeric}),prodvers=({numeric}),mask=0x3f,flags=0,OS=0x40004,fileType=1,subtype=0,date=(0,0)),kids=[StringFileInfo([StringTable('040904B0',[StringStruct('FileDescription','FitTrack Local Fitness Diary'),StringStruct('ProductName','FitTrack'),StringStruct('FileVersion','{APP_VERSION}'),StringStruct('ProductVersion','{APP_VERSION}'),StringStruct('OriginalFilename','FitTrack.exe')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])",
            encoding="utf-8",
        )
        subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--distpath",
                str(build / "dist"),
                "--workpath",
                str(build / "work"),
                str(ROOT / "tools/portable.spec"),
            ],
            env=env,
            cwd=ROOT,
            check=True,
        )
    assemble(build, args.output)


if __name__ == "__main__":
    main()
