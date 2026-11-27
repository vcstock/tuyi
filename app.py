from datetime import datetime
from io import BytesIO
import os
from pathlib import Path
from time import perf_counter
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlsplit
import webbrowser

from PIL import Image, ImageOps, ImageTk
import requests

from translation import (API_PROVIDERS, LANGUAGES, NETWORKS, OCR_MODES, PROTOCOLS, PROVIDERS, WEB_PROVIDERS,
                         codex_path, downloads_folder, ocr_backend, parse_web_translation, proxy_address, recognize,
                         repaint, start_login, translate, translation_prompt)
from image_formats import EXPORT_FORMATS, IMAGE_LIMIT, IMAGE_SUFFIXES, export_image, open_image
from windows_support import clipboard_image, load_settings, save_settings

BG = "#ecf1f4"
WHITE = "#ffffff"
INK = "#152635"
MUTED = "#506675"
LINE = "#cddae3"
NAVY = "#142f42"
TEAL = "#006e65"
FONT = "Microsoft YaHei UI"


class Preview(tk.Frame):
    def __init__(self, parent, title, empty):
        super().__init__(parent, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
        header = tk.Frame(self, bg=WHITE, padx=16, pady=10)
        header.pack(fill="x")
        tk.Label(header, text=title, font=(FONT, 11, "bold"), bg=WHITE, fg=INK).pack(side="left")
        self.meta = tk.Label(header, bg=WHITE, fg=MUTED, font=(FONT, 9))
        self.meta.pack(side="right")
        self.canvas = tk.Canvas(self, bg="#f5f8fa", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=9, pady=(0, 9))
        self.image = None
        self.photo = None
        self.empty = empty
        self.canvas.bind("<Configure>", self.draw)

    def set(self, image):
        self.image = image
        self.meta.configure(text=f"{image.width} × {image.height} px" if image else "")
        self.draw()

    def draw(self, _event=None):
        self.canvas.delete("all")
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if self.image is None:
            self.photo = None
            self.canvas.create_text(width // 2, height // 2, text=self.empty, fill=MUTED,
                                    font=(FONT, 10), justify="center", width=max(1, width - 24))
        else:
            if width <= 16 or height <= 16:
                return
            scale = min((width - 16) / self.image.width, (height - 16) / self.image.height)
            dimensions = tuple(max(1, round(axis * scale)) for axis in self.image.size)
            preview = self.image.resize(dimensions, Image.Resampling.LANCZOS)
            self.photo = ImageTk.PhotoImage(preview)
            self.canvas.create_image(width // 2, height // 2, image=self.photo)


class App:
    def __init__(self, root):
        self.root = root
        root.title("图译 · AI 图片翻译")
        root.geometry("1080x720")
        root.minsize(855, 530)
        root.configure(bg=BG)
        root.option_add("*Font", (FONT, 10))
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TCombobox", padding=4, fieldbackground=WHITE, background=BG, foreground=INK)
        style.map("TCombobox", fieldbackground=[("readonly", WHITE)],
                  selectbackground=[("readonly", WHITE)], selectforeground=[("readonly", INK)])
        self.provider = tk.StringVar(value=PROVIDERS[0])
        self.language = tk.StringVar(value="简体中文")
        self.network = tk.StringVar(value=NETWORKS[0])
        self.export_format = tk.StringVar(value="PNG")
        self.jpg_quality = tk.StringVar(value="92%")
        self.ocr_mode = tk.StringVar(value=OCR_MODES[0])
        self.keys = {name: tk.StringVar() for name in API_PROVIDERS}
        self.models = {name: tk.StringVar() for name in API_PROVIDERS}
        self.protocol = tk.StringVar(value=PROTOCOLS[0])
        self.host = tk.StringVar()
        self.port = tk.StringVar()
        self.scale = tk.StringVar(value="100%")
        self.text_scale = tk.StringVar(value="100%")
        self.export_info = tk.StringVar()
        self.export_revision = 0
        self.export_timer = None
        self.render_inputs = None
        self.original_visible = True
        self.events = queue.Queue()
        self.image = self.result = None
        self.generation = 0
        self.busy = False
        self.source = "clipboard"
        self.filename = ""
        self.settings_error = False
        try:
            settings = load_settings()
            if settings.get("provider") in PROVIDERS:
                self.provider.set(settings["provider"])
            if settings.get("network") in NETWORKS:
                self.network.set(settings["network"])
            if settings.get("ocr_mode") in OCR_MODES:
                self.ocr_mode.set(settings["ocr_mode"])
            if settings.get("jpg_quality") in {"80%", "85%", "90%", "92%", "95%", "98%"}:
                self.jpg_quality.set(settings["jpg_quality"])
            address = settings.get("address", "")
            if address:
                parsed = urlsplit(address if "://" in address else "http://" + address)
                if parsed.scheme in PROTOCOLS and parsed.hostname:
                    self.protocol.set(parsed.scheme)
                    auth, _, _ = parsed.netloc.rpartition("@")
                    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
                    self.host.set(f"{auth}@{host}" if auth else host)
                    self.port.set(parsed.port or {"http": 80, "https": 443}.get(parsed.scheme, 1080))
            keys = settings.get("keys", {})
            for provider, variable in self.keys.items():
                variable.set(keys.get(provider, ""))
                self.models[provider].set(settings.get("models", {}).get(provider, ""))
        except (OSError, ValueError, AttributeError, TypeError):
            self.settings_error = True

        hero = tk.Frame(root, bg=NAVY, padx=24, pady=14)
        hero.pack(fill="x")
        tk.Label(hero, text="图译", font=(FONT, 23, "bold"), bg=NAVY, fg=WHITE).pack(side="left")
        tk.Label(hero, text="AI 图片翻译", font=(FONT, 11), bg=NAVY, fg="#bfe7e8").pack(side="left", padx=14)
        self.settings_button = self.button(hero, "设置  ▾", self.toggle_settings)
        self.settings_button.pack(side="right")
        tk.Label(hero, text="Ctrl + V  粘贴图片", font=(FONT, 10), bg=NAVY,
                 fg="#d3e5ef").pack(side="right", padx=12)

        self.settings = config = tk.Frame(root, bg=WHITE, padx=16, pady=7,
                                          highlightthickness=1, highlightbackground=LINE)
        config.columnconfigure(3, weight=1)
        for row, label, variable, values in [
            (0, "翻译服务", self.provider, PROVIDERS),
            (2, "网络连接", self.network, NETWORKS),
        ]:
            tk.Label(config, text=label, bg=WHITE, fg=INK).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
            select = ttk.Combobox(config, textvariable=variable, values=values, state="readonly", width=14)
            select.grid(row=row, column=1, sticky="ew", pady=4)
            select.bind("<<ComboboxSelected>>", self.sync_settings)

        self.key_label = tk.Label(config, text="API Key", bg=WHITE, fg=INK)
        self.key_label.grid(row=0, column=2, sticky="w", padx=(16, 8))
        self.key_entry = ttk.Entry(config, show="•")
        self.key_entry.grid(row=0, column=3, sticky="ew")
        self.login_row = tk.Frame(config, bg=WHITE)
        self.login_row.grid(row=0, column=3, columnspan=3, sticky="w")
        self.login_button = self.button(self.login_row, "打开登录页", self.login)
        self.login_button.pack(side="left")
        self.login_note = tk.Label(self.login_row, bg=WHITE, fg=MUTED)
        self.login_note.pack(side="left", padx=7)
        self.model_label = tk.Label(config, text="模型 / 接入点", bg=WHITE, fg=INK)
        self.model_label.grid(row=1, column=2, sticky="w", padx=(16, 8))
        self.model_row = tk.Frame(config, bg=WHITE)
        self.model_row.grid(row=1, column=3, sticky="ew")
        self.model_entry = ttk.Entry(self.model_row, width=25)
        self.model_entry.pack(side="left")
        self.model_note = tk.Label(self.model_row, bg=WHITE, fg=MUTED)
        self.model_note.pack(side="left", padx=8)
        self.network_note = tk.Label(config, bg=WHITE, fg=MUTED, anchor="w")
        self.network_note.grid(row=2, column=3, sticky="ew")
        self.proxy_row = tk.Frame(config, bg=WHITE)
        self.proxy_row.grid(row=2, column=2, columnspan=2, sticky="w", padx=(16, 0))
        for label, variable, width in [("协议", self.protocol, 8), ("主机", self.host, 19), ("端口", self.port, 6)]:
            tk.Label(self.proxy_row, text=label, bg=WHITE, fg=INK).pack(side="left", padx=(0, 5))
            if variable is self.protocol:
                control = ttk.Combobox(self.proxy_row, textvariable=variable, values=PROTOCOLS,
                                       state="readonly", width=width)
            else:
                control = ttk.Entry(self.proxy_row, textvariable=variable, width=width)
            control.pack(side="left", padx=(0, 8))
        tk.Label(config, text="OCR 加速", fg=INK, bg=WHITE).grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(config, textvariable=self.ocr_mode, values=OCR_MODES, state="readonly", width=14).grid(
            row=3, column=1, sticky="ew", pady=4)
        self.button(config, "保存设置", self.persist_settings, primary=True).grid(
            row=3, column=3, sticky="e", pady=(5, 2))

        self.toolbar = toolbar = tk.Frame(root, bg=BG)
        toolbar.pack(fill="x", padx=22, pady=12)
        self.button(toolbar, "选择图片", self.pick).pack(side="left")
        self.button(toolbar, "粘贴图片", self.paste).pack(side="left", padx=7)
        tk.Label(toolbar, text="译为", bg=BG, fg=INK).pack(side="left", padx=(9, 5))
        languages = ttk.Combobox(toolbar, textvariable=self.language, values=tuple(LANGUAGES), state="readonly", width=12)
        languages.pack(side="left")
        languages.bind("<<ComboboxSelected>>", self.change_language)
        self.translate_button = self.button(toolbar, "开始翻译", self.start, primary=True)
        self.translate_button.pack(side="left", padx=8)
        self.save_button = self.button(toolbar, "保存译图", self.save, primary=True)
        self.save_button.pack(side="right")
        formats = ttk.Combobox(toolbar, textvariable=self.export_format, values=tuple(EXPORT_FORMATS),
                               state="readonly", width=6)
        formats.pack(side="right", padx=(0, 7))
        tk.Label(toolbar, text="格式", bg=BG, fg=INK).pack(side="right", padx=(4, 5))
        ttk.Combobox(toolbar, textvariable=self.scale, width=6,
                     values=("100%", "90%", "80%", "70%", "60%", "50%", "40%", "30%", "25%", "20%", "10%", "150%", "200%")
                     ).pack(side="right", padx=(0, 7))
        tk.Label(toolbar, text="缩放", bg=BG, fg=INK).pack(side="right", padx=(4, 5))

        self.content = content = tk.PanedWindow(root, orient="horizontal", bg=BG, borderwidth=0,
                                               sashwidth=9, opaqueresize=True)
        content.pack(fill="both", expand=True, padx=22)
        self.before = Preview(content, "原图", "选择文件或按 Ctrl + V 粘贴图片")
        self.after = Preview(content, "译图", "翻译完成后在这里预览")
        for pane in (self.before, self.after):
            content.add(pane, minsize=210, width=507, stretch="always")

        image_controls = tk.Frame(root, bg=BG)
        image_controls.pack(fill="x", padx=22, pady=(6, 0))
        self.original_button = self.button(image_controls, "收起原图", self.toggle_original)
        self.original_button.pack(side="left")
        tk.Label(image_controls, text="译文字号", fg=INK, bg=BG).pack(side="left", padx=(12, 5))
        text_size = ttk.Combobox(image_controls, textvariable=self.text_scale, width=6,
                                 values=("50%", "60%", "70%", "80%", "90%", "100%", "110%", "125%", "150%", "200%"))
        text_size.pack(side="left")
        text_size.bind("<<ComboboxSelected>>", self.restyle)
        text_size.bind("<Return>", self.restyle)
        self.restyle_button = self.button(image_controls, "应用字号", self.restyle)
        self.restyle_button.pack(side="left", padx=6)
        self.quality_controls = tk.Frame(image_controls, bg=BG)
        tk.Label(self.quality_controls, text="JPG 画质", fg=INK, bg=BG).pack(side="left", padx=(7, 4))
        ttk.Combobox(self.quality_controls, textvariable=self.jpg_quality,
                     values=("80%", "85%", "90%", "92%", "95%", "98%"), state="readonly", width=5).pack(side="left")
        tk.Label(image_controls, textvariable=self.export_info, fg=MUTED, bg=BG, anchor="e").pack(
            side="right", fill="x", expand=True)
        self.scale.trace_add("write", self.queue_export_info)
        self.export_format.trace_add("write", self.change_export_format)
        self.jpg_quality.trace_add("write", self.queue_export_info)

        terms = tk.Frame(root, bg=BG)
        terms.pack(fill="x", padx=22, pady=(8, 0))
        tk.Label(terms, text="术语与翻译要求", fg=INK, bg=BG).pack(anchor="w")
        tk.Label(terms, text="例如 ROI → 投资回报率，品牌名保留原文；修改后点击「开始翻译」应用。",
                 fg=MUTED, bg=BG).pack(anchor="w")
        self.instructions = tk.Text(terms, height=2, wrap="word", padx=6, pady=4, fg=INK,
                                    bg=WHITE, highlightthickness=1, highlightbackground=LINE, relief="flat")
        self.instructions.pack(fill="x", pady=(3, 0))

        self.status = tk.StringVar(value="之前的设置无法读取，可在「设置」中重新保存。"
                                   if self.settings_error else "支持 PNG、JPG、WebP、SVG、SVGZ 等图片")
        tk.Label(root, textvariable=self.status, bg=BG, fg=MUTED, anchor="w", padx=22, pady=8).pack(fill="x")
        banner = tk.Frame(root, bg="#d8e8ed")
        banner.pack(fill="x")
        link = tk.Button(banner, text="研究报告 · 企业管理报告 · 论文资料", fg=NAVY, bg="#d8e8ed",
                         activebackground="#c3dae2", cursor="hand2", relief="flat", bd=0,
                         font=(FONT, 9, "underline"), pady=5,
                         command=lambda: webbrowser.open("https://hy.chnmc.com/"))
        link.pack()
        root.bind("<Control-KeyPress-v>", self.shortcut)
        root.bind("<Control-KeyPress-V>", self.shortcut)
        self.sync_settings()
        self.refresh_buttons()
        root.after(60, self.poll)

    @staticmethod
    def button(parent, text, command, primary=False):
        return tk.Button(parent, text=text, command=command, bg=TEAL if primary else WHITE,
                         fg=WHITE if primary else INK, activebackground="#005850" if primary else "#dce9ee",
                         activeforeground=WHITE if primary else INK, disabledforeground="#889ba5",
                         padx=12, pady=4, bd=0, relief="flat", cursor="hand2", highlightthickness=1,
                         highlightbackground=TEAL if primary else LINE, highlightcolor=TEAL)

    def sync_settings(self, _event=None):
        provider = self.provider.get()
        login = provider not in API_PROVIDERS
        for widget in (self.key_entry, self.key_label, self.model_row, self.model_label):
            widget.grid_remove() if login else widget.grid()
        if login:
            self.login_row.grid()
            self.login_button.configure(text="登录 ChatGPT" if provider == PROVIDERS[1] else "打开官网登录")
            self.login_note.configure(text="使用已登录的 ChatGPT 账号" if provider == PROVIDERS[1]
                                      else "网页登录后，在浏览器和图译之间复制提示词与译文")
        else:
            self.login_row.grid_remove()
            self.key_entry.configure(textvariable=self.keys[provider])
            self.model_entry.configure(textvariable=self.models[provider])
            default = API_PROVIDERS[provider][1]
            self.model_note.configure(text=f"留空使用 {default}" if default else "填写模型 ID 或 ep- 开头的接入点 ID")
        manual = self.network.get() == NETWORKS[2]
        self.proxy_row.grid() if manual else self.proxy_row.grid_remove()
        if manual:
            self.network_note.grid_remove()
        else:
            self.network_note.grid()
            self.network_note.configure(text="沿用 Windows 或环境变量代理设置" if self.network.get() == NETWORKS[0]
                                        else "不使用代理")

    def toggle_settings(self):
        self.show_settings(not self.settings.winfo_manager())

    def show_settings(self, visible):
        if visible:
            self.settings.pack(fill="x", padx=22, pady=(14, 0), before=self.toolbar)
        else:
            focus = self.root.focus_get()
            if focus and str(focus).startswith(str(self.settings) + "."):
                self.settings_button.focus_set()
            self.settings.pack_forget()
        self.settings_button.configure(text="设置  ▴" if visible else "设置  ▾")

    def persist_settings(self):
        try:
            address = self.selected_proxy()
            save_settings({
                "provider": self.provider.get(),
                "network": self.network.get(),
                "ocr_mode": self.ocr_mode.get(),
                "jpg_quality": self.jpg_quality.get(),
                "address": address,
                "models": {name: value.get().strip() for name, value in self.models.items()},
                "keys": {name: value.get().strip() for name, value in self.keys.items()},
            })
        except ValueError as error:
            self.status.set(str(error))
            return
        except OSError:
            self.status.set("无法保存设置。请检查当前 Windows 用户目录的权限。")
            return
        self.show_settings(False)
        self.status.set("设置已保存。")
        if self.image is not None and self.result is None and not self.busy:
            self.maybe_start()

    def refresh_buttons(self):
        self.save_button.configure(state="normal" if self.result is not None else "disabled")
        self.translate_button.configure(state="normal" if self.image is not None and not self.busy else "disabled")
        self.original_button.configure(state="normal" if self.image is not None else "disabled")
        self.restyle_button.configure(state="normal" if self.render_inputs is not None and not self.busy else "disabled")

    def login(self):
        provider = self.provider.get()
        if provider in WEB_PROVIDERS:
            webbrowser.open(WEB_PROVIDERS[provider])
            return
        try:
            if self.busy:
                return
            start_login(self.network.get(), self.selected_proxy())
            self.status.set("请在浏览器完成 ChatGPT 登录，然后点击「开始翻译」。")
        except (OSError, ValueError) as error:
            self.status.set(str(error))

    def shortcut(self, event):
        if isinstance(event.widget, tk.Text) or (isinstance(event.widget, ttk.Entry) and (
                not isinstance(event.widget, ttk.Combobox) or event.widget.cget("state") != "readonly")):
            return
        self.paste()
        return "break"

    def selected_proxy(self):
        host, port = self.host.get().strip(), self.port.get().strip()
        mode = self.network.get()
        if not host and mode != NETWORKS[2]:
            return ""
        if mode == NETWORKS[2] and (not host or not port.isascii() or not port.isdecimal()
                                    or not 1 <= int(port) <= 65535):
            raise ValueError("请填写代理主机及 1–65535 之间的端口。")
        if any(char in host for char in "/?#\\") or any(char.isspace() for char in host):
            raise ValueError("代理主机应填写 IP 或域名。协议和端口请分别填写。")
        address = f"{self.protocol.get()}://{host}:{port}" if host and port else ""
        if mode == NETWORKS[2]:
            proxy_address(mode, address)
            try:
                if urlsplit(address).port != int(port):
                    raise ValueError()
            except ValueError:
                raise ValueError("请检查代理主机和端口。IPv6 主机须用方括号括起来。") from None
        return address

    def pick(self):
        path = filedialog.askopenfilename(filetypes=[
            ("图片文件", " ".join("*" + suffix for suffix in sorted(IMAGE_SUFFIXES))),
            ("所有文件", "*"),
        ])
        if path:
            self.open_file(path)

    def open_file(self, path):
        try:
            with open_image(Path(path)) as image:
                self.import_image(image, Path(path).stem)
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
            self.status.set("无法打开此图片。请检查文件格式或重新选图。")

    def paste(self):
        try:
            item = clipboard_image()
            if isinstance(item, Image.Image):
                self.import_image(item, "clipboard")
            elif isinstance(item, list):
                path = next((file for file in item if Path(file).suffix.lower() in IMAGE_SUFFIXES), None)
                if path:
                    self.open_file(path)
                else:
                    self.status.set("剪贴板中没有可打开的图片文件。")
            else:
                self.status.set("剪贴板中没有图片。请使用浏览器的「复制图片」，或用 Win + Shift + S 截图后再粘贴。")
        except (OSError, ValueError, Image.DecompressionBombError):
            self.status.set("无法读取剪贴板图片。请重新复制或使用「选择图片」。")

    def import_image(self, image, name):
        if image.width * image.height > 30_000_000:
            self.status.set("图片超过 3000 万像素，请缩小后再导入。")
            return
        self.generation += 1
        self.image = ImageOps.exif_transpose(image).convert("RGBA")
        self.source = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:85] or "image"
        self.before.set(self.image)
        self.clear_result()
        self.maybe_start()

    def change_language(self, _event=None):
        if self.image:
            self.generation += 1
            self.clear_result()
            self.maybe_start()

    def clear_result(self):
        self.result = None
        self.render_inputs = None
        self.after.set(None)
        self.queue_export_info()
        self.refresh_buttons()

    def toggle_original(self):
        if self.original_visible:
            self.content.forget(self.before)
        else:
            self.content.add(self.before, before=self.after, minsize=210, width=507, stretch="always")
        self.original_visible = not self.original_visible
        self.original_button.configure(text="收起原图" if self.original_visible else "显示原图")

    @staticmethod
    def percent(text, minimum, maximum):
        value = text.strip().removesuffix("%").strip()
        if value.isascii() and value.isdecimal() and minimum <= int(value) <= maximum:
            return int(value)
        raise ValueError(f"请输入 {minimum}% 到 {maximum}% 之间的整数比例。")

    def queue_export_info(self, *_):
        self.export_revision += 1
        if self.export_timer is not None:
            self.root.after_cancel(self.export_timer)
            self.export_timer = None
        if self.result is None:
            self.export_info.set("")
            return
        try:
            percent = self.percent(self.scale.get(), 1, 400)
        except ValueError:
            self.export_info.set("图片缩放支持 1%–400%")
            return
        image, name, revision = self.result, self.export_format.get(), self.export_revision
        quality = int(self.jpg_quality.get().removesuffix("%"))
        width, height = (max(1, round(edge * percent / 100)) for edge in image.size)
        dimensions = f"{width} × {height} px"
        if width * height > IMAGE_LIMIT:
            self.export_info.set(f"{dimensions} · 超过 3000 万像素")
            return
        self.export_info.set(f"{dimensions} · 正在计算文件大小…")

        def encode():
            try:
                data = BytesIO()
                export_image(image, data, name, percent, quality)
                length = data.tell()
                size = f"{length / 1048576:.2f} MiB" if length >= 1048576 else f"{length / 1024:.1f} KiB"
                info = f"{dimensions} · {size} · {name}"
            except (OSError, ValueError):
                info = f"{dimensions} · 无法计算文件大小"
            self.events.put((revision, "export_info", info))

        def schedule():
            self.export_timer = None
            threading.Thread(target=encode, daemon=True).start()

        self.export_timer = self.root.after(275, schedule)

    def change_export_format(self, *_):
        if self.export_format.get() == "JPG":
            self.quality_controls.pack(side="left")
        else:
            self.quality_controls.pack_forget()
        self.queue_export_info()

    def restyle(self, _event=None):
        if self.render_inputs is None or self.busy:
            return
        try:
            percent = self.percent(self.text_scale.get(), 25, 200)
        except ValueError as error:
            self.status.set(str(error))
            return
        self.busy = True
        self.refresh_buttons()
        self.status.set("正在调整译文字号…")
        threading.Thread(target=self.render, args=(self.generation, self.image, self.render_inputs,
                                                   percent, "restyled"), daemon=True).start()

    def maybe_start(self):
        provider = self.provider.get()
        if self.busy:
            self.status.set("上一张正在处理，完成后会处理当前图片。")
        elif provider not in API_PROVIDERS or self.keys[provider].get().strip():
            self.start()
        else:
            self.status.set("图片已载入。请在「设置」中填写 API Key，或选择 ChatGPT 登录。")

    def start(self):
        if self.busy or self.image is None:
            return
        provider = self.provider.get()
        key = self.keys[provider].get().strip() if provider in self.keys else ""
        if provider in API_PROVIDERS and not key:
            self.status.set("请在「设置」中输入所选服务的 API Key。")
            self.show_settings(True)
            self.key_entry.focus_set()
            return
        try:
            address = "" if provider in WEB_PROVIDERS else self.selected_proxy()
        except ValueError as error:
            self.status.set(str(error))
            self.show_settings(True)
            return
        try:
            text_percent = self.percent(self.text_scale.get(), 25, 200)
        except ValueError as error:
            self.status.set(str(error))
            return
        instructions = self.instructions.get("1.0", "end-1c").strip()
        if len(instructions) > 4000:
            self.status.set("术语与翻译要求最多支持 4000 字。")
            return
        self.busy = True
        self.refresh_buttons()
        self.status.set("正在本机识别文字…")
        language = self.language.get()
        model = self.models[provider].get() if provider in self.models else ""
        args = (self.generation, self.image, language, provider, key, self.network.get(), address,
                model, instructions, text_percent, self.ocr_mode.get())
        threading.Thread(target=self.work, args=args, daemon=True).start()

    def work(self, generation, image, language, provider, key, mode, address, model, instructions, text_percent,
             ocr_mode):
        try:
            started = perf_counter()
            regions = recognize(image, ocr_mode)
            if not regions:
                raise ValueError("没有识别到文字。可试用清晰的中文或拉丁字母图片。")
            summary = f"{ocr_backend()} OCR · {perf_counter() - started:.2f} 秒 · {len(regions)} 行"
            if provider in WEB_PROVIDERS:
                self.events.put((generation, "web",
                                 (image, regions, language, provider, instructions, text_percent, summary)))
                return
            self.events.put((generation, "progress", f"{summary} · 正在请求 {provider} 翻译…"))
            translations = translate([text for _, text in regions], language, provider, key, mode, address,
                                     model, instructions)
            self.render(generation, image, (regions, translations, LANGUAGES[language]), text_percent)
        except requests.exceptions.Timeout:
            self.events.put((generation, "error", "连接翻译服务超时，请检查网络或代理后重试。"))
        except requests.exceptions.RequestException:
            self.events.put((generation, "error", "无法连接翻译服务，请检查网络及代理地址。"))
        except ValueError as error:
            self.events.put((generation, "error", str(error)))
        except Exception:
            self.events.put((generation, "error", "处理失败。请检查图片、网络和翻译服务后重试。"))

    def render(self, generation, image, inputs, text_percent, action="done"):
        try:
            result = repaint(image, *inputs, text_percent=text_percent)
            self.events.put((generation, action, (result, inputs, text_percent)))
        except Exception:
            self.events.put((generation, "error", "无法回填译文。"))

    def browser_translation(self, generation, image, regions, language, provider, instructions, text_percent, summary):
        self.busy = True
        self.refresh_buttons()
        self.status.set(f"{summary} · 等待网页译文")
        dialog = tk.Toplevel(self.root)
        dialog.title(provider)
        dialog.transient(self.root)
        dialog.geometry("665x435")
        dialog.minsize(520, 335)
        dialog.configure(bg=BG, padx=16, pady=12)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(2, weight=1)
        tk.Label(dialog, text="在官网发送提示词，复制 AI 的回复，然后回到这里点击「生成译图」。",
                 bg=BG, fg=INK, wraplength=470, justify="left").grid(row=0, sticky="w", pady=(0, 8))
        panel = tk.Frame(dialog, bg=BG)
        panel.grid(row=1, sticky="ew", pady=(0, 8))
        response = tk.Text(dialog, wrap="word", height=6, width=1, padx=8, pady=6, undo=True)
        response.grid(row=2, sticky="nsew")
        notice = tk.StringVar(value=f"需要 {len(regions)} 条译文。支持 JSON，也可每行填写一条。")
        feedback = tk.Label(dialog, textvariable=notice, bg=BG, fg=MUTED,
                            justify="left", anchor="w", wraplength=465)
        feedback.grid(row=3, sticky="ew", pady=(7, 2))
        prompt = translation_prompt([text for _, text in regions], language, instructions)

        def warn(message):
            feedback.configure(fg="#a32622")
            notice.set(message)

        def copy_prompt():
            dialog.clipboard_clear()
            dialog.clipboard_append(prompt)
            if not webbrowser.open(WEB_PROVIDERS[provider]):
                warn("提示词已复制。浏览器未打开，请手动打开官网。")
                return
            feedback.configure(fg=MUTED)
            notice.set("已复制提示词。请粘贴到网页聊天框。")

        def paste_reply():
            try:
                text = dialog.clipboard_get().strip()
            except tk.TclError:
                text = ""
            if not text:
                warn("剪贴板中没有文本。请先复制网页上的 AI 回复。")
                return False
            if text == prompt:
                warn("剪贴板里还是提示词。请复制网页上的 AI 回复。")
                return False
            response.delete("1.0", "end")
            response.insert("1.0", text)
            feedback.configure(fg=MUTED)
            notice.set("已粘贴回复。点击「生成译图」继续。")
            return True

        def cancel():
            dialog.destroy()
            self.events.put((generation, "error", "已取消网页翻译。"))

        def apply():
            if not response.get("1.0", "end-1c").strip() and not paste_reply():
                return
            try:
                lines = parse_web_translation(response.get("1.0", "end-1c"), len(regions))
            except ValueError as error:
                warn(str(error))
                response.focus_set()
                return
            dialog.destroy()
            self.status.set("正在回填译文…")

            inputs = (regions, lines, LANGUAGES[language])
            threading.Thread(target=self.render, args=(generation, image, inputs, text_percent), daemon=True).start()

        self.button(panel, "复制提示词并打开官网", copy_prompt, primary=True).pack(side="left")
        self.button(panel, "粘贴网页回复", paste_reply).pack(side="left", padx=8)
        footer = tk.Frame(dialog, bg=BG)
        footer.grid(row=4, sticky="ew", pady=(6, 0))
        self.button(footer, "取消", cancel).pack(side="right", padx=(8, 0))
        self.button(footer, "生成译图", apply, primary=True).pack(side="right")
        dialog.bind("<Control-Return>", lambda _: apply())
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.grab_set()
        response.focus_set()

    def poll(self):
        while not self.events.empty():
            generation, action, value = self.events.get_nowait()
            if action == "export_info":
                if generation == self.export_revision:
                    self.export_info.set(value)
                continue
            if action == "progress":
                if generation == self.generation:
                    self.status.set(value)
                continue
            self.busy = False
            if generation != self.generation:
                self.refresh_buttons()
                self.maybe_start()
                continue
            if action == "web":
                self.browser_translation(generation, *value)
                continue
            if action in {"done", "restyled"}:
                self.result, self.render_inputs, text_percent = value
                regions, _, tag = self.render_inputs
                self.after.set(self.result)
                self.queue_export_info()
                if action == "done":
                    self.filename = f"{self.source}_{tag}_{datetime.now():%Y%m%d_%H%M%S}"
                    self.status.set(f"翻译完成 · {len(regions)} 行 · 可保存译图")
                else:
                    self.status.set(f"已应用 {text_percent}% 译文字号 · 同组文字按版面统一适配")
            else:
                self.status.set(value)
            self.refresh_buttons()
        self.root.after(60, self.poll)

    def save(self):
        if self.result is None:
            return
        name = self.export_format.get()
        suffix, _, _ = EXPORT_FORMATS[name]
        try:
            percent = self.percent(self.scale.get(), 1, 400)
        except ValueError as error:
            self.status.set(str(error))
            return
        stem = self.filename if percent == 100 else f"{self.filename}_{percent}pct"
        path = filedialog.asksaveasfilename(initialdir=downloads_folder(), initialfile=stem + suffix,
                                           defaultextension=suffix, filetypes=[(name + " 图片", "*" + suffix)])
        if path:
            target = Path(path)
            allowed = {suffix, *({"JPG": (".jpeg",), "TIFF": (".tif",)}.get(name, ()))}
            if target.suffix.lower() not in allowed:
                target = target.with_name(target.name + suffix)
                if target.exists() and not messagebox.askyesno("覆盖文件", f"覆盖 {target.name}？"):
                    return
            try:
                export_image(self.result, target, name, percent, int(self.jpg_quality.get().removesuffix("%")))
                self.status.set("已保存 " + target.name)
            except ValueError as error:
                self.status.set(str(error))
            except OSError:
                self.status.set("保存失败。请检查目标文件夹权限或另选位置。")


def smoke_test(destination):
    import subprocess
    from PIL import ImageDraw, ImageFont
    from translation import font_file
    if getattr(sys, "frozen", False):
        subprocess.run([codex_path(), "--version"], check=True, capture_output=True,
                       timeout=25, creationflags=subprocess.CREATE_NO_WINDOW)
    image = Image.new("RGBA", (560, 220), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 16, 48, 55), fill="#006e65")
    draw.text((86, 73), "Hello World", font=ImageFont.truetype(font_file("en"), 38), fill="#152635")
    regions = recognize(image)
    assert any("Hello" in value for _, value in regions), regions
    if os.getenv("TUYI_SMOKE_EXPECT_GPU") == "1":
        assert ocr_backend().startswith("GPU"), ocr_backend()
        cpu_regions = recognize(image, OCR_MODES[1])
        assert ocr_backend() == "CPU"
        assert any("Hello" in value for _, value in cpu_regions), cpu_regions
    result = repaint(image, regions, ["你好，世界"] * len(regions), "zh-CN")
    assert result.size == image.size and result.getpixel((30, 30)) == image.getpixel((30, 30))
    assert result.tobytes() != image.tobytes()
    base = Path(destination)
    result.putpixel((0, 0), (255, 0, 0, 0))
    for name, (suffix, expected, _) in EXPORT_FORMATS.items():
        path = base.with_suffix(suffix)
        export_image(result, path, name, 60)
        with open_image(path) as exported:
            assert exported.size == (336, 132) and exported.format == ("PNG" if expected == "SVG" else expected)
            if name == "JPG":
                assert all(channel > 245 for channel in exported.getpixel((0, 0)))
    root = tk.Tk()
    App(root)
    root.update()
    root.destroy()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        smoke_test(sys.argv[2])
    else:
        root = tk.Tk()
        App(root)
        root.mainloop()
