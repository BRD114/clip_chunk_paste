#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ClipChunkPaste —— 剪贴板分组粘贴小工具（Windows 系统托盘常驻程序）

用途
    某些平台（聊天框、验证码式输入框、单行输入框等）单次粘贴有字符上限（例如 20 个）。
    开启本工具后，正常的 Ctrl+V 会被接管：剪贴板里的长文本被切成 N 个字符一组，
    逐组写入剪贴板并依次粘贴，最后再把原始文本还原回剪贴板。

运行
    pythonw clip_chunk_paste.py        # 无控制台窗口常驻托盘
    python  clip_chunk_paste.py --debug  # 带调试日志
    python  clip_chunk_paste.py --selftest  # 只跑单元自检，不进托盘

依赖：pystray、pillow（其余全部走 ctypes 调 Win32 API）
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import threading
import time

# --------------------------------------------------------------------------- #
# 常量与配置
# --------------------------------------------------------------------------- #

APP_NAME = "ClipChunkPaste"
APP_TITLE = "剪贴板分组粘贴"
APP_ID = "ClipChunkPaste.SingleInstance.v1"

DEFAULT_CHUNK = 20
CHUNK_CHOICES = (10, 15, 20, 25, 30, 40, 50)      # 每组字符数可选值
INTERVAL_CHOICES = (20, 50, 80, 120, 200)          # 组间间隔(ms)可选值
DEFAULT_INTERVAL = 80

VK_V = 0x56
VK_CONTROL = 0x11
VK_MENU = 0x12          # Alt
VK_LWIN = 0x5B
VK_RWIN = 0x5C

WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105

LLKHF_INJECTED = 0x10
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
ERROR_ALREADY_EXISTS = 183

# --------------------------------------------------------------------------- #
# Win32 绑定
# --------------------------------------------------------------------------- #

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wt.DWORD),
        ("wParamL", wt.WORD),
        ("wParamH", wt.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.UnhookWindowsHookEx.restype = wt.BOOL
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.TranslateMessage.restype = wt.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostThreadMessageW.restype = wt.BOOL
user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wt.UINT
user32.MapVirtualKeyW.argtypes = [wt.UINT, wt.UINT]
user32.MapVirtualKeyW.restype = wt.UINT
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

user32.OpenClipboard.argtypes = [wt.HWND]
user32.OpenClipboard.restype = wt.BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wt.BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wt.BOOL
user32.IsClipboardFormatAvailable.argtypes = [wt.UINT]
user32.IsClipboardFormatAvailable.restype = wt.BOOL
user32.GetClipboardData.argtypes = [wt.UINT]
user32.GetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = [wt.UINT, ctypes.c_void_p]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.RegisterClipboardFormatW.argtypes = [wt.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wt.UINT

kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalUnlock.restype = wt.BOOL
kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
kernel32.GlobalFree.restype = ctypes.c_void_p
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HINSTANCE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = ctypes.c_void_p
kernel32.GetCurrentThreadId.restype = wt.DWORD

# --------------------------------------------------------------------------- #
# 日志
# --------------------------------------------------------------------------- #

_DEBUG = "--debug" in sys.argv
_LOG_PATH = os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME, "app.log"
)


def log(msg: str) -> None:
    """写一行日志到 %APPDATA%\\ClipChunkPaste\\app.log（--debug 时同时输出到控制台）。"""
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    try:
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    if _DEBUG and sys.stderr is not None:
        try:
            print(line, file=sys.stderr, flush=True)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# 文本分组（纯逻辑，便于自检）
# --------------------------------------------------------------------------- #

def normalize_newlines(text: str) -> str:
    """把 CRLF / CR 统一成 LF：Windows 剪贴板是 CRLF，但平台通常按 1 个字符计换行。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def split_chunks(text: str, size: int = DEFAULT_CHUNK) -> list[str]:
    """按 size 个字符一组切分；最后一组就是剩余部分，不做补位、不丢弃。"""
    if size <= 0:
        raise ValueError("分组长度必须大于 0")
    return [text[i:i + size] for i in range(0, len(text), size)]


# --------------------------------------------------------------------------- #
# 剪贴板读写（ctypes 直连，便于区分「无文本」与「被占用」）
# --------------------------------------------------------------------------- #

def _open_clipboard(retries: int = 12, delay: float = 0.02) -> bool:
    """剪贴板同一时刻只能被一个进程打开，其它程序占用时短暂重试。"""
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(delay)
    return False


def read_clipboard_text() -> tuple[str | None, str]:
    """读取剪贴板文本。

    返回 (text, reason)：
        ("...", "ok")      读取成功（可能是空串）
        (None, "notext")   剪贴板里没有文本（图片/文件/空剪贴板）
        (None, "locked")   剪贴板被其它程序占用，读不到
    """
    if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return None, "notext"
    if not _open_clipboard():
        return None, "locked"
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None, "notext"
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return "", "ok"
        try:
            return ctypes.wstring_at(ptr), "ok"
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


_ignore_formats: list[int] = []


def _ignore_formats_ids() -> list[int]:
    """让中间态的分组文本不进入 Win+V 剪贴板历史 / Office 剪贴板。"""
    if not _ignore_formats:
        for name in ("Clipboard Viewer Ignore", "ExcludeClipboardContentFromMonitorProcessing"):
            fmt = user32.RegisterClipboardFormatW(name)
            if fmt:
                _ignore_formats.append(fmt)
    return _ignore_formats


def write_clipboard_text(text: str, hide_from_history: bool = True) -> bool:
    """把字符串写入剪贴板（CF_UNICODETEXT）。"""
    data = text.encode("utf-16-le") + b"\x00\x00"
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        return False
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        kernel32.GlobalFree(handle)
        return False
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(handle)

    if not _open_clipboard():
        kernel32.GlobalFree(handle)
        return False
    try:
        if not user32.EmptyClipboard():
            kernel32.GlobalFree(handle)
            return False
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
        # 所有权已转交系统，不能再 free
        if hide_from_history:
            for fmt in _ignore_formats_ids():
                user32.SetClipboardData(fmt, None)
        return True
    finally:
        user32.CloseClipboard()


# --------------------------------------------------------------------------- #
# 按键注入：发送 Ctrl+V
# --------------------------------------------------------------------------- #

def _key_input(vk: int, keyup: bool) -> INPUT:
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if keyup else 0)
    ki = KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=ki))


def send_ctrl_v() -> bool:
    """注入一次完整的 Ctrl+V（按下再抬起，保证修饰键状态平衡）。"""
    seq = (
        _key_input(VK_CONTROL, False),
        _key_input(VK_V, False),
        _key_input(VK_V, True),
        _key_input(VK_CONTROL, True),
    )
    arr = (INPUT * len(seq))(*seq)
    sent = user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))
    if sent != len(seq):
        log(f"SendInput 失败：{sent}/{len(seq)} err={ctypes.get_last_error()}")
        return False
    return True


# --------------------------------------------------------------------------- #
# 全局键盘钩子
# --------------------------------------------------------------------------- #

class KeyboardHook:
    """低级键盘钩子：拦截用户在 Ctrl+V 上的按键，交给回调决定是否放行。

    注意：钩子回调必须尽快返回，实际粘贴工作在独立线程完成。
    """

    def __init__(self, on_ctrl_v, is_enabled):
        self._on_ctrl_v = on_ctrl_v        # callable(is_down: bool) -> None
        self._is_enabled = is_enabled      # callable() -> bool
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._hook = None
        self._proc = None
        self._ready = threading.Event()
        self._swallow_v_up = False
        self.ok = False

    # -- 生命周期 -----------------------------------------------------------
    def start(self, timeout: float = 3.0) -> bool:
        self._thread = threading.Thread(target=self._run, name="kbd-hook", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self.ok

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        self._proc = HOOKPROC(self._callback)  # 必须保持引用，否则会被 GC
        self._hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0
        )
        if not self._hook:
            log(f"SetWindowsHookEx 失败 err={ctypes.get_last_error()}")
            self._ready.set()
            return
        self.ok = True
        self._ready.set()
        log("键盘钩子已就绪")
        msg = wt.MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret in (0, -1):
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
        log("键盘钩子已卸载")

    # -- 回调 ---------------------------------------------------------------
    def _callback(self, n_code, w_param, l_param):
        if n_code == HC_ACTION:
            kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            # 我们自己注入的按键带 INJECTED 标记，直接放行，避免死循环
            if not (kb.flags & LLKHF_INJECTED) and self._is_enabled():
                if kb.vkCode == VK_V:
                    if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        if self._ctrl_active():
                            self._swallow_v_up = True
                            try:
                                self._on_ctrl_v(True)
                            except Exception as exc:  # 钩子内绝不能抛异常
                                log(f"钩子回调异常：{exc!r}")
                            return 1  # 吞掉物理 V 按下，阻止原生粘贴
                    elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                        if self._swallow_v_up:
                            self._swallow_v_up = False
                            return 1  # 一并吞掉抬起，避免状态错位
        return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

    @staticmethod
    def _ctrl_active() -> bool:
        """Ctrl 按下且未按 Alt / Win（Ctrl+Alt+V「选择性粘贴」保持原生行为）。"""
        down = lambda vk: bool(user32.GetAsyncKeyState(vk) & 0x8000)  # noqa: E731
        if not down(VK_CONTROL):
            return False
        if down(VK_MENU):
            return False
        if down(VK_LWIN) or down(VK_RWIN):
            return False
        return True


# --------------------------------------------------------------------------- #
# 粘贴引擎：一次 Ctrl+V → 若干组粘贴
# --------------------------------------------------------------------------- #

class PasteEngine:
    def __init__(self, settings, notify):
        self.settings = settings
        self.notify = notify            # callable(title, message, key=None)
        self._lock = threading.Lock()
        self._busy = False

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def on_ctrl_v(self, is_down: bool) -> None:
        """由钩子线程调用；同一时刻只允许一个粘贴任务。"""
        if not is_down:
            return
        with self._lock:
            if self._busy:
                log("上一个分组粘贴尚未结束，忽略本次触发")
                return
            self._busy = True
        threading.Thread(target=self._job, name="paste-job", daemon=True).start()

    # -- 真正干活 -----------------------------------------------------------
    def _job(self) -> None:
        chunk_size = max(1, int(self.settings.chunk))
        interval = max(0, int(self.settings.interval_ms)) / 1000.0
        modified = False
        original: str | None = None
        try:
            time.sleep(0.03)  # 等物理按键事件收尾，避免与注入的按键互相干扰

            raw, reason = read_clipboard_text()
            if raw is None:
                if reason == "locked":
                    self.notify(APP_TITLE, "剪贴板被其它程序占用，本次按普通粘贴处理", key="locked")
                else:
                    self.notify(APP_TITLE, "剪贴板里没有文本，本次按普通粘贴处理", key="notext")
                send_ctrl_v()
                return

            text = normalize_newlines(raw)
            if not text.strip():
                self.notify(APP_TITLE, "剪贴板文本为空，本次按普通粘贴处理", key="blank")
                send_ctrl_v()
                return

            chunks = split_chunks(text, chunk_size)
            if len(chunks) <= 1:
                # 不超过一组：直接走原生粘贴，不打扰剪贴板
                send_ctrl_v()
                return

            original = raw
            log(f"开始分组粘贴：{len(text)} 字符 → {len(chunks)} 组，每组 {chunk_size}")
            for index, part in enumerate(chunks):
                if not write_clipboard_text(part, self.settings.hide_from_history):
                    self.notify(APP_TITLE, "写入剪贴板失败，分组粘贴已中止", key="writefail")
                    log("write_clipboard_text 失败，中止")
                    return
                modified = True
                time.sleep(0.008)  # 让剪贴板内容稳定后再触发粘贴
                send_ctrl_v()
                if index < len(chunks) - 1 and interval > 0:
                    time.sleep(interval)
            log("分组粘贴完成")
        except Exception as exc:
            log(f"粘贴任务异常：{exc!r}")
            self.notify(APP_TITLE, f"分组粘贴出错：{exc}", key="error")
        finally:
            if modified and original is not None:
                # 还原原始剪贴板内容
                for _ in range(3):
                    if write_clipboard_text(original, self.settings.hide_from_history):
                        break
                    time.sleep(0.05)
            with self._lock:
                self._busy = False


# --------------------------------------------------------------------------- #
# 配置持久化
# --------------------------------------------------------------------------- #

class Settings:
    def __init__(self) -> None:
        self.enabled = True
        self.chunk = DEFAULT_CHUNK
        self.interval_ms = DEFAULT_INTERVAL
        self.hide_from_history = True

    @staticmethod
    def _path() -> str:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_NAME, "settings.json")

    @classmethod
    def load(cls) -> "Settings":
        obj = cls()
        try:
            with open(cls._path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            obj.enabled = bool(data.get("enabled", obj.enabled))
            chunk = int(data.get("chunk", obj.chunk))
            obj.chunk = chunk if chunk > 0 else obj.chunk
            interval = int(data.get("interval_ms", obj.interval_ms))
            obj.interval_ms = interval if interval >= 0 else obj.interval_ms
            obj.hide_from_history = bool(data.get("hide_from_history", obj.hide_from_history))
        except (OSError, ValueError, TypeError):
            pass
        return obj

    def save(self) -> None:
        try:
            path = self._path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "enabled": self.enabled,
                        "chunk": self.chunk,
                        "interval_ms": self.interval_ms,
                        "hide_from_history": self.hide_from_history,
                    },
                    fh,
                    ensure_ascii=False,
                    indent=2,
                )
        except OSError as exc:
            log(f"保存配置失败：{exc!r}")


# --------------------------------------------------------------------------- #
# 托盘
# --------------------------------------------------------------------------- #

def _menu_action(fn, value):
    """生成 pystray 认可的 (icon, item) 双参回调。

    pystray 用 __code__.co_argcount 校验回调参数个数，不能用 lambda 默认参数传值。
    """

    def action(icon, item):
        fn(value)

    return action


def _make_icon_image():
    from PIL import Image, ImageDraw


    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((5, 3, 59, 61), radius=12, fill=(37, 99, 235, 255))
    # 三条横线 = 被切分的若干组
    for y in (19, 32, 45):
        draw.rounded_rectangle((16, y - 3, 48, y + 3), radius=3, fill=(255, 255, 255, 255))
    return img


class TrayApp:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.icon = None
        self.hook: KeyboardHook | None = None
        self._note_time: dict[str, float] = {}
        self.engine = PasteEngine(settings, self.notify)

    # -- 通知（带节流，避免刷屏） -------------------------------------------
    def notify(self, title: str, message: str, key: str | None = None) -> None:
        now = time.time()
        if key:
            if now - self._note_time.get(key, 0.0) < 5.0:
                return
            self._note_time[key] = now
        log(f"[通知] {title}: {message}")
        if self.icon is not None:
            try:
                self.icon.notify(message, title)
            except Exception:
                pass

    # -- 菜单动作 -----------------------------------------------------------
    def _refresh(self) -> None:
        if self.icon is None:
            return
        state = "开" if self.settings.enabled else "关"
        self.icon.title = f"{APP_TITLE} · {state} · {self.settings.chunk} 字/组"
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def toggle_enabled(self, icon=None, item=None) -> None:
        self.settings.enabled = not self.settings.enabled
        self.settings.save()
        self.notify(
            APP_TITLE,
            f"分组粘贴已{'开启' if self.settings.enabled else '关闭'}"
            f"（{self.settings.chunk} 字符/组）",
            key="toggle",
        )
        self._refresh()

    def set_chunk(self, value: int) -> None:
        self.settings.chunk = value
        self.settings.save()
        self._refresh()

    def set_interval(self, value: int) -> None:
        self.settings.interval_ms = value
        self.settings.save()
        self._refresh()

    def toggle_history(self, icon=None, item=None) -> None:
        self.settings.hide_from_history = not self.settings.hide_from_history
        self.settings.save()
        self._refresh()

    def preview(self, icon=None, item=None) -> None:
        raw, reason = read_clipboard_text()
        if raw is None:
            msg = "剪贴板被占用，读不到内容" if reason == "locked" else "剪贴板里没有文本"
            self.notify(APP_TITLE, msg)
            return
        text = normalize_newlines(raw)
        if not text:
            self.notify(APP_TITLE, "剪贴板文本为空")
            return
        chunks = split_chunks(text, self.settings.chunk)
        head = chunks[0] if chunks else ""
        if len(head) > 15:
            head = head[:15] + "…"
        self.notify(
            APP_TITLE,
            f"{len(text)} 字符 → {len(chunks)} 组（每组 {self.settings.chunk} 字）\n首组：{head}",
        )

    def open_log(self, icon=None, item=None) -> None:
        try:
            os.startfile(os.path.dirname(_LOG_PATH))  # noqa: S606
        except Exception:
            pass

    def quit(self, icon=None, item=None) -> None:
        log("退出")
        if self.hook is not None:
            self.hook.stop()
        if self.icon is not None:
            self.icon.stop()

    # -- 菜单构建 -----------------------------------------------------------
    def _build_menu(self):
        from pystray import Menu, MenuItem

        s = self.settings
        # action 签名必须是 (icon, item)，checked 签名是 (item)
        chunk_items = [
            MenuItem(
                f"{n} 字符 / 组",
                _menu_action(self.set_chunk, n),
                checked=lambda item, n=n: s.chunk == n,
                radio=True,
            )
            for n in CHUNK_CHOICES
        ]
        interval_items = [
            MenuItem(
                f"{ms} 毫秒",
                _menu_action(self.set_interval, ms),
                checked=lambda item, ms=ms: s.interval_ms == ms,
                radio=True,
            )
            for ms in INTERVAL_CHOICES
        ]
        return Menu(
            MenuItem(
                lambda item: f"分组粘贴：{'已开启' if s.enabled else '已关闭'}",
                self.toggle_enabled,
                checked=lambda item: s.enabled,
                default=True,
            ),
            Menu.SEPARATOR,
            MenuItem("分组长度", Menu(*chunk_items)),
            MenuItem("组间间隔", Menu(*interval_items)),
            MenuItem(
                "不污染剪贴板历史",
                self.toggle_history,
                checked=lambda item: s.hide_from_history,
            ),
            Menu.SEPARATOR,
            MenuItem("查看剪贴板分组", self.preview),
            MenuItem("打开日志目录", self.open_log),
            Menu.SEPARATOR,
            MenuItem("退出", self.quit),
        )

    # -- 启动 ---------------------------------------------------------------
    def run(self) -> None:
        import pystray

        self.icon = pystray.Icon(
            APP_NAME,
            _make_icon_image(),
            f"{APP_TITLE} · {self.settings.chunk} 字/组",
            menu=self._build_menu(),
        )
        # 托盘就绪后（setup 在独立线程执行）再装钩子，避免钩子早于图标生效
        self.icon.run(setup=self._on_ready)

    def _on_ready(self, icon) -> None:
        self.hook = KeyboardHook(self.engine.on_ctrl_v, lambda: self.settings.enabled)
        if self.hook.start():
            self.notify(
                APP_TITLE,
                f"已就绪：Ctrl+V 将按 {self.settings.chunk} 字符/组 分组粘贴"
                f"（右键图标可开关或调整）",
                key="startup",
            )
        else:
            self.notify(APP_TITLE, "键盘钩子安装失败，功能不可用", key="hookfail")
        self._refresh()


# --------------------------------------------------------------------------- #
# 单实例 & 入口
# --------------------------------------------------------------------------- #

_mutex_handle = None


def ensure_single_instance() -> bool:
    global _mutex_handle
    _mutex_handle = kernel32.CreateMutexW(None, False, "Local\\" + APP_ID)
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def _selftest() -> int:
    failures = []

    def check(name, cond, extra=""):
        if cond:
            print(f"  [OK]   {name}")
        else:
            failures.append(name)
            print(f"  [FAIL] {name} {extra}")

    print("1) 分组逻辑")
    check("空串 → 0 组", split_chunks("", 20) == [])
    check("19 字 → 1 组", split_chunks("a" * 19, 20) == ["a" * 19])
    check("20 字 → 1 组", len(split_chunks("a" * 20, 20)) == 1)
    check("21 字 → 2 组，末尾 1 字", split_chunks("b" * 21, 20) == ["b" * 20, "b"])
    check("45 字 → 3 组 20/20/5",
          [len(c) for c in split_chunks("c" * 45, 20)] == [20, 20, 5])
    joined = "".join(split_chunks("混合 content 12345\n" * 7, 20))
    check("拼接可无损还原", joined == "混合 content 12345\n" * 7)
    check("非法长度抛错", _raises(lambda: split_chunks("x", 0)))

    print("2) 换行归一化")
    check("CRLF → LF", normalize_newlines("a\r\nb") == "a\nb")
    check("CR → LF", normalize_newlines("a\rb") == "a\nb")
    check("换行计 1 字符", len(normalize_newlines("a\r\nb")) == 3)

    print("3) 剪贴板读写（会临时占用剪贴板，结束后还原）")
    backup, reason = read_clipboard_text()
    ok = write_clipboard_text("分组粘贴 selftest 123", hide_from_history=True)
    check("写入成功", ok)
    got, _ = read_clipboard_text()
    check("读回一致", got == "分组粘贴 selftest 123", repr(got))
    if backup is not None:
        write_clipboard_text(backup)
        restored, _ = read_clipboard_text()
        check("原内容已还原", restored == backup)
    else:
        print("  [skip] 原剪贴板无文本，无需还原")

    print()
    if failures:
        print(f"自检失败 {len(failures)} 项：{failures}")
        return 1
    print("全部自检通过。")
    return 0


def _raises(fn) -> bool:
    try:
        fn()
    except Exception:
        return True
    return False


def _fatal(text: str) -> None:
    """pythonw 下没有控制台，异常必须落日志 + 弹窗，否则用户只会看到「双击没反应」。"""
    log(text)
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            f"{APP_TITLE} 启动失败：\n\n{text.strip()[-700:]}\n\n完整信息见日志：\n{_LOG_PATH}",
            f"{APP_TITLE} - 错误",
            0x10,
        )
    except Exception:
        pass


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()

    if not ensure_single_instance():
        # 已有实例在跑，静默退出（不重复占托盘）
        log("已有实例在运行，本次退出")
        return 0

    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        msg = "缺少依赖，请先执行：pip install pystray pillow\n或双击「安装依赖.bat」"
        log(msg)
        if sys.stderr is not None:
            print(msg, file=sys.stderr)
        ctypes.windll.user32.MessageBoxW(None, msg, APP_TITLE, 0x10)
        return 2

    settings = Settings.load()
    app = TrayApp(settings)
    log(f"启动 (python {sys.version.split()[0]}, 分组={settings.chunk}, 间隔={settings.interval_ms}ms)")
    try:
        app.run()
    except KeyboardInterrupt:
        app.quit()
    return 0


if __name__ == "__main__":
    try:
        _exit_code = main()
    except SystemExit:
        raise
    except BaseException:
        import traceback

        _fatal(traceback.format_exc())
        _exit_code = 3
    sys.exit(_exit_code)
