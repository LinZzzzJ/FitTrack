import json
import os
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from fittrack import desktop, distribution, version
from fittrack.paths import RuntimePaths


def test_frozen_command_does_not_depend_on_development_python(tmp_path, monkeypatch):
    monkeypatch.setattr(distribution, "FROZEN", True)
    monkeypatch.setattr(distribution.sys, "executable", str(tmp_path / "FitTrack.exe"))
    assert distribution.app_command(project=tmp_path) == [str(tmp_path / "FitTrack.exe")]
    assert distribution.independent_environment()["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_external_launch_restores_dll_and_path_even_on_error(tmp_path, monkeypatch):
    bundle = tmp_path / "_internal"
    system = str(tmp_path / "system-bin")
    original = str(bundle) + os.pathsep + system
    calls = []
    monkeypatch.setattr(distribution, "FROZEN", True)
    monkeypatch.setattr(distribution.sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("PATH", original)
    monkeypatch.setenv("PYTHONPATH", "developer-only")
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "parent-archive")
    monkeypatch.setattr(distribution.ctypes.windll.kernel32, "SetDllDirectoryW", calls.append)
    with pytest.raises(RuntimeError), distribution.external_program() as env:
        assert env["PATH"] == system
        assert "PYTHONPATH" not in env and "_PYI_ARCHIVE_FILE" not in env
        raise RuntimeError("launch failed")
    assert calls == [None, str(bundle)]
    assert os.environ["PATH"] == original


def test_portable_version_identity_changes_with_manifest(tmp_path, monkeypatch):
    folder = tmp_path / "fittrack"
    folder.mkdir()
    manifest = folder / "build-info.json"
    manifest.write_text(json.dumps({"build_id": "first-build"}))
    monkeypatch.setattr(version, "FROZEN", True)
    monkeypatch.setattr(version, "__file__", str(folder / "version.py"))
    build = version.BuildInfo()
    info = build.public()
    assert info["distribution"] == "portable" and info["build_id"] == "first-build"
    assert not info["restart_required"]
    manifest.write_text(json.dumps({"build_id": "second-build"}))
    assert build.public()["restart_required"]


def test_picker_result_must_stay_in_root_tmp(tmp_path, monkeypatch):
    paths = RuntimePaths.initialize(tmp_path / "root")
    monkeypatch.setattr(
        desktop.sys,
        "argv",
        [
            "FitTrack",
            "--desktop-pick",
            "--initial",
            str(paths.root),
            "--output",
            str(tmp_path / "outside.json"),
        ],
    )
    monkeypatch.setattr(
        desktop, "pick_directory", lambda *args: pytest.fail("must reject before opening picker")
    )
    with pytest.raises(ValueError, match="临时"):
        desktop.picker_main()
    assert not (tmp_path / "outside.json").exists()


def test_no_console_picker_cancel_returns_null_inside_root(tmp_path, monkeypatch):
    paths = RuntimePaths.initialize(tmp_path / "root with spaces")
    result = paths.root / "tmp/result.json"
    monkeypatch.setattr(
        desktop.sys,
        "argv",
        ["FitTrack", "--desktop-pick", "--initial", str(paths.root), "--output", str(result)],
    )
    monkeypatch.setattr(desktop, "pick_directory", lambda *args: None)
    assert desktop.picker_main() == 0
    assert json.loads(result.read_text())["path"] is None


def test_service_picker_cleans_result_file_and_uses_no_stdout(tmp_path, monkeypatch):
    paths = RuntimePaths.initialize(tmp_path / "root")
    results = []

    def run(command, **kwargs):
        assert "--desktop-pick" in command
        result = Path(command[-1])
        assert result.parent == paths.root / "tmp"
        result.write_text(json.dumps({"path": None}))
        results.append(result)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(desktop.subprocess, "run", run)
    assert desktop.choose_from_service(paths.root) is None
    assert results and all(not result.exists() for result in results)


def test_frozen_shortcuts_target_exe_not_python(tmp_path, monkeypatch):
    exe = tmp_path / "FitTrack.exe"
    exe.touch()
    monkeypatch.setattr(distribution, "FROZEN", True)
    monkeypatch.setattr(distribution.sys, "executable", str(exe))
    calls = []
    monkeypatch.setattr(desktop.subprocess, "run", lambda *args, **kwargs: calls.append(args[0]))
    desktop.create_shortcuts(tmp_path / "records", project=tmp_path)
    import base64

    script = base64.b64decode(calls[0][-1]).decode("utf-16-le")
    assert "FitTrack.exe" in script and "pythonw.exe" not in script and "-m fittrack" not in script
    assert "--stop" in script and "--restart" in script and "--data-root" in script


@pytest.mark.parametrize("name", ["msedge.exe", "chrome.exe"])
def test_registered_browser_requests_explicit_new_window(tmp_path, monkeypatch, name):
    import winreg

    exe = tmp_path / name
    exe.touch()
    monkeypatch.setattr(winreg, "OpenKey", lambda hive, path: nullcontext(path))
    monkeypatch.setattr(
        winreg,
        "QueryValueEx",
        lambda key, value: (
            "TestBrowser" if value == "ProgId" else f'"{exe}" --single-argument %1',
            1,
        ),
    )
    calls = []
    monkeypatch.setattr(
        distribution.subprocess, "Popen", lambda args, **kwargs: calls.append((args, kwargs))
    )
    monkeypatch.setattr(
        distribution.webbrowser,
        "open",
        lambda *args: pytest.fail("registered browser must request a new window"),
    )
    assert distribution.open_browser("http://127.0.0.1:8788")
    assert calls[0][0] == [str(exe), "--new-window", "http://127.0.0.1:8788"]
    assert "PYTHONPATH" not in calls[0][1]["env"]
