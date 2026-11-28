import base64
from contextlib import closing
import ctypes
from ctypes import wintypes
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import unquote, urlsplit

from PIL import Image, ImageGrab
from image_formats import IMAGE_SUFFIXES


SETTINGS_PATH = Path(os.environ["LOCALAPPDATA"]) / "TuYi" / "settings.dat"
MAX_CLIPBOARD_BYTES = 128 * 1024 * 1024


class Blob(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect(data, encrypt):
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel.LocalFree.restype = ctypes.c_void_p
    operation = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    operation.argtypes = (ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob))
    operation.restype = wintypes.BOOL
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, destination = Blob(len(data), buffer), Blob()
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(destination.data, destination.length)
    finally:
        kernel.LocalFree(destination.data)


def load_settings(path=None):
    path = SETTINGS_PATH if path is None else path
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        return {}
    settings = json.loads(protect(payload, False).decode("utf-8"))
    if not isinstance(settings, dict):
        raise ValueError("invalid settings")
    return settings


def save_settings(settings, path=None):
    path = SETTINGS_PATH if path is None else path
    payload = protect(json.dumps(settings, ensure_ascii=False).encode("utf-8"), True)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


class ClipboardImageHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            source = dict(attrs).get("src")
            if source:
                self.sources.append(source)


def image_reference(value):
    value = value.strip().strip('"')
    if value.lower().startswith("data:image/"):
        header, separator, payload = value.partition(",")
        if separator and header.lower().endswith(";base64") and len(payload) < MAX_CLIPBOARD_BYTES:
            return Image.open(io.BytesIO(base64.b64decode(payload)))
    if len(value) > 1024 or "\n" in value or "\r" in value:
        return None
    if value.lower().startswith("file:"):
        parts = urlsplit(value)
        if parts.netloc not in ("", "localhost"):
            return None
        value = unquote(parts.path).lstrip("/")
    if len(value) >= 3 and value[0].isalpha() and value[1] == ":" and value[2] in "/\\":
        path = Path(value)
        if path.suffix.lower() in IMAGE_SUFFIXES and path.is_file():
            return [str(path)]
    return None


def copy_clipboard_text(text, window):
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user.OpenClipboard.argtypes, user.OpenClipboard.restype = (wintypes.HWND,), wintypes.BOOL
    user.CloseClipboard.argtypes, user.CloseClipboard.restype = (), wintypes.BOOL
    user.EmptyClipboard.argtypes, user.EmptyClipboard.restype = (), wintypes.BOOL
    user.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
    user.SetClipboardData.restype = wintypes.HANDLE
    kernel.GlobalAlloc.argtypes, kernel.GlobalAlloc.restype = (wintypes.UINT, ctypes.c_size_t), wintypes.HGLOBAL
    kernel.GlobalLock.argtypes, kernel.GlobalLock.restype = (wintypes.HGLOBAL,), ctypes.c_void_p
    kernel.GlobalUnlock.argtypes, kernel.GlobalUnlock.restype = (wintypes.HGLOBAL,), wintypes.BOOL
    kernel.GlobalFree.argtypes, kernel.GlobalFree.restype = (wintypes.HGLOBAL,), wintypes.HGLOBAL
    data = text.encode("utf-16-le") + b"\0\0"
    handle = kernel.GlobalAlloc(2, len(data))  # GMEM_MOVEABLE
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        pointer = kernel.GlobalLock(handle)
        if not pointer:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ctypes.memmove(pointer, data, len(data))
        finally:
            kernel.GlobalUnlock(handle)
        open_clipboard(user, window)
        try:
            if not user.EmptyClipboard() or not user.SetClipboardData(13, handle):  # CF_UNICODETEXT
                raise ctypes.WinError(ctypes.get_last_error())
            handle = None  # Windows now owns the allocation.
        finally:
            user.CloseClipboard()
    finally:
        if handle:
            kernel.GlobalFree(handle)


def open_clipboard(user, window=None):
    for attempt in range(5):
        if user.OpenClipboard(window):
            return
        if attempt == 4:
            raise ctypes.WinError(ctypes.get_last_error())
        time.sleep(.035)


def native_clipboard():
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user.OpenClipboard.argtypes, user.OpenClipboard.restype = (wintypes.HWND,), wintypes.BOOL
    user.CloseClipboard.argtypes, user.CloseClipboard.restype = (), wintypes.BOOL
    user.RegisterClipboardFormatW.argtypes, user.RegisterClipboardFormatW.restype = (wintypes.LPCWSTR,), wintypes.UINT
    user.GetClipboardData.argtypes, user.GetClipboardData.restype = (wintypes.UINT,), wintypes.HANDLE
    kernel.GlobalSize.argtypes, kernel.GlobalSize.restype = (wintypes.HGLOBAL,), ctypes.c_size_t
    kernel.GlobalLock.argtypes, kernel.GlobalLock.restype = (wintypes.HGLOBAL,), ctypes.c_void_p
    kernel.GlobalUnlock.argtypes, kernel.GlobalUnlock.restype = (wintypes.HGLOBAL,), wintypes.BOOL
    targets = [(user.RegisterClipboardFormatW(name), "image") for name in (
        "PNG", "image/png", "JFIF", "JPEG", "image/jpeg", "WebP", "image/webp")]
    targets.extend(((17, "dib"), (8, "dib"), (user.RegisterClipboardFormatW("HTML Format"), "html"),
                    (13, "text")))
    open_clipboard(user)
    try:
        for identifier, kind in targets:
            handle = user.GetClipboardData(identifier)
            if not handle:
                continue
            length = kernel.GlobalSize(handle)
            limit = 8 * 1024 * 1024 if kind in ("text", "html") else MAX_CLIPBOARD_BYTES
            if not 0 < length <= limit:
                continue
            pointer = kernel.GlobalLock(handle)
            if not pointer:
                continue
            try:
                yield kind, ctypes.string_at(pointer, length)
            finally:
                kernel.GlobalUnlock(handle)
    finally:
        user.CloseClipboard()


def clipboard_image():
    failure = None
    try:
        item = ImageGrab.grabclipboard()
        if isinstance(item, Image.Image):
            item.load()
            return item
        if isinstance(item, list) and item:
            return item
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        failure = error

    from PIL.BmpImagePlugin import DibImageFile
    with closing(native_clipboard()) as formats:
        for kind, data in formats:
            try:
                if kind in ("image", "dib"):
                    stream = io.BytesIO(data)
                    item = Image.open(stream) if kind == "image" else DibImageFile(stream)
                    item.load()
                    return item
                if kind == "html":
                    html = ClipboardImageHTML()
                    html.feed(data.decode("utf-8", "replace").rstrip("\0"))
                    if len(html.sources) != 1:
                        continue
                    reference = html.sources[0]
                else:
                    reference = data.decode("utf-16-le").split("\0", 1)[0]
                item = image_reference(reference)
                if item is not None:
                    return item
            except (OSError, ValueError, Image.DecompressionBombError) as error:
                failure = error
    if failure:
        raise failure
    return None
