"""Windows GUI integration, with no console or AppData/registry locator writes."""

import argparse
import base64
import json
import os
import subprocess
import sys
import secrets
from pathlib import Path

from fittrack.distribution import (
    PROJECT,
    app_command,
    external_program,
    independent_environment,
    powershell,
)


def message(text, error=False):
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "FitTrack · 轻衡", 0x10 if error else 0x40)
    else:
        print(text, file=sys.stderr if error else sys.stdout)


def pick_directory(initial=None):
    from fittrack.native_dialog import pick_directory as native_pick

    return native_pick(initial)


def choose_from_service(initial):
    if os.name != "nt":
        raise ValueError("目录选择器仅适用于本机 Windows；可填写根目录内的相对路径")
    from fittrack.paths import read_json

    result_file = Path(initial) / "tmp" / ("directory-" + secrets.token_hex(12) + ".json")
    try:
        result = subprocess.run(
            app_command()
            + ["--desktop-pick", "--initial", str(initial), "--output", str(result_file)],
            cwd=PROJECT,
            env=independent_environment(),
            timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            raise ValueError("未能打开文件夹选择窗口，可手动填写路径")
        return read_json(result_file)["path"]
    finally:
        result_file.unlink(missing_ok=True)


def picker_main():
    from fittrack.paths import write_json

    parser = argparse.ArgumentParser()
    parser.add_argument("--desktop-pick", action="store_true")
    parser.add_argument("--initial", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.initial.resolve()
    output = args.output.resolve()
    if (
        not root.is_absolute()
        or output.parent != root / "tmp"
        or not (root / "fittrack-root.json").is_file()
    ):
        raise ValueError("目录选择结果必须写入指定根目录的临时区域")
    write_json(output, {"path": pick_directory(root)})
    return 0


def create_shortcuts(root=None, project=PROJECT):
    if os.name != "nt":
        return
    command = app_command(project=project)
    python = Path(command[0])
    if not python.exists():
        raise ValueError("程序入口缺失，请完整解压发布包或安装开发依赖")
    unbound = command[1:] + ["--background"]
    shortcuts = [("首次设置 FitTrack.lnk", list(unbound))]
    if root or not (project / "启动 FitTrack.lnk").exists():
        shortcuts.append(("启动 FitTrack.lnk", list(unbound)))
    if root:
        shortcuts[-1][1].extend(["--data-root", str(root)])
        shortcuts.append(("停止 FitTrack.lnk", command[1:] + ["--data-root", str(root), "--stop"]))
        shortcuts.append(
            (
                "重启 FitTrack.lnk",
                command[1:] + ["--background", "--data-root", str(root), "--restart"],
            )
        )

    def quoted(value):
        return "'" + str(value).replace("'", "''") + "'"

    lines = [
        "$ErrorActionPreference='Stop'",
        "$ProgressPreference='SilentlyContinue'",
        "$shell=New-Object -ComObject WScript.Shell",
    ]
    for name, args in shortcuts:
        lines += [
            f"$link=$shell.CreateShortcut({quoted(project / name)})",
            f"$link.TargetPath={quoted(python)}",
            f"$link.Arguments={quoted(subprocess.list2cmdline(args))}",
            f"$link.WorkingDirectory={quoted(project)}",
            "$link.WindowStyle=7",
            "$link.Save()",
        ]
    encoded = base64.b64encode("\n".join(lines).encode("utf-16-le")).decode()
    with external_program() as env:
        subprocess.run(
            [powershell(), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            check=True,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["pick", "shortcuts"])
    parser.add_argument("--initial", type=Path)
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()
    if args.action == "pick":
        print(json.dumps({"path": pick_directory(args.initial)}, ensure_ascii=False))
    else:
        create_shortcuts(args.data_root)


if __name__ == "__main__":
    main()
