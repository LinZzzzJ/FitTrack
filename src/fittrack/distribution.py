"""Installation paths and safe process boundaries for source and portable builds."""

import ctypes
import os
import subprocess
import sys
import threading
import webbrowser
from contextlib import contextmanager
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
PROJECT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parents[2]
_LAUNCH_LOCK = threading.RLock()


def powershell():
    return str(
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )


def app_command(background=True, project=None):
    location = Path(project) if project is not None else PROJECT
    if FROZEN:
        return [str(location / Path(sys.executable).name)]
    python = location / ".venv/Scripts" / ("pythonw.exe" if background else "python.exe")
    return [str(python), "-B", "-m", "fittrack"]


def independent_environment():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if FROZEN:
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


@contextmanager
def external_program():
    """Do not pass frozen DLL search paths to Windows/system browser processes."""
    with _LAUNCH_LOCK:
        env = dict(os.environ)
        for key in list(env):
            if key.startswith("_PYI_") or key in {
                "PYTHONHOME",
                "PYTHONPATH",
                "_MEIPASS2",
                "PYINSTALLER_RESET_ENVIRONMENT",
            }:
                env.pop(key, None)
        previous_path = os.environ.get("PATH", "")
        bundle = str(getattr(sys, "_MEIPASS", ""))
        if FROZEN:
            env["PATH"] = os.pathsep.join(
                part
                for part in previous_path.split(os.pathsep)
                if part and not part.casefold().startswith(bundle.casefold())
            )
            os.environ["PATH"] = env["PATH"]
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        try:
            yield env
        finally:
            if FROZEN:
                os.environ["PATH"] = previous_path
                ctypes.windll.kernel32.SetDllDirectoryW(bundle)


def open_browser(url):
    try:
        with external_program() as env:
            if os.name == "nt":
                import winreg

                try:
                    with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
                    ) as key:
                        program = winreg.QueryValueEx(key, "ProgId")[0]
                    with winreg.OpenKey(
                        winreg.HKEY_CLASSES_ROOT, program + r"\shell\open\command"
                    ) as key:
                        command = winreg.QueryValueEx(key, "")[0]
                    # Browser registrations normally quote the full executable path.
                    executable = (
                        command.split('"', 2)[1]
                        if command.startswith('"')
                        else command.split(" ", 1)[0]
                    )
                    if (
                        Path(executable).name.casefold() in {"msedge.exe", "chrome.exe"}
                        and Path(executable).is_file()
                    ):
                        subprocess.Popen(
                            [executable, "--new-window", url],
                            env=env,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                        return True
                except OSError:
                    pass
            if webbrowser.open(url):
                return True
    except OSError:
        pass
    from fittrack.desktop import message

    message("浏览器启动调用失败。后台已运行，请手动打开：\n" + url, error=True)
    return False


def open_folder(path):
    with external_program():
        os.startfile(path)
