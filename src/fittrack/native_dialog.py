"""Windows IFileOpenDialog folder picker, using only the system shell."""

import ctypes
from ctypes import wintypes
from pathlib import Path
from uuid import UUID


def pick_directory(initial=None):
    ole = ctypes.OleDLL("ole32")
    shell = ctypes.WinDLL("shell32")

    def guid(value):
        return (ctypes.c_ubyte * 16).from_buffer_copy(UUID(value).bytes_le)

    result = ole.CoInitializeEx(None, 2)  # Each picker runs on its own STA thread/process.
    if result < 0:
        raise OSError("无法初始化 Windows 目录选择窗口")
    dialog = ctypes.c_void_p()
    folder = ctypes.c_void_p()
    selected = ctypes.c_void_p()

    def invoke(pointer, index, signature, *values):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *signature)(table[index])(
            pointer, *values
        )

    def check(code):
        if code < 0:
            raise OSError("Windows 目录选择窗口调用失败")

    try:
        clsid = guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")
        iid = guid("D57C7288-D4AD-4768-BE02-9D969532D960")
        ole.CoCreateInstance.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        check(
            ole.CoCreateInstance(
                ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(dialog)
            )
        )
        check(invoke(dialog, 9, [wintypes.DWORD], 0x20 | 0x40 | 0x800 | 0x8))
        check(invoke(dialog, 17, [wintypes.LPCWSTR], "选择 FitTrack 专用数据目录"))
        if initial and Path(initial).is_dir():
            shell_iid = guid("43826D1E-E718-42EE-BC55-A1E261C37BFE")
            shell.SHCreateItemFromParsingName.argtypes = [
                wintypes.LPCWSTR,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            shell.SHCreateItemFromParsingName.restype = ctypes.c_long
            if (
                shell.SHCreateItemFromParsingName(
                    str(initial), None, ctypes.byref(shell_iid), ctypes.byref(folder)
                )
                >= 0
            ):
                check(invoke(dialog, 12, [ctypes.c_void_p], folder))
        shown = invoke(dialog, 3, [wintypes.HWND], None)
        if shown & 0xFFFFFFFF == 0x800704C7:
            return None
        check(shown)
        check(invoke(dialog, 20, [ctypes.c_void_p], ctypes.byref(selected)))
        text = ctypes.c_void_p()
        check(
            invoke(selected, 5, [wintypes.DWORD, ctypes.c_void_p], 0x80058000, ctypes.byref(text))
        )
        try:
            return ctypes.wstring_at(text)
        finally:
            ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
            ole.CoTaskMemFree(text)
    finally:
        for pointer in (selected, folder, dialog):
            if pointer:
                invoke(pointer, 2, [])
        ole.CoUninitialize()
