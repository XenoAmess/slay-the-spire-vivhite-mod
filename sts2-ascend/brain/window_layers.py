"""Small, side-effect-free Win32 helpers for the ASCEND-VISION window layer.

The game must remain the foreground window so that automated input continues to
work.  ``SetWindowPos(HWND_TOPMOST, SWP_NOACTIVATE, ...)`` is therefore used
instead of ``SetForegroundWindow`` for the viewer: it repairs the z-order
without stealing focus or keyboard/mouse input.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

from ctypes import wintypes
from lifecycle import STACK_ROOT


VIEWER_TITLE = "ASCEND-VISION"
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
GWLP_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH = 260


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


def _user32():
    """Return user32 only on Windows; callers turn failures into no-ops."""
    if os.name != "nt":
        return None
    return ctypes.windll.user32


def _hwnd(value: int) -> ctypes.c_void_p:
    return ctypes.c_void_p(int(value))


def _is_window(user32, hwnd: int) -> bool:
    fn = user32.IsWindow
    fn.argtypes = [wintypes.HWND]
    fn.restype = wintypes.BOOL
    return bool(fn(_hwnd(hwnd)))


def _normalize_executable_path(path: Path | str) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _process_image_path(pid: int) -> str | None:
    """Resolve one process image without shelling out to tasklist/PowerShell."""
    if os.name != "nt" or pid <= 0:
        return None
    try:
        kernel32 = ctypes.windll.kernel32
        open_process = kernel32.OpenProcess
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        query_image = kernel32.QueryFullProcessImageNameW
        query_image.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        query_image.restype = wintypes.BOOL
        handle = open_process(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return None
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            if not query_image(handle, 0, buffer, ctypes.byref(size)):
                return None
            return buffer.value
        finally:
            close_handle(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def process_name_running(executable_name: str) -> bool:
    """Enumerate process basenames even when an elevated image path is hidden."""
    if os.name != "nt" or not str(executable_name).strip():
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        create_snapshot = kernel32.CreateToolhelp32Snapshot
        create_snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        create_snapshot.restype = wintypes.HANDLE
        process_first = kernel32.Process32FirstW
        process_first.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        process_first.restype = wintypes.BOOL
        process_next = kernel32.Process32NextW
        process_next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        process_next.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        snapshot = create_snapshot(TH32CS_SNAPPROCESS, 0)
        if not snapshot or snapshot == ctypes.c_void_p(-1).value:
            return False
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            if not process_first(snapshot, ctypes.byref(entry)):
                return False
            expected = str(executable_name).strip().casefold()
            while True:
                if str(entry.szExeFile).casefold() == expected:
                    return True
                if not process_next(snapshot, ctypes.byref(entry)):
                    return False
        finally:
            close_handle(snapshot)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def find_window_for_executable(executable_path: Path | str) -> int | None:
    """Find a visible top-level window owned by one exact executable path."""
    user32 = _user32()
    if user32 is None:
        return None
    try:
        expected = _normalize_executable_path(executable_path)
        enum_windows = user32.EnumWindows
        enum_windows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
        enum_windows.restype = wintypes.BOOL
        get_window_pid = user32.GetWindowThreadProcessId
        get_window_pid.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        get_window_pid.restype = wintypes.DWORD
        is_visible = user32.IsWindowVisible
        is_visible.argtypes = [wintypes.HWND]
        is_visible.restype = wintypes.BOOL
    except (AttributeError, OSError, TypeError, ValueError):
        return None

    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd, _lparam):
        if not is_visible(hwnd):
            return True
        window_pid = wintypes.DWORD(0)
        get_window_pid(hwnd, ctypes.byref(window_pid))
        image = _process_image_path(int(window_pid.value))
        if image and _normalize_executable_path(image) == expected:
            found.append(int(hwnd))
            return False
        return True

    try:
        enum_windows(callback, 0)
    except (OSError, TypeError, ValueError):
        return None
    return found[0] if found else None


def is_topmost(hwnd: int) -> bool:
    """Return whether ``hwnd`` has the WS_EX_TOPMOST extended style."""
    if not hwnd:
        return False
    try:
        user32 = _user32()
        if user32 is None or not _is_window(user32, hwnd):
            return False
        fn = user32.GetWindowLongPtrW
        fn.argtypes = [wintypes.HWND, ctypes.c_int]
        fn.restype = ctypes.c_ssize_t
        return bool(int(fn(_hwnd(hwnd), GWLP_EXSTYLE)) & WS_EX_TOPMOST)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def set_topmost_no_activate(hwnd: int) -> bool:
    """Move a window to the topmost band without activating it."""
    if not hwnd:
        return False
    try:
        user32 = _user32()
        if user32 is None or not _is_window(user32, hwnd):
            return False
        fn = user32.SetWindowPos
        fn.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        fn.restype = wintypes.BOOL
        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        if not fn(_hwnd(hwnd), _hwnd(HWND_TOPMOST), 0, 0, 0, 0, flags):
            return False
        return is_topmost(hwnd)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _viewer_lock_path() -> Path:
    return STACK_ROOT / "knowledge" / "viewer.lock"


def _read_viewer_pid(lock_file: Path) -> int | None:
    try:
        pid = int(lock_file.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def find_viewer_hwnd(lock_file: Path | str | None = None) -> int | None:
    """Find the live viewer window using its PID lock and exact title.

    The lock is written by ``review_viewer.py`` only after it owns the viewer
    singleton.  Combining that PID with the exact title avoids reordering an
    unrelated window that happens to share a generic Python process name.
    """
    user32 = _user32()
    if user32 is None:
        return None
    path = Path(lock_file) if lock_file is not None else _viewer_lock_path()
    pid = _read_viewer_pid(path)
    if pid is None:
        return None

    try:
        enum_windows = user32.EnumWindows
        enum_windows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
        enum_windows.restype = wintypes.BOOL
        get_title = user32.GetWindowTextW
        get_title.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        get_title.restype = ctypes.c_int
        get_window_pid = user32.GetWindowThreadProcessId
        get_window_pid.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        get_window_pid.restype = wintypes.DWORD
        is_visible = user32.IsWindowVisible
        is_visible.argtypes = [wintypes.HWND]
        is_visible.restype = wintypes.BOOL
    except AttributeError:
        return None

    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd, _lparam):
        if not is_visible(hwnd):
            return True
        title_buffer = ctypes.create_unicode_buffer(256)
        get_title(hwnd, title_buffer, len(title_buffer))
        if title_buffer.value != VIEWER_TITLE:
            return True
        window_pid = wintypes.DWORD(0)
        get_window_pid(hwnd, ctypes.byref(window_pid))
        if int(window_pid.value) == pid:
            found.append(int(hwnd))
            return False
        return True

    try:
        enum_windows(callback, 0)
    except (OSError, TypeError, ValueError):
        return None
    return found[0] if found else None


def reassert_viewer_topmost(hwnd: int | None = None,
                            lock_file: Path | str | None = None) -> bool:
    """Repair the viewer z-order, resolving its HWND from the singleton lock.

    This intentionally never activates the window.  ``False`` means the viewer
    is not running yet or Win32 rejected the operation; callers may retry on the
    next heartbeat without affecting the game or the service stack.
    """
    target = int(hwnd) if hwnd else find_viewer_hwnd(lock_file)
    return bool(target and set_topmost_no_activate(target))
