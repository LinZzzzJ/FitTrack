# Build using the isolated official CPython interpreter, never the development Conda.
import os
from pathlib import Path

root = Path(SPECPATH).parent
meta = Path(os.environ["FITTRACK_BUILD_META"])
a = Analysis(
    [str(root / "tools/portable_entry.py")],
    pathex=[str(root / "src")],
    hookspath=[str(root / "tools/hooks")],
    binaries=[],
    datas=[(str(root / "src/fittrack/static"), "fittrack/static"),
           (str(meta / "build-info.json"), "fittrack")],
    hiddenimports=["uvicorn.logging", "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl",
                   "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on", "uvicorn.lifespan.off",
                   "anyio._backends._asyncio", "PIL.JpegImagePlugin", "PIL.PngImagePlugin",
                   "PIL.WebPImagePlugin", "PIL.GifImagePlugin", "_cffi_backend"],
    excludes=["tkinter", "pytest", "playwright", "pip", "setuptools", "numpy", "pandas",
              "scipy", "IPython", "matplotlib", "test", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="FitTrack", console=False,
          debug=False, strip=False, upx=False, uac_admin=False, version=str(meta / "windows-version.txt"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="FitTrack")
