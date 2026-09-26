"""ttkbootstrap main window for MangaCleanup."""
from __future__ import annotations

import csv
import queue
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tkinter import filedialog, messagebox

import ttkbootstrap as ttk
from PIL import Image

from core.neko import NekoProject, load_neko
from core.pipeline import JobConfig, JobResult, process_one
from core.scanner import attach_neko, find_neko_files, scan_images
from providers.base import size_for_provider
from providers.factory import create_provider
from utils.config import load_config, save_config
from utils.constants import (
    DEFAULT_GEMINI_BASE_URL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GROK_BASE_URL,
    DEFAULT_GROK_MODEL,
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PROMPT,
    GEMINI_MODEL_PRESETS,
    GEMINI_SIZE_PRESETS,
    GROK_MODEL_PRESETS,
    GROK_SIZE_PRESETS,
    IMAGE_SIZE_PRESETS,
    OPENAI_MODEL_PRESETS,
    OPENAI_SIZE_PRESETS,
)
from utils.fs import ensure_dir, open_folder

MODE_LABELS = {"auto": "全自动(全图失败转截屏)", "full": "强制全图", "crop": "强制截屏回填"}
LABEL_TO_MODE = {v: k for k, v in MODE_LABELS.items()}


class MainWindow(ttk.Window):
    def __init__(self):
        super().__init__(themename="superhero")
        self.title("MangaCleanup - 漫画清字")
        self.geometry("1180x800")
        self.minsize(900, 600)

        self.cfg = load_config()
        self.items: list = []
        self.neko: NekoProject | None = None
        self.ui_queue: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.running = False
        self.status_map: dict[str, JobResult] = {}

        self._build_vars()
        self._build_layout()
        self._apply_config_to_ui()
        self._poll_id = self.after(120, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- vars / layout ----------
    def _build_vars(self):
        c = self.cfg
        self.var_input = tk.StringVar(value="")
        self.var_neko = tk.StringVar(value="")
        self.var_provider = tk.StringVar(value=c.get("provider", "OpenAI"))
        self.var_model = tk.StringVar(value=c.get("openai_model", DEFAULT_OPENAI_MODEL))
        self.var_base = tk.StringVar(value=c.get("openai_base_url", DEFAULT_OPENAI_BASE_URL))
        self.var_key = tk.StringVar(value=c.get("api_key", ""))
        self.var_remember = tk.BooleanVar(value=bool(c.get("remember_key")))
        self.var_retries = tk.IntVar(value=int(c.get("retries", 2)))
        self.var_pad = tk.IntVar(value=int(c.get("pad_px", 20)))
        self.var_workers = tk.IntVar(value=int(c.get("concurrency", 3)))
        self.var_timeout = tk.IntVar(value=int(c.get("timeout", 120)))
        self.var_size = tk.StringVar(value=str(c.get("image_size", "") or ""))
        self.var_subdir = tk.StringVar(value=c.get("output_subdir", "cleaned"))
        self.var_mode = tk.StringVar(value=MODE_LABELS.get(c.get("run_mode", "auto"), MODE_LABELS["auto"]))
        self.var_recursive = tk.BooleanVar(value=bool(c.get("recursive")))

    def _build_layout(self):
        root = ttk.Frame(self, padding=6)
        root.pack(fill="both", expand=True)

        self.notebook = ttk.Notebook(root)
        tab_run = ttk.Frame(self.notebook, padding=4)
        tab_cfg = ttk.Frame(self.notebook, padding=4)
        self.notebook.add(tab_run, text="运行")
        self.notebook.add(tab_cfg, text="配置")

        self._build_run_tab(tab_run)
        self._build_config_tab(tab_cfg)

        # --- bottom: progress (always visible below the tabs) ---
        fr_status = ttk.Frame(root)
        fr_status.pack(side="bottom", fill="x", pady=(4, 0))
        self.progress = ttk.Progressbar(fr_status, mode="determinate")
        self.progress.pack(fill="x")

        self.notebook.pack(fill="both", expand=True)

    def _build_run_tab(self, tab):
        # --- row: input ---
        fr_in = ttk.Labelframe(tab, text="输入 / 输出", padding=4)
        fr_in.pack(fill="x")
        ttk.Label(fr_in, text="输入文件夹").grid(row=0, column=0, sticky="w")
        ttk.Entry(fr_in, textvariable=self.var_input, width=70).grid(row=0, column=1, padx=6, sticky="ew")
        ttk.Button(fr_in, text="浏览目录", command=self._browse_input, bootstyle="info").grid(row=0, column=2, padx=2)
        ttk.Button(fr_in, text="打开文件夹", command=lambda: self._open_dir(self.var_input.get())).grid(row=0, column=3, padx=2)
        ttk.Button(fr_in, text="重新扫描", command=self.rescan, bootstyle="success").grid(row=0, column=4, padx=2)
        ttk.Checkbutton(fr_in, text="递归子目录", variable=self.var_recursive, command=self.rescan).grid(row=0, column=5, padx=6)
        ttk.Label(fr_in, text="neko工程").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(fr_in, textvariable=self.var_neko, width=70).grid(row=1, column=1, padx=6, pady=(6, 0), sticky="ew")
        ttk.Button(fr_in, text="浏览", command=self._browse_neko).grid(row=1, column=2, padx=2, pady=(6, 0))
        ttk.Button(fr_in, text="自动查找", command=self._auto_neko).grid(row=1, column=3, padx=2, pady=(6, 0))
        self.lbl_neko = ttk.Label(fr_in, text="未加载neko", bootstyle="secondary")
        self.lbl_neko.grid(row=1, column=4, columnspan=2, sticky="w", padx=6, pady=(6, 0))
        fr_in.columnconfigure(1, weight=1)

        # --- row: run controls (mode shares var with 配置页) ---
        fr_r = ttk.Frame(tab)
        fr_r.pack(fill="x", pady=(4, 0))
        ttk.Label(fr_r, text="运行模式").pack(side="left")
        ttk.Combobox(fr_r, textvariable=self.var_mode, values=list(MODE_LABELS.values()), width=24, state="readonly").pack(side="left", padx=6)
        ttk.Button(fr_r, text="开始处理", command=self.start, bootstyle="primary").pack(side="right", padx=2)
        ttk.Button(fr_r, text="取消", command=self.cancel, bootstyle="danger-outline").pack(side="right", padx=2)
        ttk.Button(fr_r, text="重试失败", command=self.retry_failed, bootstyle="secondary").pack(side="right", padx=2)
        ttk.Button(fr_r, text="打开输出", command=self._open_output).pack(side="right", padx=2)

        # --- center: splitter keeps BOTH list and terminal visible in small
        # windows (pack alone would starve one of them down to ~1px) ---
        self.pane = ttk.Panedwindow(tab, orient="vertical")
        self.pane.pack(fill="both", expand=True, pady=(4, 0))

        # --- list ---
        self.fr_l = ttk.Labelframe(self.pane, text="图像列表 (双击切换强制截屏)", padding=4)
        fr_l = self.fr_l
        cols = ("name", "size", "match", "boxes", "force", "status")
        self.tree = ttk.Treeview(fr_l, columns=cols, show="headings", height=6)
        for cid, w, txt in [("name", 320, "文件名"), ("size", 100, "尺寸"), ("match", 130, "neko匹配"),
                            ("boxes", 60, "框数"), ("force", 80, "强制截屏"), ("status", 380, "状态")]:
            self.tree.heading(cid, text=txt)
            self.tree.column(cid, width=w, anchor="w" if cid in ("name", "status") else "center")
        sb = ttk.Scrollbar(fr_l, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._toggle_force)
        fr_btn = ttk.Frame(fr_l)
        fr_btn.pack(side="right", padx=(6, 0), fill="y")
        ttk.Button(fr_btn, text="设为强制截屏", command=lambda: self._set_force(True)).pack(fill="x", pady=2)
        ttk.Button(fr_btn, text="取消强制", command=lambda: self._set_force(False)).pack(fill="x", pady=2)
        self.pane.add(fr_l, weight=3)

        # --- log / terminal (shares the splitter, never clipped) ---
        fr_log = ttk.Labelframe(self.pane, text="日志 / 终端", padding=4)
        self.txt_log = tk.Text(fr_log, height=5, wrap="word", state="disabled")
        log_sb = ttk.Scrollbar(fr_log, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=log_sb.set)
        self.txt_log.pack(side="left", fill="both", expand=True)
        log_sb.pack(side="right", fill="y")
        self.pane.add(fr_log, weight=2)
        # initial 60/40 split once geometry is known (default sashpos would
        # otherwise starve one side in small windows)
        self._sash_id = self.after_idle(self._init_sash)

    def _build_config_tab(self, tab):
        # --- provider ---
        fr_p = ttk.Labelframe(tab, text="图像编辑模型 (OpenAI / Gemini 可选，模型名可编辑)", padding=4)
        fr_p.pack(fill="x")
        ttk.Label(fr_p, text="协议").grid(row=0, column=0, sticky="w")
        self.cb_provider = ttk.Combobox(fr_p, textvariable=self.var_provider, values=["OpenAI", "Gemini", "Grok", "Mock"], width=10, state="readonly")
        self.cb_provider.grid(row=0, column=1, padx=6, sticky="w")
        self.cb_provider.bind("<<ComboboxSelected>>", lambda e: self._on_provider_switch())
        ttk.Label(fr_p, text="模型名").grid(row=0, column=2, sticky="w")
        self.cb_model = ttk.Combobox(fr_p, textvariable=self.var_model, width=38)
        self.cb_model.grid(row=0, column=3, padx=6, sticky="ew")
        ttk.Label(fr_p, text="BaseURL").grid(row=0, column=4, sticky="w")
        ttk.Entry(fr_p, textvariable=self.var_base, width=36).grid(row=0, column=5, padx=6, sticky="ew")
        ttk.Button(fr_p, text="测试连接", command=self._test_connection, bootstyle="warning").grid(row=0, column=6, padx=2)
        ttk.Label(fr_p, text="API Key").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(fr_p, textvariable=self.var_key, width=30, show="*").grid(row=1, column=1, columnspan=2, padx=6, pady=(6, 0), sticky="ew")
        ttk.Checkbutton(fr_p, text="记住Key(存config.json)", variable=self.var_remember).grid(row=1, column=3, pady=(6, 0), sticky="w")
        fr_p.columnconfigure(3, weight=1)
        fr_p.columnconfigure(5, weight=1)

        # --- params ---
        fr_c = ttk.Labelframe(tab, text="处理参数", padding=4)
        fr_c.pack(fill="x", pady=(4, 0))
        ttk.Label(fr_c, text="运行模式").grid(row=0, column=0, sticky="w")
        ttk.Combobox(fr_c, textvariable=self.var_mode, values=list(MODE_LABELS.values()), width=24, state="readonly").grid(row=0, column=1, padx=6, sticky="w")
        ttk.Label(fr_c, text="输出子目录").grid(row=0, column=2, sticky="w")
        ttk.Entry(fr_c, textvariable=self.var_subdir, width=14).grid(row=0, column=3, padx=6, sticky="w")
        ttk.Label(fr_c, text="并发").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(fr_c, from_=1, to=8, textvariable=self.var_workers, width=5).grid(row=0, column=5, padx=6, sticky="w")
        ttk.Label(fr_c, text="超时(s)").grid(row=0, column=6, sticky="w")
        ttk.Spinbox(fr_c, from_=30, to=600, textvariable=self.var_timeout, width=6).grid(row=0, column=7, padx=6, sticky="w")
        ttk.Label(fr_c, text="失败重试").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(fr_c, from_=0, to=5, textvariable=self.var_retries, width=5).grid(row=1, column=1, padx=6, sticky="w", pady=(6, 0))
        ttk.Label(fr_c, text="扩展像素").grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Spinbox(fr_c, from_=0, to=200, textvariable=self.var_pad, width=6).grid(row=1, column=3, padx=6, sticky="w", pady=(6, 0))
        ttk.Label(fr_c, text="分辨率").grid(row=1, column=4, sticky="w", pady=(6, 0))
        self.cb_size = ttk.Combobox(fr_c, textvariable=self.var_size, values=IMAGE_SIZE_PRESETS, width=14)
        self.cb_size.grid(row=1, column=5, padx=6, sticky="w", pady=(6, 0))
        ttk.Label(fr_c, text="留空=auto；OpenAI填WxH，Gemini/Grok填1K/2K或宽高比", bootstyle="secondary").grid(row=1, column=6, columnspan=2, sticky="w", pady=(6, 0))

        # --- prompt ---
        self.fr_prompt = ttk.Labelframe(tab, text="提示词 (过审/不过审共用)", padding=4)
        self.fr_prompt.pack(fill="x", pady=(4, 0))
        self.txt_prompt = tk.Text(self.fr_prompt, height=6, wrap="word")
        self.txt_prompt.pack(side="left", fill="x", expand=True)
        prompt_sb = ttk.Scrollbar(self.fr_prompt, orient="vertical", command=self.txt_prompt.yview)
        self.txt_prompt.configure(yscrollcommand=prompt_sb.set)
        prompt_sb.pack(side="left", fill="y")
        self.txt_prompt.insert("1.0", self.cfg.get("prompt", DEFAULT_PROMPT))
        ttk.Button(self.fr_prompt, text="恢复默认", command=self._reset_prompt).pack(side="right", padx=(6, 0))

        # --- save ---
        fr_s = ttk.Frame(tab)
        fr_s.pack(fill="x", pady=(8, 0))
        ttk.Button(fr_s, text="保存配置", command=self._save_settings, bootstyle="success").pack(side="right", padx=2)

    def _init_sash(self):
        try:
            if not self.winfo_exists():
                return
            self.pane.update_idletasks()
            h = self.pane.winfo_height()
            if h > 100:
                self.pane.sashpos(0, int(h * 0.6))
        except tk.TclError:
            pass

    def _apply_config_to_ui(self):
        self._on_provider_switch(init=True)

    # ---------- helpers ----------
    def log(self, msg: str):
        self.ui_queue.put(("log", msg))

    def _append_log(self, msg: str):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _open_dir(self, path: str):
        if not path or not Path(path).is_dir():
            messagebox.showwarning("提示", "目录不存在，请先选择有效文件夹")
            return
        try:
            open_folder(path)
        except Exception as e:
            messagebox.showerror("打开失败", str(e))

    def _open_output(self):
        base = self.var_input.get().strip()
        if not base:
            return
        self._open_dir(str(Path(base) / (self.var_subdir.get().strip() or "cleaned")))

    def _browse_input(self):
        d = filedialog.askdirectory(title="选择输入文件夹")
        if d:
            self.var_input.set(d)
            self.rescan()

    def _browse_neko(self):
        f = filedialog.askopenfilename(title="选择neko工程", filetypes=[("neko", "*.neko"), ("全部", "*.*")])
        if f:
            self.var_neko.set(f)
            self.rescan()

    def _auto_neko(self):
        base = self.var_input.get().strip()
        if not base:
            messagebox.showwarning("提示", "请先选择输入文件夹")
            return
        found = find_neko_files(base)
        if found:
            self.var_neko.set(str(found[0]))
            self.log(f"自动找到neko: {found[0].name}")
            self.rescan()
        else:
            self.log("输入目录下未找到 *.neko，可手动指定")

    def _reset_prompt(self):
        self.txt_prompt.delete("1.0", "end")
        self.txt_prompt.insert("1.0", DEFAULT_PROMPT)

    def _save_settings(self):
        cfg = self._collect_ui_config()
        save_config(cfg)
        self._append_log("配置已保存")

    def _on_provider_switch(self, init=False):
        p = self.var_provider.get()
        hist: list = self.cfg.get("model_history", [])
        if p == "Gemini":
            if init:
                self.var_model.set(self.cfg.get("gemini_model", DEFAULT_GEMINI_MODEL))
                self.var_base.set(self.cfg.get("gemini_base_url", DEFAULT_GEMINI_BASE_URL))
            else:
                self.var_model.set(self.cfg.get("gemini_model", DEFAULT_GEMINI_MODEL) or DEFAULT_GEMINI_MODEL)
                self.var_base.set(DEFAULT_GEMINI_BASE_URL)
            self.cb_model.configure(values=list(dict.fromkeys(GEMINI_MODEL_PRESETS + hist)))
            self.cb_size.configure(values=GEMINI_SIZE_PRESETS)
        elif p == "Grok":
            if init:
                self.var_model.set(self.cfg.get("grok_model", DEFAULT_GROK_MODEL))
                self.var_base.set(self.cfg.get("grok_base_url", DEFAULT_GROK_BASE_URL))
            else:
                self.var_model.set(self.cfg.get("grok_model", DEFAULT_GROK_MODEL) or DEFAULT_GROK_MODEL)
                self.var_base.set(DEFAULT_GROK_BASE_URL)
            self.cb_model.configure(values=list(dict.fromkeys(GROK_MODEL_PRESETS + hist)))
            self.cb_size.configure(values=GROK_SIZE_PRESETS)
        elif p == "Mock":
            self.var_model.set("mock")
            self.cb_model.configure(values=["mock"])
            self.cb_size.configure(values=IMAGE_SIZE_PRESETS)
        else:
            if init:
                self.var_model.set(self.cfg.get("openai_model", DEFAULT_OPENAI_MODEL))
                self.var_base.set(self.cfg.get("openai_base_url", DEFAULT_OPENAI_BASE_URL))
            else:
                self.var_model.set(self.cfg.get("openai_model", DEFAULT_OPENAI_MODEL) or DEFAULT_OPENAI_MODEL)
                self.var_base.set(DEFAULT_OPENAI_BASE_URL)
            self.cb_model.configure(values=list(dict.fromkeys(OPENAI_MODEL_PRESETS + hist)))
            self.cb_size.configure(values=OPENAI_SIZE_PRESETS)
        if not init:
            # 防呆: 切协议时丢掉不适用的分辨率写法 (如切到 OpenAI 时残留的 2K)
            fixed = size_for_provider(p, self.var_size.get())
            if fixed != self.var_size.get():
                self.var_size.set(fixed)
                self._append_log(f"分辨率已重置为 auto (原值不适用于 {p})")

    def _collect_ui_config(self) -> dict:
        c = self.cfg
        c.update({
            "provider": self.var_provider.get(),
            "openai_model": self.var_model.get() if self.var_provider.get() == "OpenAI" else c.get("openai_model"),
            "gemini_model": self.var_model.get() if self.var_provider.get() == "Gemini" else c.get("gemini_model"),
            "grok_model": self.var_model.get() if self.var_provider.get() == "Grok" else c.get("grok_model"),
            "openai_base_url": self.var_base.get() if self.var_provider.get() == "OpenAI" else c.get("openai_base_url"),
            "gemini_base_url": self.var_base.get() if self.var_provider.get() == "Gemini" else c.get("gemini_base_url"),
            "grok_base_url": self.var_base.get() if self.var_provider.get() == "Grok" else c.get("grok_base_url"),
            "api_key": self.var_key.get().strip(),
            "remember_key": bool(self.var_remember.get()),
            "prompt": self.txt_prompt.get("1.0", "end").strip() or DEFAULT_PROMPT,
            "retries": int(self.var_retries.get()),
            "pad_px": int(self.var_pad.get()),
            "concurrency": max(1, min(8, int(self.var_workers.get()))),
            "timeout": int(self.var_timeout.get()),
            "image_size": self.var_size.get().strip().lower(),
            "output_subdir": self.var_subdir.get().strip() or "cleaned",
            "run_mode": LABEL_TO_MODE.get(self.var_mode.get(), "auto"),
            "recursive": bool(self.var_recursive.get()),
        })
        model = self.var_model.get().strip()
        if model and model not in c.get("model_history", []):
            c["model_history"] = ([model] + c.get("model_history", []))[:10]
        self.cfg = c
        return c

    # ---------- scan ----------
    def rescan(self):
        base = self.var_input.get().strip()
        if not base:
            return
        try:
            items = scan_images(base, recursive=bool(self.var_recursive.get()))
        except Exception as e:
            messagebox.showerror("扫描失败", str(e))
            return
        # load neko (explicit path or auto)
        neko = None
        neko_src = self.var_neko.get().strip()
        try:
            if neko_src and Path(neko_src).is_file():
                neko = load_neko(neko_src)
            else:
                found = find_neko_files(base)
                if found:
                    if not neko_src:
                        self.var_neko.set(str(found[0]))
                    neko = load_neko(found[0])
        except Exception as e:
            self._append_log(f"neko解析失败: {e}")
        self.neko = neko
        # keep force flags by path
        old_force = {str(i.path): i.force_crop for i in self.items}
        attach_neko(items, neko)
        for i in items:
            if str(i.path) in old_force:
                i.force_crop = old_force[str(i.path)]
        self.items = items
        self.status_map = {}
        self._refresh_tree()
        if neko:
            self.lbl_neko.configure(text=f"{neko.neko_path.name}: {neko.image_count}页/{neko.translation_count}框", bootstyle="success")
        else:
            self.lbl_neko.configure(text="未加载neko(全图可用，截屏将回退全图)", bootstyle="warning")
        self._append_log(f"扫描到 {len(items)} 张图像" + (f"，neko {neko.translation_count} 框" if neko else "，无neko"))
        self.progress.configure(value=0, maximum=max(1, len(items)))

    def _refresh_tree(self):
        for r in self.tree.get_children():
            self.tree.delete(r)
        for it in self.items:
            st = self.status_map.get(str(it.path))
            status = f"{st.status}: {st.message}" if st else "待处理"
            size = f"{it.width}x{it.height}" if it.width else "-"
            match = f"{it.neko_uid}({it.match_method})" if it.neko_uid else "未命中"
            self.tree.insert("", "end", iid=str(it.path), values=(
                it.name, size, match, it.box_count,
                "是" if it.force_crop else "否", status))

    def _toggle_force(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        for iid in sel:
            for it in self.items:
                if str(it.path) == iid:
                    it.force_crop = not it.force_crop
        self._refresh_tree()

    def _set_force(self, val: bool):
        sel = self.tree.selection() or [str(i.path) for i in self.items]
        for it in self.items:
            if str(it.path) in sel:
                it.force_crop = val
        self._refresh_tree()

    # ---------- run ----------
    def _make_provider(self, cfg: dict):
        provider = cfg["provider"]
        size = str(cfg.get("image_size", "") or "")
        if provider == "Gemini":
            return create_provider(provider, cfg.get("gemini_model", ""), cfg.get("api_key", ""),
                                   cfg.get("gemini_base_url", ""), int(cfg.get("timeout", 120)), size)
        if provider == "Grok":
            return create_provider(provider, cfg.get("grok_model", ""), cfg.get("api_key", ""),
                                   cfg.get("grok_base_url", ""), int(cfg.get("timeout", 120)), size)
        if provider == "Mock":
            return create_provider(provider, "mock", "", "", int(cfg.get("timeout", 120)), size)
        return create_provider(provider, cfg.get("openai_model", ""), cfg.get("api_key", ""),
                               cfg.get("openai_base_url", ""), int(cfg.get("timeout", 120)), size)

    def start(self, only_failed=False):
        if self.running:
            messagebox.showinfo("提示", "任务运行中")
            return
        base = self.var_input.get().strip()
        if not base or not Path(base).is_dir():
            messagebox.showwarning("提示", "请先选择有效输入文件夹")
            return
        if not self.items:
            self.rescan()
        if not self.items:
            messagebox.showwarning("提示", "未扫描到图像")
            return
        cfg = self._collect_ui_config()
        save_config(cfg)
        targets = list(self.items)
        if only_failed:
            targets = [i for i in self.items if str(i.path) in self.status_map and self.status_map[str(i.path)].status == "failed"]
            if not targets:
                messagebox.showinfo("提示", "没有失败项")
                return
        if cfg["provider"] != "Mock" and not cfg.get("api_key"):
            if not messagebox.askyesno("提示", "API Key 为空，仍要继续吗？"):
                return
        out_dir = ensure_dir(Path(base) / cfg["output_subdir"])
        self.cancel_event.clear()
        self.running = True
        self.progress.configure(value=0, maximum=len(targets))
        t = threading.Thread(target=self._worker, args=(targets, cfg, str(out_dir)), daemon=True)
        t.start()
        self.log(f"开始处理 {len(targets)} 张，模式={self.var_mode.get()}，输出={out_dir}")

    def retry_failed(self):
        self.start(only_failed=True)

    def cancel(self):
        self.cancel_event.set()
        self.log("已请求取消…")

    def _worker(self, targets, cfg, out_dir):
        provider = self._make_provider(cfg)
        job_cfg = JobConfig(prompt=cfg["prompt"], retries=int(cfg["retries"]),
                            pad_px=int(cfg["pad_px"]), run_mode=cfg["run_mode"],
                            output_dir=Path(out_dir))
        done = 0
        try:
            with ThreadPoolExecutor(max_workers=int(cfg["concurrency"])) as ex:
                futs = {ex.submit(process_one, it, self.neko, provider, job_cfg, self.cancel_event): it for it in targets}
                for fut in as_completed(futs):
                    if self.cancel_event.is_set():
                        for f in futs:
                            f.cancel()
                        self.ui_queue.put(("log", "任务已取消"))
                        break
                    it = futs[fut]
                    try:
                        res: JobResult = fut.result()
                    except Exception as e:
                        from core.pipeline import JobResult as JR
                        res = JR(it, "failed", f"异常: {e}")
                    self.ui_queue.put(("result", res))
                    done += 1
                    self.ui_queue.put(("progress", done))
        finally:
            self.ui_queue.put(("done", done))
            # write results.csv
            try:
                with open(Path(out_dir) / "results.csv", "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.writer(f)
                    w.writerow(["file", "status", "mode", "message", "output", "elapsed"])
                    for it in self.items:
                        r = self.status_map.get(str(it.path))
                        if r:
                            w.writerow([it.name, r.status, r.mode_used, r.message, r.output_path, round(r.elapsed, 1)])
            except Exception:
                pass

    def _poll_queue(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "progress":
                    self.progress.configure(value=payload)
                elif kind == "result":
                    self.status_map[str(payload.item.path)] = payload
                    if self.tree.exists(str(payload.item.path)):
                        it = payload.item
                        size = f"{it.width}x{it.height}" if it.width else "-"
                        match = f"{it.neko_uid}({it.match_method})" if it.neko_uid else "未命中"
                        self.tree.item(str(it.path), values=(
                            it.name, size, match, it.box_count,
                            "是" if it.force_crop else "否",
                            f"{payload.status} [{payload.mode_used}]: {payload.message}"))
                elif kind == "done":
                    self.running = False
                    ok = sum(1 for r in self.status_map.values() if r.status == "success")
                    fail = sum(1 for r in self.status_map.values() if r.status == "failed")
                    self._append_log(f"批量完成: 成功 {ok} / 失败 {fail}")
        except queue.Empty:
            pass
        except tk.TclError:
            return
        try:
            self._poll_id = self.after(120, self._poll_queue)
        except tk.TclError:
            pass

    def _test_connection(self):
        cfg = self._collect_ui_config()
        save_config(cfg)
        self.log(f"测试连接: {cfg['provider']} / {self.var_model.get()} …")

        def _run():
            try:
                provider = self._make_provider(cfg)
                img = Image.new("RGB", (256, 256), "white")
                out = provider.edit(img, "Return the image unchanged.")
                self.ui_queue.put(("log", f"连接成功，返回尺寸 {out.size}"))
            except Exception as e:
                self.ui_queue.put(("log", f"连接失败: {e}"))

        threading.Thread(target=_run, daemon=True).start()

    def _on_close(self):
        for attr in ("_poll_id", "_sash_id"):
            try:
                aid = getattr(self, attr, None)
                if aid:
                    self.after_cancel(aid)
            except Exception:
                pass
        try:
            save_config(self._collect_ui_config())
        except Exception:
            pass
        self.destroy()


def run_app():
    app = MainWindow()
    app.mainloop()
