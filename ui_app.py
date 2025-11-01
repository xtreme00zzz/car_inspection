#!/usr/bin/env python3
from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime
import shutil
import tempfile
import warnings
import zipfile
from pathlib import Path
from typing import Any
import sys
import os
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
import webbrowser
from app_version import UPDATE_CHANNEL
import updater

from inspector.reference_index import build_reference_index, save_index
from inspector.matcher import build_fingerprint_index
from inspector.validator import validate_submitted_car, RulebookConfig
from inspector.report import save_report
from inspector.anti_cheat import CHECK_HINTS as AC_HINTS
from auth.manager import AuthManager, AuthError
from auth import config as auth_config


APP_BASE_DIR = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def _default_data_root() -> Path:
    override = os.getenv('EF_SCRUTINEER_DATA_DIR')
    if override:
        return Path(override).expanduser()
    if sys.platform.startswith('win'):
        local_appdata = os.getenv('LOCALAPPDATA')
        if local_appdata:
            return Path(local_appdata) / 'eFDriftScrutineer'
        return Path.home() / 'AppData' / 'Local' / 'eFDriftScrutineer'
    return Path.home() / '.ef_drift_scrutineer'


def _default_reference_root() -> Path:
    override = os.getenv('EF_SCRUTINEER_REFERENCE_ROOT')
    if override:
        path = Path(override).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path
    candidates = [
        APP_BASE_DIR / 'reference_cars',
        Path.cwd() / 'reference_cars',
        _default_data_root() / 'reference_cars',
    ]
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except Exception:
            continue
    fallback = candidates[-1]
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


@dataclass
class AppState:
    reference_root: Path = field(default_factory=_default_reference_root)
    data_root: Path = field(default_factory=_default_data_root)
    submitted_car: Path | None = None
    ruleset: str = 'competition'  # default to competition
    json_out: bool = True
    cache_dir: Path = field(init=False)
    report_dir: Path = field(init=False)
    index_path: Path = field(init=False)
    fingerprints_path: Path = field(init=False)
    settings_path: Path = field(init=False)

    def __post_init__(self):
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.cache_dir = self.data_root / 'cache'
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir = self.data_root / 'reports'
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.cache_dir / 'reference_index.json'
        self.fingerprints_path = self.cache_dir / 'reference_index.fingerprints.json'
        self.settings_path = self.cache_dir / 'settings.json'


class InspectorUI(tk.Tk):
    def __init__(self):
        super().__init__()
        if sys.platform.startswith('win'):
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('efdrift.scrutineer')
            except Exception:
                pass
        # Brand palette (classic light theme)
        self.BRAND_LIGHT = '#ECECEB'
        self.BRAND_SURFACE = '#FFFFFF'
        self.BRAND_SURFACE_ALT = '#F7F8FB'
        self.BRAND_OUTLINE = '#d5dbe8'
        self.BRAND_NAVY = '#10316B'
        self.BRAND_BLACK = '#000000'
        self.BRAND_ORANGE = '#E25822'
        # Status colors
        self.OK_FG = '#188038'; self.OK_BG = '#E6F4EA'
        self.BAD_FG = '#D93025'; self.BAD_BG = '#FCE8E6'
        self.WARN_FG = self.BRAND_ORANGE; self.WARN_BG = '#FFF4E5'
        # UI scale
        self.ui_scale = 1.0

        self.title('eF Drift Car Scrutineer')
        self.configure(bg=self.BRAND_LIGHT)
        # ttk theme and styles for a more modern look
        try:
            style = ttk.Style(self)
            # Use a platform-neutral modern theme
            if 'clam' in style.theme_names():
                style.theme_use('clam')
            style.configure('TNotebook', background=self.BRAND_LIGHT, borderwidth=0)
            style.configure('TNotebook.Tab', padding=(10, 6), font=('Segoe UI', 10),
                            background=self.BRAND_SURFACE_ALT, foreground=self.BRAND_BLACK)
            style.map('TNotebook.Tab',
                      background=[('selected', '#ffffff')],
                      foreground=[('selected', self.BRAND_BLACK)])
            style.configure('TFrame', background=self.BRAND_LIGHT)
            style.configure('TLabel', background=self.BRAND_LIGHT, foreground=self.BRAND_BLACK)
            # Modern buttons (light)
            base_bg = '#dfe4ef'
            style.configure('TButton', padding=(10, 6), background=base_bg, foreground=self.BRAND_BLACK,
                            borderwidth=0, relief='flat')
            style.map('TButton',
                      background=[('active', '#cfd6e5'), ('pressed', '#c1c9da'), ('disabled', '#eef1f6')],
                      foreground=[('disabled', '#7d7d7d')])
            # Primary (orange)
            style.configure('Primary.TButton', background=self.BRAND_ORANGE, foreground='white', relief='flat')
            style.map('Primary.TButton',
                      background=[('active', '#f06a36'), ('pressed', '#d44e17'), ('disabled', '#f5b79a')],
                      foreground=[('disabled', '#fafafa')])
            # Secondary (navy)
            style.configure('Secondary.TButton', background=self.BRAND_NAVY, foreground='white', relief='flat')
            style.map('Secondary.TButton',
                      background=[('active', '#2a5da8'), ('pressed', '#1c447d'), ('disabled', '#8097c2')],
                      foreground=[('disabled', '#f5f5f5')])
            # Success (green)
            style.configure('Success.TButton', background='#188038', foreground='white', relief='flat')
            style.map('Success.TButton',
                      background=[('active', '#2ba14a'), ('pressed', '#1a6f33'), ('disabled', '#8ec79c')],
                      foreground=[('disabled', '#f5f5f5')])
            # Neutral (cool gray)
            style.configure('Neutral.TButton', background='#d0d6e2', foreground=self.BRAND_BLACK, relief='flat')
            style.map('Neutral.TButton',
                      background=[('active', '#c1c8d8'), ('pressed', '#b3bbce'), ('disabled', '#e6e9f0')],
                      foreground=[('disabled', '#7d7d7d')])
        except Exception:
            pass
        self._icon_images: list[tk.PhotoImage] = []
        # Resolve icon path from bundled resources
        def _find_icon() -> Path | None:
            candidates = [
                APP_BASE_DIR / 'icon.ico',
                APP_BASE_DIR / '_internal' / 'icon.ico',
                Path(sys.executable).parent / 'icon.ico',
            ]
            for p in candidates:
                try:
                    if p.exists():
                        return p
                except Exception:
                    continue
            return None

        icon_path = _find_icon()
        if icon_path:
            try:
                self.iconbitmap(default=str(icon_path))
            except Exception:
                pass
            # Also set iconphoto for Tk (used by some window managers)
            try:
                from PIL import Image, ImageTk  # type: ignore
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    with Image.open(icon_path) as im:
                        # Convert to a Tk-compatible image
                        icon_img = ImageTk.PhotoImage(im)
                self.iconphoto(False, icon_img)
                self._icon_images.append(icon_img)
            except Exception:
                try:
                    icon_img = tk.PhotoImage(file=str(icon_path))
                    self.iconphoto(False, icon_img)
                    self._icon_images.append(icon_img)
                except Exception:
                    pass
        self._busy = False
        self._join_prompt_active = False
        self._initial_login_prompt_shown = False
        self.index_built = False
        self._building_index = False
        self._auto_inspect_job: str | None = None
        self._pending_auto_inspect: Path | None = None
        self._last_authed = False
        self._reference_index_cache = None
        self._graph_state: dict | None = None
        self._graph_redraw_pending = False
        self._graph_canvas_sizes: dict[str, tuple[int, int]] = {}
        self.join_help_text = 'Join the Discord server (https://discord.gg/efdrift) and DM xtreme for access.'
        self._source_archive: Path | None = None
        self._login_prompt_window: tk.Toplevel | None = None
        self.auth: AuthManager | None = None
        self.state = AppState()
        # Updater channel (persisted), default from app_version
        try:
            self.update_channel_var = tk.StringVar(value=str(UPDATE_CHANNEL))
        except Exception:
            self.update_channel_var = tk.StringVar(value='stable')
        self.report_raw_text = ''  # cached report text for filtering/search
        self._temp_car_extract: Path | None = None
        # Fonts
        self.base_font = ('Segoe UI', 10)
        self.mono_font = ('Consolas', 10)
        self._build_widgets()
        self._build_menu()
        self.load_settings()
        try:
            self.protocol('WM_DELETE_WINDOW', self._on_close)
        except Exception:
            pass
        self.auth = AuthManager(status_callback=self._queue_auth_status)
        self.update_auth_ui()
        self.after(200, self._launch_initial_login)
        # Apply initial window size after widgets settle
        self.after(80, self._apply_initial_geometry)

    def _build_widgets(self):
        pad = {'padx': 6, 'pady': 4}

        # Brand Header
        hdr = tk.Frame(self, bg=self.BRAND_NAVY)
        hdr.grid(row=0, column=0, sticky='ew', padx=6, pady=(8, 2))
        self.columnconfigure(0, weight=1)
        title = tk.Label(hdr, text='eF Drift Car Scrutineer', font=('Segoe UI', 16, 'bold'), fg='white', bg=self.BRAND_NAVY)
        subtitle = tk.Label(hdr, text='Assetto Corsa Car Validator', font=self.base_font, fg='white', bg=self.BRAND_NAVY)
        title.grid(row=0, column=0, sticky='w')
        subtitle.grid(row=1, column=0, sticky='w')
        hdr.columnconfigure(1, weight=1)
        # Right-side controls: pass/fail banner + auth status
        right = tk.Frame(hdr, bg=self.BRAND_NAVY)
        right.grid(row=0, column=1, rowspan=2, sticky='e', padx=(0, 6))
        self.pass_label = tk.Label(right, text='Inspection: Ready', font=('Segoe UI', 10, 'bold'),
                                   fg='white', bg=self.BRAND_NAVY, padx=10, pady=2)
        self.pass_label.pack(anchor='e')
        self.auth_user_var = tk.StringVar(value='Not authenticated')
        self.auth_user_label = tk.Label(right, textvariable=self.auth_user_var, font=('Segoe UI', 9), fg='white', bg=self.BRAND_NAVY)
        self.auth_user_label.pack(anchor='e', pady=(2, 0))
        self.login_btn = ttk.Button(right, text='Login with Discord', command=self.start_login_flow, style='Secondary.TButton')
        self.login_btn.pack(anchor='e', pady=(4, 0))
        self.join_button = ttk.Button(right, text='Join Discord Server', command=self.open_join_link, style='Neutral.TButton')
        # Do not pack join button until needed

        # Reference (selectable via menu)
        frm_ref = tk.LabelFrame(self, text='Reference', bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK)
        frm_ref.grid(row=1, column=0, sticky='ew', **pad)
        self.ref_frame = frm_ref
        self.ref_path_var = tk.StringVar(value=str(self.state.reference_root))
        tk.Label(frm_ref, textvariable=self.ref_path_var, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK, font=self.base_font).grid(row=0, column=0, sticky='w')
        frm_ref.columnconfigure(0, weight=1)

        # Submitted car
        frm_car = tk.LabelFrame(self, text='Submitted Car', bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK)
        frm_car.grid(row=2, column=0, sticky='ew', **pad)
        self.car_var = tk.StringVar(value='')
        # Make Browse left-most for visibility
        self.btn_browse = ttk.Button(frm_car, text='Browse', command=self.browse_car, style='Neutral.TButton')
        self.btn_browse.grid(row=0, column=0, padx=(2,6), sticky='w')
        tk.Label(frm_car, text='Car folder:', bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK, font=self.base_font).grid(row=0, column=1, sticky='w')
        self.car_entry = tk.Entry(frm_car, textvariable=self.car_var, width=50, bg='white', font=self.base_font,
                                  highlightthickness=2, highlightbackground=self.BRAND_LIGHT, highlightcolor=self.BRAND_ORANGE,
                                  state='readonly', readonlybackground='#f0f2f8')
        self.car_entry.grid(row=0, column=2, sticky='ew')
        # Focus highlight
        self.car_entry.bind('<FocusIn>', lambda e: self.car_entry.configure(highlightcolor=self.BRAND_ORANGE))
        self.car_entry.bind('<FocusOut>', lambda e: self.car_entry.configure(highlightcolor=self.BRAND_LIGHT))
        frm_car.columnconfigure(2, weight=1)

        # Options (Ruleset + Toggles)
        frm_opt = tk.LabelFrame(self, text='Options & Rules', bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK)
        frm_opt.grid(row=3, column=0, sticky='ew', **pad)
        # Keep a reference so we can hide this block (Settings moved to menu)
        self.options_frame = frm_opt
        # Top row: Ruleset and JSON
        # JSON export toggle only (ruleset is fixed to competition)
        self.json_var = tk.BooleanVar(value=self.state.json_out)
        tk.Checkbutton(frm_opt, text='Write JSON report', variable=self.json_var, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).grid(row=0, column=0, sticky='w')

        # Row 1: Mass & CG
        self.enf_mass_var = tk.BooleanVar(value=True)
        self.min_mass_var = tk.StringVar(value='1300')
        tk.Checkbutton(frm_opt, text='Enforce min mass (kg):', variable=self.enf_mass_var, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).grid(row=1, column=0, sticky='w')
        tk.Entry(frm_opt, textvariable=self.min_mass_var, width=8, bg='white', font=self.base_font).grid(row=1, column=1, sticky='w')
        self.enf_cg_var = tk.BooleanVar(value=True)
        self.cg_var = tk.StringVar(value='0.52')
        tk.Checkbutton(frm_opt, text='Front bias CG_LOCATION:', variable=self.enf_cg_var, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).grid(row=1, column=2, sticky='w')
        tk.Entry(frm_opt, textvariable=self.cg_var, width=8, bg='white', font=self.base_font).grid(row=1, column=3, sticky='w')

        # Row 2: Tyres
        self.enf_rear_tyre_var = tk.BooleanVar(value=True)
        self.rear_tyre_var = tk.StringVar(value='265')
        tk.Checkbutton(frm_opt, text='Rear tyre max (mm):', variable=self.enf_rear_tyre_var, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).grid(row=2, column=0, sticky='w')
        tk.Entry(frm_opt, textvariable=self.rear_tyre_var, width=8, bg='white', font=self.base_font).grid(row=2, column=1, sticky='w')
        self.enf_front_tyre_var = tk.BooleanVar(value=True)
        self.front_tyre_lo_var = tk.StringVar(value='225')
        self.front_tyre_hi_var = tk.StringVar(value='265')
        tk.Checkbutton(frm_opt, text='Front tyre range (mm):', variable=self.enf_front_tyre_var, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).grid(row=2, column=2, sticky='w')
        tk.Entry(frm_opt, textvariable=self.front_tyre_lo_var, width=6, bg='white', font=self.base_font).grid(row=2, column=3, sticky='w')
        tk.Label(frm_opt, text='-', bg=self.BRAND_LIGHT).grid(row=2, column=4)
        tk.Entry(frm_opt, textvariable=self.front_tyre_hi_var, width=6, bg='white', font=self.base_font).grid(row=2, column=5, sticky='w')

        # Row 3: Steering
        self.enf_steer_var = tk.BooleanVar(value=True)
        self.steer_max_var = tk.StringVar(value='70')
        # Default off to avoid PowerShell dependency unless explicitly enabled
        self.require_cm_var = tk.BooleanVar(value=False)
        tk.Checkbutton(frm_opt, text='Steering angle <= (deg):', variable=self.enf_steer_var, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).grid(row=3, column=0, sticky='w')
        tk.Entry(frm_opt, textvariable=self.steer_max_var, width=8, bg='white', font=self.base_font).grid(row=3, column=1, sticky='w')
        tk.Checkbutton(frm_opt, text='Auto-generate & require CM steering JSON', variable=self.require_cm_var, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).grid(row=3, column=2, columnspan=3, sticky='w')

        # Row 4: Assets & Model
        self.enf_assets_var = tk.BooleanVar(value=True)
        self.max_kn5_mb_var = tk.StringVar(value='60')
        self.max_skin_mb_var = tk.StringVar(value='30')
        tk.Checkbutton(frm_opt, text='KN5 max (MB):', variable=self.enf_assets_var, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).grid(row=4, column=0, sticky='w')
        tk.Entry(frm_opt, textvariable=self.max_kn5_mb_var, width=8, bg='white', font=self.base_font).grid(row=4, column=1, sticky='w')
        tk.Label(frm_opt, text='Skin max (MB):', bg=self.BRAND_LIGHT).grid(row=4, column=2, sticky='w')
        tk.Entry(frm_opt, textvariable=self.max_skin_mb_var, width=8, bg='white', font=self.base_font).grid(row=4, column=3, sticky='w')

        self.enf_model_var = tk.BooleanVar(value=False)
        # Default off to avoid external tool dependency unless explicitly enabled
        self.require_ks_var = tk.BooleanVar(value=False)
        self.max_tris_var = tk.StringVar(value='500000')
        self.max_objs_var = tk.StringVar(value='300')
        tk.Checkbutton(frm_opt, text='Model caps: Triangles/Objects', variable=self.enf_model_var, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).grid(row=5, column=0, sticky='w')
        tk.Entry(frm_opt, textvariable=self.max_tris_var, width=10, bg='white', font=self.base_font).grid(row=5, column=1, sticky='w')
        tk.Entry(frm_opt, textvariable=self.max_objs_var, width=6, bg='white', font=self.base_font).grid(row=5, column=2, sticky='w')
        tk.Checkbutton(frm_opt, text='Auto-generate & require KN5 stats JSON', variable=self.require_ks_var, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).grid(row=5, column=3, columnspan=2, sticky='w')

        # Row 5: Misc
        self.enf_rwd_var = tk.BooleanVar(value=True)
        self.enf_year_var = tk.BooleanVar(value=True)
        self.min_year_var = tk.StringVar(value='1965')
        self.e92_fallback_var = tk.BooleanVar(value=True)
        tk.Checkbutton(frm_opt, text='Enforce RWD', variable=self.enf_rwd_var, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).grid(row=6, column=0, sticky='w')
        tk.Checkbutton(frm_opt, text='Year >=', variable=self.enf_year_var, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).grid(row=6, column=1, sticky='e')
        tk.Entry(frm_opt, textvariable=self.min_year_var, width=6, bg='white', font=self.base_font).grid(row=6, column=2, sticky='w')
        tk.Checkbutton(frm_opt, text='Allow E92 fallback', variable=self.e92_fallback_var, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).grid(row=6, column=3, sticky='w')

        # Actions
        frm_act = tk.Frame(self)
        frm_act.grid(row=4, column=0, sticky='ew', **pad)
        self.btn_open_kn5 = ttk.Button(frm_act, text='Open KN5 🗂️', command=self.open_in_cm, style='Primary.TButton')
        self.btn_update_phy = ttk.Button(frm_act, text='Update Physics ⚙️', command=self.update_physics, style='Neutral.TButton')
        self.btn_export_html = ttk.Button(frm_act, text='Export HTML ⤓', command=self.export_html, style='Neutral.TButton')
        self.btn_fix_export = ttk.Button(frm_act, text='Fix Physics & Export 🛠️', command=self.fix_and_export, style='Success.TButton')
        self.btn_clear = ttk.Button(frm_act, text='Clear 🧹', command=self.clear_preview, style='Neutral.TButton')
        self.btn_open_kn5.grid(row=0, column=0, padx=2)
        self.btn_update_phy.grid(row=0, column=1, padx=2)
        self.btn_export_html.grid(row=0, column=2, padx=2)
        self.btn_fix_export.grid(row=0, column=3, padx=2)
        self.btn_clear.grid(row=0, column=4, padx=2)
        self.action_buttons = [
            self.btn_open_kn5, self.btn_update_phy,
            self.btn_export_html, self.btn_fix_export, self.btn_clear, self.btn_browse
        ]
        # Button tooltips
        self.attach_tooltip(self.btn_browse, 'Browse for car folder (Ctrl+O)')
        self.attach_tooltip(self.btn_open_kn5, 'Open main KN5 in default viewer')
        self.attach_tooltip(self.btn_update_phy, 'Replace physics from another car/data')
        self.attach_tooltip(self.btn_export_html, 'Export report as HTML (Ctrl+E)')
        self.attach_tooltip(self.btn_fix_export, 'Auto-fix physics and export ZIP')
        self.attach_tooltip(self.btn_clear, 'Clear report and selections (Ctrl+L)')

        # Output
        # (Report preview moved into notebook below)

        # Report + Graphs + Car Info notebook
        nb = ttk.Notebook(self)
        nb.grid(row=6, column=0, sticky='nsew', padx=6, pady=6)
        self.rowconfigure(6, weight=1)
        # Report tab (with enhanced header)
        tab_report = tk.Frame(nb, bg=self.BRAND_LIGHT)
        nb.add(tab_report, text='Report')
        tab_report.rowconfigure(2, weight=1)
        tab_report.columnconfigure(0, weight=1)
        header = tk.Frame(tab_report, bg=self.BRAND_LIGHT)
        header.grid(row=0, column=0, sticky='ew', padx=6, pady=(6, 2))
        head_text = tk.Frame(header, bg=self.BRAND_LIGHT)
        head_text.pack(side='left', padx=10, fill='x', expand=True)
        self.report_title_label = tk.Label(head_text, text='No car selected', font=('Segoe UI', 13, 'bold'), bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK)
        self.report_title_label.pack(anchor='w')
        self.report_meta_label = tk.Label(head_text, text='', font=('Segoe UI', 9), bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK)
        self.report_meta_label.pack(anchor='w')
        # Add PASS/FAIL pill on the right
        self.report_status_label = tk.Label(header, text='', font=('Segoe UI', 9, 'bold'), padx=10, pady=4, bg=self.BRAND_LIGHT)
        self.report_status_label.pack(side='right')
        # Report controls (filter + search)
        ctrl = tk.Frame(tab_report, bg=self.BRAND_LIGHT)
        ctrl.grid(row=1, column=0, columnspan=2, sticky='ew', padx=6, pady=(0, 6))
        ctrl.columnconfigure(3, weight=1)
        tk.Label(ctrl, text='Filter:', bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK, font=self.base_font).grid(row=0, column=0, sticky='w')
        self.report_filter_var = tk.StringVar(value='all')
        filter_box = ttk.Combobox(ctrl, textvariable=self.report_filter_var, state='readonly', values=('all', 'issues', 'warnings', 'failures'), width=12)
        filter_box.grid(row=0, column=1, sticky='w', padx=(6, 16))
        filter_box.bind('<<ComboboxSelected>>', lambda _e=None: self.render_report_text())
        filter_box.current(0)
        self.attach_tooltip(filter_box, 'Choose which report rows to display (all, only issues, warnings, or failures).')
        tk.Label(ctrl, text='Search:', bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK, font=self.base_font).grid(row=0, column=2, sticky='w')
        self.report_search_var = tk.StringVar(value='')
        search_entry = ttk.Entry(ctrl, textvariable=self.report_search_var, width=28)
        search_entry.grid(row=0, column=3, sticky='ew', padx=(6, 0))
        search_entry.bind('<KeyRelease>', lambda _e=None: self._on_report_search_change())
        self.attach_tooltip(search_entry, 'Type to highlight matching text within the report.')
        clear_btn = ttk.Button(ctrl, text='Clear', command=self._clear_report_search, style='Neutral.TButton')
        clear_btn.grid(row=0, column=4, sticky='w', padx=(6, 0))
        self.attach_tooltip(clear_btn, 'Clear the search box and restore the full report view.')
        # Report text + scrollbar
        self.txt = tk.Text(tab_report, wrap='char', bg='white', fg=self.BRAND_BLACK,
                           font=self.mono_font)
        vsb = ttk.Scrollbar(tab_report, orient='vertical', command=self.txt.yview)
        self.txt.configure(yscrollcommand=vsb.set)
        self.txt.grid(row=2, column=0, sticky='nsew')
        vsb.grid(row=2, column=1, sticky='ns')
        # Context menu for report
        self.txt_menu = tk.Menu(self, tearoff=0)
        self.txt_menu.add_command(label='Copy', command=lambda: self.txt.event_generate('<<Copy>>'))
        def _txt_popup(e):
            try:
                self.txt_menu.tk_popup(e.x_root, e.y_root)
            finally:
                self.txt_menu.grab_release()
        self.txt.bind('<Button-3>', _txt_popup)
        # Summary tab — visual chips for key checks (scrollable)
        tab_summary = tk.Frame(nb, bg=self.BRAND_LIGHT)
        nb.add(tab_summary, text='Summary')
        self.summary_canvas = tk.Canvas(tab_summary, bg=self.BRAND_LIGHT, highlightthickness=0)
        self.summary_vsb = ttk.Scrollbar(tab_summary, orient='vertical', command=self.summary_canvas.yview)
        self.summary_canvas.configure(yscrollcommand=self.summary_vsb.set)
        self.summary_canvas.pack(side='left', fill='both', expand=True)
        self.summary_vsb.pack(side='right', fill='y')
        self.summary_inner = tk.Frame(self.summary_canvas, bg=self.BRAND_LIGHT)
        self.summary_window = self.summary_canvas.create_window((0, 0), window=self.summary_inner, anchor='nw')
        def _sum_on_inner_configure(event=None):
            try:
                self.summary_canvas.configure(scrollregion=self.summary_canvas.bbox('all'))
            except Exception:
                pass
        def _sum_on_canvas_configure(event):
            try:
                self.summary_canvas.itemconfigure(self.summary_window, width=event.width)
            except Exception:
                pass
        self.summary_inner.bind('<Configure>', _sum_on_inner_configure)
        self.summary_canvas.bind('<Configure>', _sum_on_canvas_configure)
        self._bind_summary_scroll_events()
        # Graphs tab
        tab_graph = tk.Frame(nb, bg=self.BRAND_LIGHT)
        nb.add(tab_graph, text='Graphs')
        graph_container = tk.Frame(tab_graph, bg=self.BRAND_LIGHT)
        graph_container.pack(fill='both', expand=True, padx=6, pady=6)
        self.graph_canvas = tk.Canvas(graph_container, bg=self.BRAND_LIGHT, highlightthickness=0)
        graph_vsb = ttk.Scrollbar(graph_container, orient='vertical', command=self.graph_canvas.yview)
        self.graph_canvas.configure(yscrollcommand=graph_vsb.set)
        self.graph_canvas.pack(side='left', fill='both', expand=True)
        graph_vsb.pack(side='right', fill='y')
        self.graph_body = tk.Frame(self.graph_canvas, bg=self.BRAND_LIGHT)
        self.graph_canvas_window = self.graph_canvas.create_window((0, 0), window=self.graph_body, anchor='nw')

        def _graph_on_body_config(event):
            try:
                self.graph_canvas.configure(scrollregion=self.graph_canvas.bbox('all'))
            except Exception:
                pass

        def _graph_on_canvas_config(event):
            try:
                self.graph_canvas.itemconfigure(self.graph_canvas_window, width=event.width)
            except Exception:
                pass

        self.graph_body.bind('<Configure>', _graph_on_body_config)
        self.graph_canvas.bind('<Configure>', _graph_on_canvas_config)
        self._bind_graph_scroll_events()

        def add_chart(title: str, height: int):
            wrapper = tk.Frame(self.graph_body, bg=self.BRAND_LIGHT)
            wrapper.pack(fill='x', expand=True, pady=(0, 16))
            lbl = tk.Label(wrapper, text=title, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK, font=('Segoe UI', 10, 'bold'))
            lbl.pack(anchor='w', pady=(0, 6))
            canvas = tk.Canvas(wrapper, height=height, bg=self.BRAND_SURFACE, highlightthickness=1,
                               highlightbackground=self.BRAND_OUTLINE, borderwidth=0)
            canvas.pack(fill='both', expand=True)
            return canvas

        self.power_canvas = add_chart('Power & Torque', 330)
        self.gear_canvas = add_chart('Gearing Ratios', 260)
        self.chassis_canvas = add_chart('Chassis Balance', 420)
        self.tyre_canvas = add_chart('Tyre Footprint', 260)
        self.graph_canvases = {
            'power': self.power_canvas,
            'gear': self.gear_canvas,
            'chassis': self.chassis_canvas,
            'tyre': self.tyre_canvas,
        }
        for key, canvas in self.graph_canvases.items():
            try:
                canvas.bind('<Configure>', lambda e, k=key: self._on_graph_resize(k, e))
            except Exception:
                pass
        # Anti-Cheat tab
        tab_ac = tk.Frame(nb, bg=self.BRAND_LIGHT)
        nb.add(tab_ac, text='Anti-Cheat')
        # Filters bar
        bar = tk.Frame(tab_ac, bg=self.BRAND_LIGHT)
        bar.pack(fill='x', padx=6, pady=(6,0))
        tk.Label(bar, text='Filter:', bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).pack(side='left')
        self.ac_filter_var = tk.StringVar(value='all')
        for v, lbl in (('all','All'), ('warn','Warn'), ('fail','Fail')):
            ttk.Radiobutton(bar, text=lbl, variable=self.ac_filter_var, value=v, command=lambda: self.populate_anti_cheat(getattr(self,'last_result',None))).pack(side='left', padx=(6,0))
        tk.Label(bar, text='Search:', bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).pack(side='left', padx=(12,0))
        self.ac_search_var = tk.StringVar(value='')
        ent = ttk.Entry(bar, textvariable=self.ac_search_var, width=24)
        ent.pack(side='left', padx=(4,0))
        ent.bind('<KeyRelease>', lambda e: self.populate_anti_cheat(getattr(self,'last_result',None)))
        # Summary banner
        self.ac_summary_var = tk.StringVar(value='Run Inspect to populate anti-cheat checks.')
        self.ac_summary_frame = tk.Frame(tab_ac, bg=self.BRAND_LIGHT, highlightthickness=0)
        self.ac_summary_frame.pack(fill='x', padx=6, pady=(4,0))
        self.ac_summary_label = tk.Label(self.ac_summary_frame, textvariable=self.ac_summary_var, anchor='w',
                                         font=('Segoe UI', 10, 'bold'), bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK,
                                         padx=12, pady=6, wraplength=760, justify='left')
        self.ac_summary_label.pack(fill='x')
        # Log area
        self.ac_text = tk.Text(tab_ac, wrap='char', bg='white', fg=self.BRAND_BLACK,
                               font=('Segoe UI', 10))
        ac_vsb = ttk.Scrollbar(tab_ac, orient='vertical', command=self.ac_text.yview)
        self.ac_text.configure(yscrollcommand=ac_vsb.set)
        self.ac_text.pack(side='left', fill='both', expand=True, padx=6, pady=6)
        ac_vsb.pack(side='right', fill='y', padx=(0,6), pady=6)
        self.ac_text.tag_configure('row_fail', background='#FDECEA', foreground='#8B1A1A')
        self.ac_text.tag_configure('row_warn', background='#FFF7ED', foreground='#8B5E00')
        self.ac_text.tag_configure('row_pass', background='#F1F8E9', foreground='#1B5E20')
        self.ac_text.tag_configure('status_fail', foreground='#D93025', font=('Segoe UI', 10, 'bold'))
        self.ac_text.tag_configure('status_warn', foreground=self.BRAND_ORANGE, font=('Segoe UI', 10, 'bold'))
        self.ac_text.tag_configure('status_pass', foreground='#188038', font=('Segoe UI', 10, 'bold'))
        self.ac_text.tag_configure('detail_text', font=('Segoe UI', 9))
        # Context menu for anti-cheat log
        self.ac_menu = tk.Menu(self, tearoff=0)
        self.ac_menu.add_command(label='Copy', command=lambda: self.ac_text.event_generate('<<Copy>>'))
        def _ac_popup(e):
            try:
                self.ac_menu.tk_popup(e.x_root, e.y_root)
            finally:
                self.ac_menu.grab_release()
        self.ac_text.bind('<Button-3>', _ac_popup)
        # (Removed dedicated Preview tab per request)
        # Car Info tab
        tab_info = tk.Frame(nb, bg=self.BRAND_LIGHT)
        nb.add(tab_info, text='Car Info')
        # Side-by-side: preview (left) and info (right)
        self.preview_label = tk.Label(tab_info, bg=self.BRAND_LIGHT)
        self.preview_label.grid(row=0, column=0, sticky='nw', padx=6, pady=(6,6))
        self.info_txt = tk.Text(tab_info, wrap='char', bg='white', fg=self.BRAND_BLACK,
                                font=self.base_font)
        info_vsb = ttk.Scrollbar(tab_info, orient='vertical', command=self.info_txt.yview)
        self.info_txt.configure(yscrollcommand=info_vsb.set)
        self.info_txt.grid(row=0, column=1, sticky='nsew', padx=(6,6), pady=(6,6))
        info_vsb.grid(row=0, column=2, sticky='ns', padx=(0,6), pady=(6,6))
        tab_info.rowconfigure(0, weight=1)
        tab_info.columnconfigure(1, weight=1)

        # Status
        self.status = tk.StringVar(value='Ready')
        tk.Label(self, textvariable=self.status, anchor='w', bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK, font=self.base_font).grid(row=7, column=0, sticky='ew', **pad)
        # Apply defaults for initial ruleset
        self.apply_ruleset()
        # Hide the in-pane Options & Rules to declutter; use Rules -> Settings instead
        try:
            if hasattr(self, 'options_frame'):
                self.options_frame.grid_remove()
            if hasattr(self, 'ref_frame'):
                self.ref_frame.grid_remove()
        except Exception:
            pass
        # Shortcuts
        self.bind_all('<Control-o>', lambda e: self.browse_car())
        self.bind_all('<Control-i>', lambda e: self.inspect())
        self.bind_all('<Control-e>', lambda e: self.export_html())
        self.bind_all('<Control-l>', lambda e: self.clear_preview())
        self.bind_all('<Control-=>', lambda e: self.adjust_zoom(+0.1))
        self.bind_all('<Control-minus>', lambda e: self.adjust_zoom(-0.1))

    def adjust_zoom(self, delta: float):
        try:
            self.ui_scale = max(0.8, min(1.6, self.ui_scale + delta))
            self.tk.call('tk', 'scaling', self.ui_scale)
        except Exception:
            pass

    def _on_close(self):
        try:
            if getattr(self, '_temp_car_extract', None):
                shutil.rmtree(self._temp_car_extract, ignore_errors=True)
                self._temp_car_extract = None
            self._source_archive = None
        except Exception:
            pass
        self.destroy()

    def _queue_auth_status(self, message: str) -> None:
        self.after(0, lambda: self._handle_auth_status(message))

    def _handle_auth_status(self, message: str) -> None:
        try:
            self.status.set(message)
        except Exception:
            pass
        if message.lower().startswith('authenticated as'):
            self.hide_join_prompt()
        self.update_auth_ui()

    def update_auth_ui(self, *, trigger_index: bool = True) -> None:
        was_authed = self._last_authed
        authed = bool(self.auth and self.auth.is_authenticated)
        if authed:
            user = self.auth.current_user or 'Authenticated'
            self.auth_user_var.set(f'Logged in as {user}')
            self.login_btn.configure(text='Logout', command=self.logout)
            self.hide_join_prompt()
            if self._login_prompt_window and self._login_prompt_window.winfo_exists():
                try:
                    self._login_prompt_window.destroy()
                except Exception:
                    pass
                self._login_prompt_window = None
        else:
            if not self._join_prompt_active:
                self.auth_user_var.set('Not authenticated')
            self.login_btn.configure(text='Login with Discord', command=self.start_login_flow)
        self._update_action_buttons_state()
        self._last_authed = authed
        if trigger_index:
            self._maybe_build_index()
        if authed and not was_authed:
            self._maybe_run_pending_auto_inspect()

    def _update_action_buttons_state(self) -> None:
        enabled = bool(self.auth and self.auth.is_authenticated and not self._busy)
        for btn in getattr(self, 'action_buttons', []):
            try:
                if enabled:
                    btn.state(['!disabled'])
                else:
                    btn.state(['disabled'])
            except Exception:
                pass
        if self.join_button.winfo_manager():
            if auth_config.DISCORD_INVITE_URL:
                self.join_button.configure(state='normal')
            else:
                self.join_button.configure(state='disabled')

    def _maybe_build_index(self) -> None:
        if not (self.auth and self.auth.is_authenticated):
            return
        if self.index_built or self._building_index:
            return
        if self._busy:
            self.after(500, self._maybe_build_index)
            return
        self.build_index()

    def _launch_initial_login(self) -> None:
        if self.auth and self.auth.is_authenticated:
            self._maybe_build_index()
            return
        if self._initial_login_prompt_shown:
            return
        self._initial_login_prompt_shown = True
        try:
            tl = tk.Toplevel(self)
            tl.title('Discord Login Required')
            tl.configure(bg=self.BRAND_LIGHT)
            self._center_modal(tl, 420, 180)
            msg = ('To use eF Drift Car Scrutineer you must sign in with Discord.\n'
                   'We will open the login window for you now.')
            tk.Label(tl, text=msg, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK,
                     font=self.base_font, justify='left', wraplength=380).pack(fill='both', expand=True, padx=16, pady=(16, 8))
            btns = tk.Frame(tl, bg=self.BRAND_LIGHT)
            btns.pack(fill='x', padx=16, pady=(0, 12))

            def close():
                try:
                    tl.destroy()
                except Exception:
                    pass
                if self._login_prompt_window is tl:
                    self._login_prompt_window = None

            ttk.Button(btns, text='Close', command=close, style='Neutral.TButton').pack(side='right')
            self._login_prompt_window = tl
        except Exception:
            self._login_prompt_window = None

        def auto_login():
            if self.auth and not self.auth.is_authenticated:
                self.start_login_flow()

        self.after(400, auto_login)

    def _handle_auth_failure(self, message: str) -> None:
        msg_lower = message.lower()
        if 'join the authorized discord server' in msg_lower:
            self.show_join_prompt('Discord membership required to continue.')
        elif 'required discord role' in msg_lower:
            role_id = auth_config.PRIMARY_DISCORD_ROLE_ID
            self.show_join_prompt(f'Required competition role missing (ID {role_id}).')
        elif 'status 403' in msg_lower:
            self.show_join_prompt('Access denied (HTTP 403). Ensure you are in the server and have the required role.')
        else:
            self.hide_join_prompt()
        self.status.set(message)

    def _format_auth_error(self, raw_msg: str) -> str:
        msg_lower = raw_msg.lower()
        if ('join the authorized discord server' in msg_lower or
                'required discord role' in msg_lower or
                'status 403' in msg_lower):
            return f"{self.join_help_text}\n\nIf you've already joined, DM xtreme for access.\n\n(Details: {raw_msg})"
        return raw_msg

    def show_join_prompt(self, reason: str = '') -> None:
        self._join_prompt_active = True
        message = self.join_help_text if not reason else f"{reason}\n{self.join_help_text}"
        self.auth_user_var.set(message)
        invite_url = auth_config.DISCORD_INVITE_URL
        if invite_url:
            self.join_button.configure(state='normal')
        else:
            self.join_button.configure(state='disabled')
        if not self.join_button.winfo_manager():
            self.join_button.pack(anchor='e', pady=(4, 0))

    def hide_join_prompt(self) -> None:
        if self.join_button.winfo_manager():
            self.join_button.pack_forget()
        self._join_prompt_active = False
        if not (self.auth and self.auth.is_authenticated):
            self.auth_user_var.set('Not authenticated')

    def open_join_link(self) -> None:
        invite_url = auth_config.DISCORD_INVITE_URL
        if invite_url:
            try:
                webbrowser.open(invite_url)
            except Exception as e:
                messagebox.showerror('Discord', f'Failed to open invite link: {e}')
        else:
            messagebox.showinfo('Discord', 'Invite link is not configured. Please contact an administrator or DM xtreme.')

    def start_login_flow(self) -> None:
        if not self.auth:
            messagebox.showerror('Authentication', 'Authentication manager not initialised.')
            return
        if self._busy:
            return

        self._set_busy(True)
        self.login_btn.state(['disabled'])

        def run():
            try:
                info = self.auth.login()
                self.after(0, lambda: self.status.set(f"Welcome {info.get('username')}"))
            except AuthError as e:
                msg = str(e)
                def fail():
                    self._handle_auth_failure(msg)
                    messagebox.showerror('Authentication', self._format_auth_error(msg))
                self.after(0, fail)
            except Exception as e:
                tb = traceback.format_exc()
                msg = f'Login failed: {e}\n\n{tb}'
                self.after(0, lambda: messagebox.showerror('Authentication', msg))
            finally:
                self.after(0, self._login_flow_complete)

        threading.Thread(target=run, daemon=True).start()

    def _login_flow_complete(self) -> None:
        self.login_btn.state(['!disabled'])
        self._set_busy(False)
        self.update_auth_ui()

    def logout(self) -> None:
        if self.auth:
            self.auth.logout()
        self.status.set('Logged out')
        self.index_built = False
        self.update_auth_ui()
        self.hide_join_prompt()

    def _ensure_authenticated(self) -> bool:
        if not self.auth:
            messagebox.showerror('Authentication', 'Authentication manager not initialised.')
            return False
        try:
            self.auth.require_authenticated()
            self.update_auth_ui(trigger_index=False)
            return True
        except AuthError as e:
            msg = str(e)
            self._handle_auth_failure(msg)
            messagebox.showerror('Authentication required', self._format_auth_error(msg))
            self.update_auth_ui(trigger_index=False)
            return False

    def open_folder(self):
        try:
            car = Path(self.car_var.get())
            if not car.exists():
                return
            import platform, subprocess, os
            sys = platform.system()
            if sys == 'Windows':
                os.startfile(str(car))  # type: ignore
            elif sys == 'Darwin':
                subprocess.Popen(['open', str(car)])
            else:
                subprocess.Popen(['xdg-open', str(car)])
        except Exception:
            pass

    # Drag-and-drop removed per request; selection is via Browse button

    def apply_ruleset(self):
        # Apply fixed competition defaults
        self.enf_mass_var.set(True); self.min_mass_var.set('1300')
        self.enf_cg_var.set(True); self.cg_var.set('0.52')
        self.enf_rear_tyre_var.set(True); self.rear_tyre_var.set('265')
        self.enf_front_tyre_var.set(True); self.front_tyre_lo_var.set('225'); self.front_tyre_hi_var.set('265')
        self.enf_steer_var.set(True); self.steer_max_var.set('70'); self.require_cm_var.set(False)
        self.enf_assets_var.set(True); self.max_kn5_mb_var.set('60'); self.max_skin_mb_var.set('30')
        self.enf_model_var.set(True); self.max_tris_var.set('500000'); self.max_objs_var.set('300'); self.require_ks_var.set(False)
        self.enf_rwd_var.set(True); self.enf_year_var.set(True); self.min_year_var.set('1965'); self.e92_fallback_var.set(True)

    def browse_ref(self):
        # Select a new reference folder
        path = filedialog.askdirectory(title='Select reference_cars folder', initialdir=str(Path.cwd()))
        if path:
            self.state.reference_root = Path(path)
            if hasattr(self, 'ref_path_var'):
                self.ref_path_var.set(str(self.state.reference_root))
            if messagebox.askyesno('Rebuild Index', 'Reference changed. Rebuild reference index now?'):
                self.build_index()
            else:
                self.status.set('Reference changed; index rebuild pending')

    def browse_car(self):
        dialog = tk.Toplevel(self)
        dialog.title('Select Car Source')
        dialog.configure(bg=self.BRAND_LIGHT)
        dialog.resizable(False, False)
        tk.Label(dialog, text='How would you like to load the submitted car?',
                 font=('Segoe UI', 10, 'bold'), bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK,
                 padx=12, pady=10).pack(fill='x')
        choice = {'value': None}

        def _set_choice(val: str):
            choice['value'] = val
            dialog.destroy()

        btn_frame = tk.Frame(dialog, bg=self.BRAND_LIGHT)
        btn_frame.pack(padx=12, pady=12, fill='x')
        ttk.Button(btn_frame, text='Browse ZIP / RAR Archive', style='Primary.TButton',
                   command=lambda: _set_choice('archive')).pack(fill='x', pady=(0,6))
        ttk.Button(btn_frame, text='Browse Car Folder', style='Neutral.TButton',
                   command=lambda: _set_choice('folder')).pack(fill='x')
        dialog.update_idletasks()
        try:
            parent_x = self.winfo_rootx()
            parent_y = self.winfo_rooty()
            parent_w = self.winfo_width()
            parent_h = self.winfo_height()
        except Exception:
            parent_x = parent_y = 100
            parent_w = parent_h = 400
        width = dialog.winfo_reqwidth()
        height = dialog.winfo_reqheight()
        pos_x = parent_x + (parent_w - width) // 2
        pos_y = parent_y + (parent_h - height) // 2
        dialog.geometry(f"{width}x{height}+{max(pos_x, 50)}+{max(pos_y, 50)}")
        dialog.transient(self)
        dialog.grab_set()
        self.wait_window(dialog)
        if choice['value'] == 'archive':
            selected = filedialog.askopenfilename(
                title='Select submitted car archive (ZIP/RAR)',
                initialdir=str(Path.cwd()),
                filetypes=[
                    ('Car archives', '*.zip *.rar'),
                    ('ZIP archives', '*.zip'),
                    ('RAR archives', '*.rar'),
                    ('All files', '*.*'),
                ]
            )
            if not selected:
                return
            sel_path = Path(selected)
            car_path = self._extract_archive(sel_path)
            if not car_path:
                return
        else:
            if choice['value'] != 'folder':
                return
            folder = filedialog.askdirectory(title='Select submitted car folder', initialdir=str(Path.cwd()))
            if not folder:
                return
            car_path = Path(folder)
            if getattr(self, '_temp_car_extract', None):
                shutil.rmtree(self._temp_car_extract, ignore_errors=True)
                self._temp_car_extract = None
            self._source_archive = None
        if not car_path.exists() or not car_path.is_dir():
            messagebox.showerror('Select Car', 'Please select a valid car folder or supported archive (ZIP/RAR).')
            return
        self.car_var.set(str(car_path))
        try:
            self.populate_car_info(car_path)
            self.update_report_header(car_path, None)
        except Exception:
            pass
        self._schedule_auto_inspect(car_path)

    def _schedule_auto_inspect(self, car: Path) -> None:
        if self._auto_inspect_job is not None:
            try:
                self.after_cancel(self._auto_inspect_job)
            except Exception:
                pass
            self._auto_inspect_job = None

        try:
            target = car.resolve()
        except Exception:
            target = car
        self._pending_auto_inspect = target

        def _run() -> None:
            current_raw = self.car_var.get()
            if not current_raw:
                self._auto_inspect_job = None
                return
            try:
                current = Path(current_raw).resolve()
            except Exception:
                current = Path(current_raw)
            if current != target:
                self._auto_inspect_job = None
                return
            if self._busy:
                self._auto_inspect_job = self.after(300, _run)
                return
            self._auto_inspect_job = None
            self.inspect(auto_trigger=True)

        if not self._busy:
            try:
                self.status.set('Preparing inspection...')
            except Exception:
                pass
        self._auto_inspect_job = self.after(150, _run)

    def _get_reference_entry(self, key: str | None):
        if not key:
            return None
        cache = self._reference_index_cache
        if isinstance(cache, dict):
            return cache.get(key)
        return None

    def _refresh_reference_data(self,
                                *,
                                need_fingerprints: bool = True,
                                save_to_disk: bool = True) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """
        Rebuild reference summaries directly from the reference root.
        Returns (index, fingerprints?) ensuring comparisons use fresh data.
        """
        ref_root = Path(self.state.reference_root)
        try:
            ref_root = ref_root.resolve()
        except Exception:
            pass
        index = build_reference_index(ref_root)
        fingerprints = build_fingerprint_index(ref_root) if need_fingerprints else None
        self._reference_index_cache = index
        if save_to_disk:
            try:
                save_index(index, self.state.index_path)
            except Exception:
                pass
            if fingerprints is not None:
                try:
                    save_index(fingerprints, self.state.fingerprints_path)
                except Exception:
                    pass
        return index, fingerprints

    def _maybe_run_pending_auto_inspect(self) -> None:
        if self._pending_auto_inspect is None:
            return
        current_raw = self.car_var.get()
        if not current_raw:
            self._pending_auto_inspect = None
            return
        try:
            current = Path(current_raw).resolve()
        except Exception:
            current = Path(current_raw)
        if current != self._pending_auto_inspect:
            self._pending_auto_inspect = None
            return
        if self._auto_inspect_job is not None:
            return
        self._schedule_auto_inspect(current)

    def _set_busy(self, busy: bool):
        self.config(cursor='watch' if busy else '')
        self._busy = busy
        self.update_idletasks()
        self._update_action_buttons_state()

    def attach_tooltip(self, widget, text: str):
        if not text:
            return
        tip = {'tl': None}
        def _show(_e=None):
            try:
                if tip['tl'] is not None:
                    return
                tl = tk.Toplevel(widget)
                tip['tl'] = tl
                tl.wm_overrideredirect(True)
                tl.configure(bg=self.BRAND_LIGHT)
                x = widget.winfo_rootx() + 10
                y = widget.winfo_rooty() + widget.winfo_height() + 5
                tl.wm_geometry(f"+{x}+{y}")
                lb = tk.Label(tl, text=text, bg='#FFFFE0', fg='#000', relief='solid', borderwidth=1,
                              font=('Segoe UI', 9), justify='left')
                lb.pack(ipadx=6, ipady=3)
            except Exception:
                pass
        def _hide(_e=None):
            try:
                if tip['tl'] is not None:
                    tip['tl'].destroy()
                    tip['tl'] = None
            except Exception:
                pass
        widget.bind('<Enter>', _show)
        widget.bind('<Leave>', _hide)

    def attach_hover_outline(self, widget):
        try:
            widget.configure(highlightthickness=0, highlightbackground=self.BRAND_NAVY)
        except Exception:
            return
        def _enter(_e=None):
            try:
                widget.configure(highlightthickness=1)
            except Exception:
                pass
        def _leave(_e=None):
            try:
                widget.configure(highlightthickness=0)
            except Exception:
                pass
        widget.bind('<Enter>', _enter)
        widget.bind('<Leave>', _leave)

    def _build_menu(self):
        try:
            m = tk.Menu(self)
            # File menu
            mf = tk.Menu(m, tearoff=0)
            mf.add_command(label='Select Reference Folder...', command=self.browse_ref)
            mf.add_command(label='Rebuild Index', command=self.build_index)
            mf.add_separator()
            mf.add_command(label='Exit', command=self.destroy)
            m.add_cascade(label='File', menu=mf)
            # Rules menu
            mr = tk.Menu(m, tearoff=0)
            mr.add_command(label='Settings...', command=self.open_settings_dialog)
            m.add_cascade(label='Rules', menu=mr)
            # Help menu
            mh = tk.Menu(m, tearoff=0)
            mh.add_command(label='Check for Updates…', command=self.menu_check_updates)
            m.add_cascade(label='Help', menu=mh)
            self.config(menu=m)
        except Exception:
            pass

    def menu_check_updates(self):
        try:
            ch = None
            try:
                ch = self.update_channel_var.get()
            except Exception:
                ch = None
            updater.check_for_update_synchronously(self, manual=True, channel=ch)
        except Exception:
            try:
                messagebox.showinfo('Update', 'Update check failed.')
            except Exception:
                pass

    def load_settings(self):
        try:
            p = self.state.settings_path
            if not p.exists():
                return
            import json
            data = json.loads(p.read_text(encoding='utf-8', errors='ignore'))
            # Map JSON to vars
            def setb(var, key):
                if key in data:
                    var.set(bool(data[key]))
            def sets(var, key):
                if key in data:
                    var.set(str(data[key]))
            setb(self.enf_mass_var, 'enf_mass'); sets(self.min_mass_var, 'min_mass')
            setb(self.enf_cg_var, 'enf_cg'); sets(self.cg_var, 'cg')
            setb(self.enf_rear_tyre_var, 'enf_rear'); sets(self.rear_tyre_var, 'rear_tyre')
            setb(self.enf_front_tyre_var, 'enf_front'); sets(self.front_tyre_lo_var, 'front_lo'); sets(self.front_tyre_hi_var, 'front_hi')
            setb(self.enf_steer_var, 'enf_steer'); sets(self.steer_max_var, 'steer_max'); setb(self.require_cm_var, 'require_cm')
            setb(self.enf_assets_var, 'enf_assets'); sets(self.max_kn5_mb_var, 'max_kn5'); sets(self.max_skin_mb_var, 'max_skin')
            setb(self.enf_model_var, 'enf_model'); sets(self.max_tris_var, 'max_tris'); sets(self.max_objs_var, 'max_objs'); setb(self.require_ks_var, 'require_ks')
            setb(self.enf_rwd_var, 'enf_rwd'); setb(self.enf_year_var, 'enf_year'); sets(self.min_year_var, 'min_year'); setb(self.e92_fallback_var, 'e92')
            # Updater
            sets(self.update_channel_var, 'update_channel')
        except Exception:
            pass

    def save_settings(self):
        try:
            import json
            data = {
                'enf_mass': self.enf_mass_var.get(), 'min_mass': self.min_mass_var.get(),
                'enf_cg': self.enf_cg_var.get(), 'cg': self.cg_var.get(),
                'enf_rear': self.enf_rear_tyre_var.get(), 'rear_tyre': self.rear_tyre_var.get(),
                'enf_front': self.enf_front_tyre_var.get(), 'front_lo': self.front_tyre_lo_var.get(), 'front_hi': self.front_tyre_hi_var.get(),
                'enf_steer': self.enf_steer_var.get(), 'steer_max': self.steer_max_var.get(), 'require_cm': self.require_cm_var.get(),
                'enf_assets': self.enf_assets_var.get(), 'max_kn5': self.max_kn5_mb_var.get(), 'max_skin': self.max_skin_mb_var.get(),
                'enf_model': self.enf_model_var.get(), 'max_tris': self.max_tris_var.get(), 'max_objs': self.max_objs_var.get(), 'require_ks': self.require_ks_var.get(),
                'enf_rwd': self.enf_rwd_var.get(), 'enf_year': self.enf_year_var.get(), 'min_year': self.min_year_var.get(), 'e92': self.e92_fallback_var.get(),
                'update_channel': getattr(self, 'update_channel_var', None).get() if hasattr(self, 'update_channel_var') else 'stable',
            }
            self.state.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.state.settings_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
            self.status.set('Settings saved')
        except Exception as e:
            messagebox.showerror('Settings', f'Failed to save settings: {e}')

    def open_settings_dialog(self):
        try:
            tl = tk.Toplevel(self); tl.title('Rules Settings'); tl.configure(bg=self.BRAND_LIGHT); tl.geometry('520x560')
            frm = tk.Frame(tl, bg=self.BRAND_LIGHT); frm.pack(fill='both', expand=True, padx=10, pady=10)
            # Build a compact grid of key settings
            row = 0
            def add_bool(label, var):
                nonlocal row
                tk.Checkbutton(frm, text=label, variable=var, bg=self.BRAND_LIGHT).grid(row=row, column=0, sticky='w')
                row += 1
            def add_num(label, var):
                nonlocal row
                tk.Label(frm, text=label, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).grid(row=row, column=0, sticky='w')
                ttk.Entry(frm, textvariable=var, width=12).grid(row=row, column=1, sticky='w')
                row += 1
            # Mass & CG
            add_bool('Enforce min mass', self.enf_mass_var); add_num('Min mass (kg)', self.min_mass_var)
            add_bool('Enforce front bias CG_LOCATION', self.enf_cg_var); add_num('Front bias (0.xx)', self.cg_var)
            # Tyres
            add_bool('Enforce rear tyre max', self.enf_rear_tyre_var); add_num('Rear tyre max (mm)', self.rear_tyre_var)
            add_bool('Enforce front tyre range', self.enf_front_tyre_var); add_num('Front min (mm)', self.front_tyre_lo_var); add_num('Front max (mm)', self.front_tyre_hi_var)
            # Steering
            add_bool('Enforce steering angle cap', self.enf_steer_var); add_num('Max angle (deg)', self.steer_max_var); add_bool('Require CM steering JSON', self.require_cm_var)
            # Assets/Model
            add_bool('Enforce assets size caps', self.enf_assets_var); add_num('KN5 max (MB)', self.max_kn5_mb_var); add_num('Skin max (MB)', self.max_skin_mb_var)
            add_bool('Enforce model caps', self.enf_model_var); add_num('Max triangles', self.max_tris_var); add_num('Max objects', self.max_objs_var); add_bool('Require KN5 stats JSON', self.require_ks_var)
            # Misc
            add_bool('Enforce RWD', self.enf_rwd_var); add_bool('Enforce Year >=', self.enf_year_var); add_num('Min year', self.min_year_var); add_bool('Allow E92 fallback', self.e92_fallback_var)
            # Updates
            try:
                tk.Label(frm, text='Update channel', bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK).grid(row=row, column=0, sticky='w')
                from tkinter import ttk as _ttk
                _ttk.Combobox(frm, values=['stable','beta'], textvariable=self.update_channel_var, state='readonly', width=12).grid(row=row, column=1, sticky='w')
                row += 1
            except Exception:
                pass
            # Buttons
            bar = tk.Frame(tl, bg=self.BRAND_LIGHT); bar.pack(fill='x', padx=10, pady=(0,10))
            ttk.Button(bar, text='Save', command=lambda: (self.save_settings(), tl.destroy()), style='Success.TButton').pack(side='right')
            ttk.Button(bar, text='Cancel', command=tl.destroy, style='Neutral.TButton').pack(side='right', padx=(0,6))
        except Exception as e:
            messagebox.showerror('Settings', f'Failed to open settings: {e}')

    def _bind_summary_scroll_events(self):
        try:
            import platform
            sys = platform.system()
            def _on_mousewheel(event):
                if not self._is_widget_in_summary(event.widget):
                    return
                try:
                    if sys == 'Darwin':
                        delta = -1 * int(event.delta)
                    else:
                        delta = -1 * int(event.delta / 120)
                    self.summary_canvas.yview_scroll(delta, 'units')
                except Exception:
                    pass
            def _on_shift_mousewheel(event):
                if not self._is_widget_in_summary(event.widget):
                    return
                try:
                    if sys == 'Darwin':
                        delta = int(event.delta)
                    else:
                        delta = int(event.delta / 120)
                    self.summary_canvas.xview_scroll(-delta, 'units')
                except Exception:
                    pass
            def _on_button4(event):
                if not self._is_widget_in_summary(event.widget):
                    return
                try:
                    if event.state & 0x1:  # Shift
                        self.summary_canvas.xview_scroll(-1, 'units')
                    else:
                        self.summary_canvas.yview_scroll(-1, 'units')
                except Exception:
                    pass
            def _on_button5(event):
                if not self._is_widget_in_summary(event.widget):
                    return
                try:
                    if event.state & 0x1:
                        self.summary_canvas.xview_scroll(1, 'units')
                    else:
                        self.summary_canvas.yview_scroll(1, 'units')
                except Exception:
                    pass
            def _on_linux_up(event):
                if not self._is_widget_in_summary(event.widget):
                    return
                try:
                    self.summary_canvas.yview_scroll(-1, 'units')
                except Exception:
                    pass
            def _on_linux_down(event):
                if not self._is_widget_in_summary(event.widget):
                    return
                try:
                    self.summary_canvas.yview_scroll(1, 'units')
                except Exception:
                    pass
            # Focus canvas on enter for mousewheel to work
            self.summary_canvas.bind('<Enter>', lambda e: self.summary_canvas.focus_set())
            self.bind_all('<MouseWheel>', lambda e: _on_shift_mousewheel(e) if (e.state & 0x1) else _on_mousewheel(e))
            self.bind_all('<Button-4>', _on_button4)
            self.bind_all('<Button-5>', _on_button5)
        except Exception:
            pass

    def _bind_graph_scroll_events(self):
        try:
            import platform
            sys = platform.system()
            def _wheel(event):
                if not self._is_widget_in_graph(event.widget):
                    return
                try:
                    if sys == 'Darwin':
                        delta = -1 * int(event.delta)
                    else:
                        delta = -1 * int(event.delta / 120)
                    self.graph_canvas.yview_scroll(delta, 'units')
                except Exception:
                    pass
            def _wheel_shift(event):
                if not self._is_widget_in_graph(event.widget):
                    return
                try:
                    if sys == 'Darwin':
                        delta = int(event.delta)
                    else:
                        delta = int(event.delta / 120)
                    self.graph_canvas.xview_scroll(-delta, 'units')
                except Exception:
                    pass
            def _linux_up(event):
                if not self._is_widget_in_graph(event.widget):
                    return
                try:
                    if event.state & 0x1:
                        self.graph_canvas.xview_scroll(-1, 'units')
                    else:
                        self.graph_canvas.yview_scroll(-1, 'units')
                except Exception:
                    pass
            def _linux_down(event):
                if not self._is_widget_in_graph(event.widget):
                    return
                try:
                    if event.state & 0x1:
                        self.graph_canvas.xview_scroll(1, 'units')
                    else:
                        self.graph_canvas.yview_scroll(1, 'units')
                except Exception:
                    pass
            self.graph_canvas.bind('<Enter>', lambda _e=None: self.graph_canvas.focus_set())
            for widget in (self.graph_canvas, getattr(self, 'graph_body', None)):
                if widget is None:
                    continue
            self.bind_all('<MouseWheel>', lambda e: _wheel_shift(e) if (e.state & 0x1) else _wheel(e))
            self.bind_all('<Button-4>', _linux_up)
            self.bind_all('<Button-5>', _linux_down)
        except Exception:
            pass

    def _apply_initial_geometry(self):
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            width = min(1400, max(1100, sw - 200))
            height = min(900, max(800, sh - 200))
            x = max(0, (sw - width) // 2)
            y = max(0, (sh - height) // 2)
            self.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            try:
                self.geometry('1280x840')
            except Exception:
                pass

    def _on_graph_resize(self, key: str, event):
        try:
            w = int(event.width)
            h = int(event.height)
        except Exception:
            return
        if w <= 0 or h <= 0:
            return
        current = self._graph_canvas_sizes.get(key)
        if current == (w, h):
            return
        self._graph_canvas_sizes[key] = (w, h)
        self._queue_graph_redraw()

    def _queue_graph_redraw(self):
        if self._graph_redraw_pending:
            return
        self._graph_redraw_pending = True
        try:
            self.after(100, self._redraw_graphs)
        except Exception:
            self._graph_redraw_pending = False

    def _redraw_graphs(self):
        self._graph_redraw_pending = False
        state = getattr(self, '_graph_state', None)
        if not state:
            return
        car_str = state.get('car')
        if not car_str:
            return
        car_path = Path(car_str)
        if not car_path.exists():
            return
        result_obj = state.get('result') or getattr(self, 'last_result', None)
        info = state.get('info')
        if not info and getattr(result_obj, 'info', None):
            info = result_obj.info
        if not isinstance(info, dict):
            info = {}
        ref_entry = None
        if result_obj is not None:
            ref_entry = self._get_reference_entry(getattr(result_obj, 'matched_reference', None))
        self._draw_power_chart(self.power_canvas, car_path, result_obj, ref_entry, preview=False)
        self._draw_gear_chart(self.gear_canvas, car_path, info, ref_entry)
        self._draw_chassis_chart(self.chassis_canvas, info, ref_entry)
        self._draw_tyre_chart(self.tyre_canvas, info, ref_entry)

    def _maximize_window(self):
        try:
            # Windows / some platforms
            self.state('zoomed')
            return
        except Exception:
            pass
        try:
            # Some X11 window managers
            self.attributes('-zoomed', True)
            return
        except Exception:
            pass
        try:
            # Fallback: set to screen size
            w = self.winfo_screenwidth()
            h = self.winfo_screenheight()
            self.geometry(f"{w}x{h}+0+0")
        except Exception:
            pass

    def _center_modal(self, tl: tk.Toplevel, width: int, height: int):
        try:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = max(0, int((sw - width) / 2))
            y = max(0, int((sh - height) / 2))
            tl.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            try:
                tl.geometry(f"{width}x{height}")
            except Exception:
                pass

    def build_index(self):
        if not self._ensure_authenticated():
            return
        if self._busy:
            return
        if self._building_index:
            return
        self._building_index = True
        self._set_busy(True)
        self.status.set('Building reference index ...')

        def run():
            try:
                ref = Path(self.state.reference_root).resolve()
                idx = build_reference_index(ref)
                save_index(idx, self.state.index_path)
                fp = build_fingerprint_index(ref)
                save_index(fp, self.state.fingerprints_path)
                self._reference_index_cache = idx
                self.index_built = True
                self.after(0, lambda: self.status.set('Index built OK'))
            except Exception as e:
                tb = traceback.format_exc()
                def show_error():
                    self.status.set('Index build failed')
                    messagebox.showerror('Error', f'Index build failed:\n{e}\n\n{tb}')
                self.after(0, show_error)
            finally:
                self._building_index = False
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=run, daemon=True).start()

    def inspect(self, *, auto_trigger: bool = False):
        current_path: Path | None = None
        try:
            if self.car_var.get():
                current_path = Path(self.car_var.get()).resolve()
        except Exception:
            try:
                current_path = Path(self.car_var.get())
            except Exception:
                current_path = None
        if auto_trigger and current_path is not None:
            self._pending_auto_inspect = current_path
        if not self._ensure_authenticated():
            if auto_trigger and self.auth and not getattr(self.auth, 'is_authenticated', False):
                self.status.set('Waiting for authentication to inspect...')
            return
        if self._busy:
            if auto_trigger:
                self.status.set('Inspection queued; waiting for current task...')
            return
        self._set_busy(True)
        # Ensure we rebuild reference cache for this run
        self._reference_index_cache = None
        def run():
            try:
                car = Path(self.car_var.get()).resolve()
                name = car.name
                # Build RulebookConfig from toggles
                def to_int(v, default=None):
                    try:
                        return int(float(v))
                    except Exception:
                        return default
                def to_float(v, default=None):
                    try:
                        return float(str(v).replace(',', '.'))
                    except Exception:
                        return default
                import os
                cm_cmd_env = os.getenv('CM_STEER_CMD') or 'powershell -ExecutionPolicy Bypass -File .\\tools\\scripts\\cm_steer_from_ini.ps1 -Car "{car}" -Out "{out}"'
                ks_cmd_env = os.getenv('KS_STATS_CMD') or 'powershell -ExecutionPolicy Bypass -File .\\tools\\scripts\\ks_stats_from_ui.ps1 -Car "{car}" -Out "{out}"'
                rb = RulebookConfig(
                    enforce_body_types=False,
                    min_year=to_int(self.min_year_var.get(), 1965) if self.enf_year_var.get() else 0,
                    enforce_rwd=self.enf_rwd_var.get(),
                    enforce_front_engine=False,
                    min_total_mass_kg=to_float(self.min_mass_var.get()) if self.enf_mass_var.get() else None,
                    enforce_front_bias=to_float(self.cg_var.get()) if self.enf_cg_var.get() else None,
                    enforce_rear_tyre_max_mm=to_int(self.rear_tyre_var.get()) if self.enf_rear_tyre_var.get() else None,
                    enforce_front_tyre_range_mm=(to_int(self.front_tyre_lo_var.get()), to_int(self.front_tyre_hi_var.get())) if self.enf_front_tyre_var.get() else None,
                    max_kn5_mb=to_int(self.max_kn5_mb_var.get()) if self.enf_assets_var.get() else None,
                    max_skin_mb=to_int(self.max_skin_mb_var.get()) if self.enf_assets_var.get() else None,
                    max_triangles=to_int(self.max_tris_var.get()) if self.enf_model_var.get() else None,
                    max_objects=to_int(self.max_objs_var.get()) if self.enf_model_var.get() else None,
                    max_steer_angle_deg=to_float(self.steer_max_var.get()) if self.enf_steer_var.get() else None,
                    require_cm_steer_file=self.require_cm_var.get(),
                    require_kn5_stats_file=self.require_ks_var.get(),
                    cm_steer_cmd=cm_cmd_env if self.require_cm_var.get() else None,
                    ks_stats_cmd=ks_cmd_env if self.require_ks_var.get() else None,
                    fallback_reference_key='vdc_bmw_e92_public' if self.e92_fallback_var.get() else None,
                )
                # Refresh reference data to ensure comparisons use live specs
                idx, fps = self._refresh_reference_data(need_fingerprints=True)
                if fps is None:
                    fps = {}
                # Validate
                result = validate_submitted_car(car, fps, idx, rb)
                path = save_report(result, self.state.report_dir, name, to_json=self.json_var.get())
                report_text = Path(path).read_text(encoding='utf-8', errors='ignore')
                # Schedule UI updates on main thread
                def apply():
                    try:
                        self.status.set(f'Report saved: {path}')
                        self.render_report_text(report_text)
                        self.last_report_path = Path(path)
                        jp = self.last_report_path.with_suffix('.json')
                        self.last_report_json_path = jp if jp.exists() else None
                        self.last_result = result
                        self.draw_graphs(car, result=result)
                        self.populate_car_info(car)
                        self.update_report_header(car, result)
                        self.populate_summary(result)
                        self.populate_anti_cheat(result)
                        # Update PASS/FAIL banner
                        overall_ok = result.exact_physics_match and not result.rule_violations
                        self.update_pass_indicator(overall_ok)
                        # Append to history
                        try:
                            hist = self.state.report_dir / 'history.jsonl'
                            import json, datetime as _dt
                            row = {
                                'ts': _dt.datetime.utcnow().isoformat() + 'Z',
                                'car': car.name,
                                'report': str(path),
                                'matched_reference': result.matched_reference,
                                'exact_physics_match': result.exact_physics_match,
                                'violations': result.rule_violations,
                            }
                            hist.parent.mkdir(parents=True, exist_ok=True)
                            with hist.open('a', encoding='utf-8') as f:
                                f.write(json.dumps(row) + "\n")
                        except Exception:
                            pass
                    except Exception:
                        pass
                    finally:
                        self._set_busy(False)
                        if auto_trigger:
                            self._pending_auto_inspect = None
                self.after(0, apply)
            except Exception as e:
                tb = traceback.format_exc()
                err = e
                def show_err(err=err, tb_text=tb):
                    self.status.set('Inspect failed')
                    messagebox.showerror('Error', f'Inspect failed:\n{err}\n\n{tb_text}')
                    self._set_busy(False)
                    if auto_trigger:
                        self._pending_auto_inspect = None
                self.after(0, show_err)
        # Start worker
        self._set_busy(True)
        self.status.set('Validating ...')
        threading.Thread(target=run, daemon=True).start()

    def update_report_header(self, car: Path, result=None):
        try:
            res = result if result is not None else getattr(self, 'last_result', None)
            # Title: prefer ui.name, fallback to folder name
            title = car.name
            brand = ''
            year = ''
            if res is not None:
                ui = (res.info or {}).get('ui') or {}
                title = ui.get('name') or title
                brand = ui.get('brand') or ''
                year = str(ui.get('year') or '')
            self.report_title_label.configure(text=title)
            # Meta: brand • year • ref • drivetrain • steer
            parts = []
            if brand:
                parts.append(brand)
            if year and year != '0':
                parts.append(year)
            if res is not None:
                if res.matched_reference:
                    parts.append(f"Ref: {res.matched_reference}")
                dt = (res.info or {}).get('drivetrain')
                if dt:
                    parts.append(str(dt))
                # Steering angle
                ang = None
                cm = (res.info or {}).get('cm_steer')
                if isinstance(cm, dict) and 'max_wheel_angle_deg' in cm:
                    try:
                        ang = round(abs(float(cm['max_wheel_angle_deg'])), 2)
                    except Exception:
                        ang = cm['max_wheel_angle_deg']
                if ang is not None:
                    parts.append(f"Angle: {ang}°")
                # Skins
                sc = (res.info or {}).get('skins_count')
                if isinstance(sc, int):
                    parts.append(f"Skins: {sc}")
            self.report_meta_label.configure(text=' • '.join(parts))
            # Status pill
            if res is not None:
                passed = res.exact_physics_match and not res.rule_violations
                if passed:
                    self.report_status_label.configure(text='PASS', bg='#188038', fg='white')
                else:
                    self.report_status_label.configure(text='FAIL', bg='#D93025', fg='white')
        except Exception:
            pass

    def populate_summary(self, result):
        try:
            # Clear old widgets
            for w in list(self.summary_inner.children.values()):
                w.destroy()

            # Layout helpers: section header + chip grid
            max_cols = 3
            r = 0
            c = 0
            for col in range(max_cols):
                self.summary_inner.grid_columnconfigure(col, weight=0)
            def section(title: str):
                nonlocal r, c
                if c != 0:
                    r += 1
                    c = 0
                lbl = tk.Label(self.summary_inner, text=title.upper(), bg=self.BRAND_LIGHT, fg=self.BRAND_NAVY, font=('Segoe UI', 10, 'bold'))
                lbl.grid(row=r, column=0, columnspan=max_cols, sticky='w', padx=6, pady=(12,2))
                r += 1
                accent = tk.Frame(self.summary_inner, bg='#c5d3ea', height=2)
                accent.grid(row=r, column=0, columnspan=max_cols, sticky='ew', padx=6, pady=(0,6))
                r += 1
                c = 0

            def _attach_tooltip(widget, text: str):
                if not text:
                    return
                tip = {'tl': None}
                def _show(_e=None):
                    try:
                        if tip['tl'] is not None:
                            return
                        tl = tk.Toplevel(widget)
                        tip['tl'] = tl
                        tl.wm_overrideredirect(True)
                        tl.configure(bg=self.BRAND_LIGHT)
                        x = widget.winfo_rootx() + 10
                        y = widget.winfo_rooty() + widget.winfo_height() + 5
                        tl.wm_geometry(f"+{x}+{y}")
                        lb = tk.Label(tl, text=text, bg=self.BRAND_SURFACE, fg=self.BRAND_BLACK, relief='solid', borderwidth=1,
                                      font=('Segoe UI', 9), justify='left', highlightbackground=self.BRAND_OUTLINE, highlightthickness=0)
                        lb.pack(ipadx=6, ipady=3)
                    except Exception:
                        pass
                def _hide(_e=None):
                    try:
                        if tip['tl'] is not None:
                            tip['tl'].destroy()
                            tip['tl'] = None
                    except Exception:
                        pass
                widget.bind('<Enter>', _show)
                widget.bind('<Leave>', _hide)

            default_tooltips = {
                'Overall': 'PASS when physics fingerprint matches reference and no rule violations are recorded.',
                'Matched Ref': 'Reference car matched via reference_cars index for this submission.',
                'Year': 'Model year from ui/ui_car.json; must meet the minimum year requirement.',
                'Name': 'Display name parsed from ui/ui_car.json:name.',
                'Brand': 'Manufacturer parsed from ui/ui_car.json:brand.',
                'Drivetrain': 'Drivetrain type from data/drivetrain.ini; competition expects a rear-wheel-drive layout.',
                'Mass': 'TOTALMASS from data/car.ini with enforcement against the rulebook minimum.',
                'Wheelbase': 'Wheelbase length from data/suspensions.ini:BASIC:WHEELBASE.',
                'Track F/R': 'Front and rear track widths from data/suspensions.ini FRONT/REAR sections.',
                'Front track': 'Front track width from data/suspensions.ini:FRONT:TRACK.',
                'Rear track': 'Rear track width from data/suspensions.ini:REAR:TRACK.',
                'Fuel Tank': 'Fuel tank position from data/car.ini:FUELTANK; tooltip lists clearance checks and flags.',
                'Fuel tank': 'Fuel tank position from data/car.ini:FUELTANK; tooltip lists clearance checks and flags.',
                'Front bias': 'CG_LOCATION from suspensions.ini:BASIC compared to enforced front weight distribution.',
                'Front tyre': 'Front tyre width and allowed range from data/tyres.ini FRONT compounds.',
                'Rear tyre': 'Rear tyre width and maximum from data/tyres.ini REAR compounds.',
                'Steering angle': 'Maximum steering angle measured/derived vs expected rule limit and reference delta.',
                'Steer inner': 'Inner wheel steering angle from measured/simulated steering data.',
                'Steer outer': 'Outer wheel steering angle from measured/simulated steering data.',
                'Steer L': 'Left wheel steering lock measured from CM/geometry data.',
                'Steer R': 'Right wheel steering lock measured from CM/geometry data.',
                'STEER_LOCK': 'STEER_LOCK value from data/car.ini compared with reference.',
                'STEER_RATIO': 'STEER_RATIO from data/car.ini compared with reference.',
                'KN5 sizes': 'Largest KN5 file compared against the allowed per-file size limit.',
                'Skin sizes': 'Summary of skin folder sizes against rulebook maximums.',
                'KN5 files': 'Count of *.kn5 model files discovered under the car root.',
                'Model caps': 'Triangles/objects count compared to competition caps (requires KN5 stats).',
                'Caps source': 'Indicates whether triangle/object estimates came from UI LOD hints.',
                'Skins': 'Number of skin folders; competition typically permits exactly one.',
                'Largest skin': 'Size of the largest skin folder in megabytes.',
                'Data files': 'Delta against reference data/ file list (extra/missing files).',
                'Fallback ref': 'Fallback reference car used when no exact physics match was found.',
                'Audit': 'Texture audit summary showing unchecked or oversized assets.',
                'Power peak': 'Maximum power from power.lut or UI curve (hp and rpm).',
                'Torque peak': 'Maximum torque derived from curves (Nm).',
                'Torque @4k': 'Interpolated torque at 4,000 rpm vs drift target.',
                'Torque @5.5k': 'Interpolated torque at 5,500 rpm vs drift target.',
                'Power @6.5k': 'Interpolated power at 6,500 rpm vs drift target.',
                'Colliders': 'Collider dimensions checked against track width and wheelbase tolerances.',
                'Setup locks': 'Count of setup.ini controls where MIN equals MAX (locked adjustments).',
                'Final Drive': 'Overall final drive ratio compared with reference and drift target range.',
                '3rd Gear Overall': 'Third gear overall ratio compared with reference and drift target range.',
            }

            def chip(label, value, ok=None, warn=False, tooltip: str = ''):
                nonlocal r, c
                # Status styling
                icon = '•'
                icon_fg = '#607089'
                card_bg = '#ffffff'
                border_col = '#d5dbe8'
                if warn:
                    icon = '⚠'
                    icon_fg = self.WARN_FG
                    card_bg = '#FFF7ED'
                    border_col = '#f5d1a3'
                elif ok is True:
                    icon = '✔'
                    icon_fg = self.OK_FG
                    card_bg = '#F1F8E9'
                    border_col = '#c6e3b8'
                elif ok is False:
                    icon = '✘'
                    icon_fg = self.BAD_FG
                    card_bg = '#FDECEA'
                    border_col = '#f5c6cb'
                card = tk.Frame(self.summary_inner, bg=card_bg, highlightthickness=1, highlightbackground=border_col)
                card.grid(row=r, column=c, sticky='nw', padx=6, pady=6)
                card.columnconfigure(2, weight=1)
                icon_lbl = tk.Label(card, text=icon, bg=card_bg, fg=icon_fg, font=('Segoe UI', 12, 'bold'))
                icon_lbl.grid(row=0, column=0, padx=(10,6), pady=8, sticky='w')
                label_lbl = tk.Label(card, text=str(label), bg=card_bg, fg='#4a5568', font=('Segoe UI', 9, 'bold'),
                                     wraplength=110, justify='left')
                label_lbl.grid(row=0, column=1, sticky='w')
                value_lbl = tk.Label(card, text=str(value), bg=card_bg, fg=self.BRAND_BLACK, font=('Segoe UI', 10),
                                     wraplength=150, justify='left', anchor='w')
                value_lbl.grid(row=0, column=2, sticky='w', padx=(12, 10))
                self.attach_hover_outline(card)
                tooltip_text = tooltip or default_tooltips.get(str(label), '')
                if tooltip_text:
                    tooltip = tooltip_text
                    _attach_tooltip(card, tooltip)
                if c >= max_cols - 1:
                    c = 0
                    r += 1
                else:
                    c += 1

            # Input data and helpers
            info = result.info or {}
            vlist = result.rule_violations or []
            def no_violation(sub):
                return not any(sub in v for v in vlist)
            spec_compare = info.get('spec_compare') or {}

            def apply_spec_value(key: str, base_value: str, extra_suffix: str = '', base_tooltip: str = '') -> tuple[str, str, bool]:
                cmp = spec_compare.get(key)
                tooltip_parts: list[str] = []
                if base_tooltip:
                    tooltip_parts.append(base_tooltip)
                if cmp:
                    value = f"{cmp.get('submitted_display', base_value)} (ref {cmp.get('reference_display', '')}){extra_suffix}"
                    tooltip_parts.append(f"Ref {cmp.get('reference_display', '')} (Δ {cmp.get('delta_display', '')})")
                    spec_fail = not cmp.get('within_tolerance', True)
                else:
                    value = base_value + extra_suffix
                    spec_fail = False
                tooltip_text = ' | '.join(p for p in tooltip_parts if p)
                return value, tooltip_text, spec_fail

            # Sections
            section('Status')
            chip('Overall', 'PASS' if (result.exact_physics_match and not vlist) else 'FAIL', ok=(result.exact_physics_match and not vlist), tooltip='Exact physics match and no rule violations')
            chip('Matched Ref', result.matched_reference or 'None', ok=bool(result.matched_reference), tooltip='Reference car matched from reference_cars index')

            # Vehicle
            section('Vehicle')
            year_val = info.get('year')
            if year_val is not None:
                chip('Year', str(year_val), ok=no_violation('Year '), tooltip='Year from ui/ui_car.json; must be >= min rule')
            ui_meta = info.get('ui') or {}
            if isinstance(ui_meta, dict):
                nm = ui_meta.get('name')
                br = ui_meta.get('brand')
                if nm:
                    chip('Name', str(nm), tooltip='ui/ui_car.json:name')
                if br:
                    chip('Brand', str(br), tooltip='ui/ui_car.json:brand')

            section('Drivetrain & Mass')
            dtype = info.get('drivetrain') or ''
            ref_drive = info.get('reference_drivetrain')
            drive_value = dtype
            drive_tooltip = 'Must be RWD per competition rules'
            drive_ok = str(dtype).upper() == 'RWD'
            if ref_drive:
                if dtype:
                    drive_value = f"{dtype} (ref {ref_drive})"
                else:
                    drive_value = f"ref {ref_drive}"
                drive_tooltip = f"Reference drivetrain: {ref_drive}"
                if dtype and str(dtype).strip().upper() != str(ref_drive).strip().upper():
                    drive_ok = False
            chip('Drivetrain', drive_value, ok=drive_ok, tooltip=drive_tooltip)

            tm = info.get('total_mass')
            exp_tm = info.get('expected_min_total_mass_kg')
            if tm is not None:
                base_tooltip = f"Min {exp_tm} kg" if exp_tm is not None else ''
                mass_value, mass_tooltip, mass_spec_fail = apply_spec_value('total_mass', f"{tm} kg", '', base_tooltip)
                mass_rule_ok = no_violation('TOTALMASS')
                mass_ok = mass_rule_ok and not mass_spec_fail
                chip('Mass', mass_value, ok=mass_ok, warn=False, tooltip=mass_tooltip)
            final_ratio = info.get('final_drive_ratio')
            drift_fd_range = info.get('drift_final_ratio_range') or (None, None)
            if final_ratio is not None:
                suffix = ''
                base_tooltip = ''
                if drift_fd_range[0] is not None and drift_fd_range[1] is not None:
                    suffix = f" (target {drift_fd_range[0]:.1f}-{drift_fd_range[1]:.1f})"
                    base_tooltip = f"Target {drift_fd_range[0]:.1f}-{drift_fd_range[1]:.1f}"
                final_value, final_tooltip, final_fail = apply_spec_value('final_drive_ratio', f"{final_ratio:.2f}", suffix, base_tooltip)
                drift_warn = bool(info.get('drift_final_ratio_warn'))
                final_ok = (not drift_warn) and not final_fail
                warn_flag = drift_warn and not final_fail
                chip('Final Drive', final_value, ok=final_ok, warn=warn_flag, tooltip=final_tooltip)
            third_ratio = info.get('third_gear_overall')
            drift_third_range = info.get('drift_third_ratio_range') or (None, None)
            if third_ratio is not None:
                suffix = ''
                base_tooltip = ''
                if drift_third_range[0] is not None and drift_third_range[1] is not None:
                    suffix = f" (target {drift_third_range[0]:.1f}-{drift_third_range[1]:.1f})"
                    base_tooltip = f"Target {drift_third_range[0]:.1f}-{drift_third_range[1]:.1f}"
                third_value, third_tooltip, third_fail = apply_spec_value('third_gear_overall', f"{third_ratio:.2f}", suffix, base_tooltip)
                third_warn = bool(info.get('drift_third_ratio_warn'))
                third_ok = (not third_warn) and not third_fail
                warn_flag = third_warn and not third_fail
                chip('3rd Gear Overall', third_value, ok=third_ok, warn=warn_flag, tooltip=third_tooltip)

            # Chassis
            section('Chassis')
            wb = info.get('wheelbase')
            ft = info.get('front_track'); rt = info.get('rear_track')
            if wb is not None:
                wb_value, wb_tooltip, wb_fail = apply_spec_value('wheelbase', f"{wb} m", '', 'data/suspensions.ini:BASIC:WHEELBASE')
                chip('Wheelbase', wb_value, ok=not wb_fail, warn=False, tooltip=wb_tooltip)
            if ft is not None:
                ft_value, ft_tooltip, ft_fail = apply_spec_value('front_track', f"{ft} m", '', 'data/suspensions.ini:FRONT:TRACK')
                chip('Front track', ft_value, ok=not ft_fail, warn=False, tooltip=ft_tooltip)
            if rt is not None:
                rt_value, rt_tooltip, rt_fail = apply_spec_value('rear_track', f"{rt} m", '', 'data/suspensions.ini:REAR:TRACK')
                chip('Rear track', rt_value, ok=not rt_fail, warn=False, tooltip=rt_tooltip)
            # Fuel tank position
            ftp = info.get('fuel_tank_pos')
            if ftp is not None:
                fuel_flags = info.get('fuel_tank_flags') or []
                tip_parts: list[str] = ['data/car.ini:FUELTANK:POSITION']
                spec_fail = False
                for axis_key in ('fuel_tank_x', 'fuel_tank_y', 'fuel_tank_z'):
                    cmp = spec_compare.get(axis_key)
                    if cmp:
                        tip_parts.append(f"{cmp['label']}: ref {cmp['reference_display']} (Δ {cmp['delta_display']})")
                        spec_fail = spec_fail or not cmp.get('within_tolerance', True)
                for flag in fuel_flags:
                    tip_parts.append(flag)
                d_front = info.get('fuel_tank_distance_to_front_axle')
                d_rear = info.get('fuel_tank_distance_to_rear_axle')
                try:
                    if isinstance(d_front, (int, float)):
                        tip_parts.append(f"front axle clearance {d_front:.2f} m")
                except Exception:
                    pass
                try:
                    if isinstance(d_rear, (int, float)):
                        tip_parts.append(f"rear axle clearance {d_rear:.2f} m")
                except Exception:
                    pass
                try:
                    if isinstance(ftp, (list, tuple)) and len(ftp) == 3:
                        fx, fy, fz = ftp
                        ftp_txt = f"({fx:.3f}, {fy:.3f}, {fz:.3f})"
                    else:
                        ftp_txt = str(ftp)
                except Exception:
                    ftp_txt = str(ftp)
                ftp_ok = no_violation('Fuel tank POSITION') and not fuel_flags and not spec_fail
                tooltip = ' | '.join(tip_parts)
                chip('Fuel tank', ftp_txt, ok=ftp_ok, warn=False, tooltip=tooltip)

            section('Balance & Tyres')
            fb = info.get('front_bias'); exp_fb = info.get('expected_front_bias')
            if fb is not None:
                fb_base_tooltip = f"Expected {exp_fb:.3f}±0.005" if exp_fb is not None else ''
                fb_value, fb_tooltip, fb_fail = apply_spec_value('front_bias', f"{fb:.3f}", '', fb_base_tooltip)
                fb_ok = (no_violation('Front bias') if exp_fb is not None else True) and not fb_fail
                chip('Front bias', fb_value, ok=fb_ok, warn=False, tooltip=fb_tooltip)
            ftw = info.get('front_tyre_width_mm'); exp_fr = info.get('expected_front_tyre_range_mm')
            if ftw is not None:
                suffix = f" (exp {exp_fr[0]}-{exp_fr[1]} mm)" if isinstance(exp_fr, (list, tuple)) and len(exp_fr) == 2 else ''
                ftw_value, ftw_tooltip, ftw_fail = apply_spec_value('front_tyre_width_mm', f"{ftw} mm", suffix, 'data/tyres.ini:FRONT:WIDTH')
                ftw_ok = (no_violation('Front tyre WIDTH') if exp_fr else True) and not ftw_fail
                chip('Front tyre', ftw_value, ok=ftw_ok, warn=False, tooltip=ftw_tooltip)
            rtw = info.get('rear_tyre_width_mm'); exp_r = info.get('expected_rear_tyre_max_mm')
            if rtw is not None:
                suffix = f" (max {exp_r} mm)" if exp_r is not None else ''
                rtw_value, rtw_tooltip, rtw_fail = apply_spec_value('rear_tyre_width_mm', f"{rtw} mm", suffix, 'data/tyres.ini:REAR:WIDTH')
                rtw_ok = (no_violation('Rear tyre WIDTH') if exp_r is not None else True) and not rtw_fail
                chip('Rear tyre', rtw_value, ok=rtw_ok, warn=False, tooltip=rtw_tooltip)

            section('Steering')
            steer_lock_val = info.get('steer_lock')
            if steer_lock_val is not None:
                lock_value, lock_tooltip, lock_fail = apply_spec_value('steer_lock', f"{steer_lock_val}°", '', 'data/car.ini:CONTROLS:STEER_LOCK')
                chip('STEER_LOCK', lock_value, ok=not lock_fail, warn=False, tooltip=lock_tooltip)
            steer_ratio_val = info.get('steer_ratio')
            if steer_ratio_val is not None:
                ratio_value, ratio_tooltip, ratio_fail = apply_spec_value('steer_ratio', f"{steer_ratio_val}", '', 'data/car.ini:CONTROLS:STEER_RATIO')
                chip('STEER_RATIO', ratio_value, ok=not ratio_fail, warn=False, tooltip=ratio_tooltip)
            ang = info.get('measured_wheel_angle_deg')
            if ang is None:
                src = info.get('cm_steer') or info.get('sim_steer')
                if isinstance(src, dict):
                    if 'max_wheel_angle_deg' in src:
                        try:
                            ang = round(abs(float(src['max_wheel_angle_deg'])), 2)
                        except Exception:
                            ang = src['max_wheel_angle_deg']
                    elif 'left_max_deg' in src and 'right_max_deg' in src:
                        try:
                            ang = round(max(abs(float(src['left_max_deg'])), abs(float(src['right_max_deg']))), 2)
                        except Exception:
                            pass
            exp_sa = info.get('expected_max_steer_angle_deg')
            src = str(info.get('steer_source') or '').lower()
            is_derived = ('derived' in src) or (src in ('ini', 'ini_derived'))
            if ang is not None and exp_sa is not None:
                # Source label and tooltip
                src_label = ''
                tooltip = ''
                src_val = str(info.get('steer_source') or '').lower()
                if 'cm' in src_val or 'normalized' in src_val:
                    src_label = ' CM'
                    if 'normalized' in src_val:
                        tooltip = 'Content Manager measurement normalized using STEER_LOCK/STEER_RATIO.'
                    else:
                        tooltip = 'Steering angle measured via Content Manager (0 toe).'
                else:
                    sim = info.get('sim_steer') or {}
                    s = str(sim.get('source') or '').lower()
                    if 'geometry' in s:
                        src_label = ' geom'
                        tooltip = 'Angle simulated from suspension geometry (kingpin + tie-rod).'
                    else:
                        src_label = ' ini'
                        tooltip = 'Angle estimated from STEER_LOCK/STEER_RATIO (fallback).'
                ref_angle_raw = info.get('reference_steer_angle_deg')
                delta_raw = info.get('steer_reference_delta')
                try:
                    ref_angle = float(ref_angle_raw) if ref_angle_raw is not None else None
                except Exception:
                    ref_angle = None
                try:
                    delta = float(delta_raw) if delta_raw is not None else None
                except Exception:
                    delta = None
                text = f"{ang}°"
                if ref_angle is not None:
                    text += f" vs ref {ref_angle:.2f}°"
                    if delta is not None and abs(delta) > 0.01:
                        text += f" (Δ {delta:+0.2f}°)"
                text += f" (max {exp_sa}°){src_label}"
                warn_flag = is_derived
                ok_flag = no_violation('wheel angle')
                if ref_angle is not None and delta is not None:
                    warn_flag = warn_flag or abs(delta) > 0.5
                    ok_flag = ok_flag and abs(delta) <= 0.5
                chip('Steering angle', text, ok=ok_flag, warn=warn_flag, tooltip=tooltip or 'Measured max steering angle (comparison against reference shown when available).')
            # Detailed inner/outer or L/R breakdown
            st_prefer_cm = str(info.get('steer_source') or '').lower()
            if 'cm' in st_prefer_cm or 'normalized' in st_prefer_cm:
                st = info.get('cm_steer')
                allow_detail = False
            else:
                st = info.get('sim_steer') or info.get('cm_steer')
                allow_detail = True
            if isinstance(st, dict) and allow_detail:
                st_src = str(st.get('source') or info.get('steer_source') or '').lower()
                st_warn = ('derived' in st_src) or ('simulated' in st_src) or (st_src in ('ini', 'ini_derived'))
                if ('inner_deg' in st) and ('outer_deg' in st):
                    try:
                        inner_v = round(abs(float(st.get('inner_deg'))), 2)
                    except Exception:
                        inner_v = st.get('inner_deg')
                    try:
                        outer_v = round(abs(float(st.get('outer_deg'))), 2)
                    except Exception:
                        outer_v = st.get('outer_deg')
                    chip('Steer inner', f"{inner_v}°", ok=no_violation('wheel angle'), warn=st_warn)
                    chip('Steer outer', f"{outer_v}°", ok=no_violation('wheel angle'), warn=st_warn)
                elif ('left_max_deg' in st) and ('right_max_deg' in st):
                    try:
                        lv = round(abs(float(st.get('left_max_deg'))), 2)
                    except Exception:
                        lv = st.get('left_max_deg')
                    try:
                        rv = round(abs(float(st.get('right_max_deg'))), 2)
                    except Exception:
                        rv = st.get('right_max_deg')
                    chip('Steer L', f"{lv}°", ok=no_violation('wheel angle'), warn=st_warn)
                    chip('Steer R', f"{rv}°", ok=no_violation('wheel angle'), warn=st_warn)
            section('Assets')
            kn5_limits = info.get('expected_max_kn5_mb')
            kn5_sizes = info.get('kn5_sizes') or {}
            if kn5_limits is not None and kn5_sizes:
                try:
                    limit_val = float(kn5_limits)
                except Exception:
                    limit_val = None
                try:
                    largest_name, largest_val = max(kn5_sizes.items(), key=lambda kv: float(kv[1] or 0.0))
                    largest_val = float(largest_val)
                except Exception:
                    largest_name, largest_val = None, None
                warn_flag = False
                ok_flag = no_violation('KN5 file')
                label_txt = 'n/a'
                if largest_val is not None:
                    label_txt = f"{largest_val:.1f} MB"
                    if limit_val is not None:
                        label_txt += f" / max {limit_val:.1f} MB"
                        warn_flag = largest_val > limit_val + 1e-6
                        ok_flag = ok_flag and not warn_flag
                tooltip = 'Largest KN5 file size'
                if largest_name:
                    tooltip += f": {largest_name}"
                chip('KN5 sizes', label_txt, ok=ok_flag, warn=warn_flag, tooltip=tooltip)
            elif info.get('expected_max_kn5_mb') is not None:
                chip('KN5 sizes', f"max {info.get('expected_max_kn5_mb')} MB", ok=no_violation('KN5 file'), tooltip='Largest KN5 size not available')
            if info.get('expected_max_skin_mb') is not None:
                chip('Skin sizes', 'within limit', ok=no_violation('Largest skin'), tooltip='Max size per skin folder (MB)')
            # KN5 files count
            kn5s = info.get('kn5_files') or []
            try:
                n_kn5 = len(kn5s)
            except Exception:
                n_kn5 = 0
            chip('KN5 files', str(n_kn5), tooltip='Number of *.kn5 files under car root')

            section('Model')
            if info.get('expected_max_triangles') is not None or info.get('expected_max_objects') is not None:
                chip('Model caps', 'within limit', ok=(no_violation('Total triangles') and no_violation('Total objects')), tooltip='Triangles/objects limits (KN5 stats or estimate)')
                ks = info.get('kn5_stats') or {}
                if isinstance(ks, dict) and str(ks.get('source') or '').lower() == 'ui_lods':
                    chip('Caps source', 'UI LODs estimate', warn=True, tooltip='Sum from ui/cm_lods_generation.json')

            section('Skins & Data')
            sc = info.get('skins_count')
            if sc is not None:
                chip('Skins', f"{sc} (expected 1)", ok=(sc==1), tooltip='Competition requires exactly one skin')
            # Largest skin info
            ms = info.get('max_skin') or {}
            if isinstance(ms, dict) and ('size_mb' in ms):
                try:
                    sz = float(ms.get('size_mb') or 0.0)
                    sz_txt = f"{sz:.1f} MB"
                except Exception:
                    sz = None
                    sz_txt = str(ms.get('size_mb'))
                exp_skin = info.get('expected_max_skin_mb')
                warn_skin = (isinstance(sz, float) and isinstance(exp_skin, (int, float)) and sz > float(exp_skin))
                chip('Largest skin', sz_txt, warn=warn_skin, tooltip='Largest skin folder size (MB)')
            d_ok = info.get('data_files_ok')
            if d_ok is not None:
                if d_ok:
                    chip('Data files', 'match reference', ok=True, tooltip='data/* exactly matches reference list')
                else:
                    extra = len(info.get('data_files_extra') or [])
                    missing = len(info.get('data_files_missing') or [])
                    chip('Data files', f'diff (+{extra}/-{missing})', ok=False, tooltip='Unexpected/missing files vs reference data/')
            if info.get('fallback_used'):
                ref = info.get('fallback_reference') or 'fallback'
                chip('Fallback ref', str(ref), warn=True, tooltip='E92 fallback reference was used (no exact ref match)')

            section('Textures')
            if info.get('textures_unchecked'):
                n_un = len(info.get('textures_unchecked') or [])
                chip('Audit', f'incomplete ({n_un} unchecked)', warn=True)

            # Performance
            section('Performance')
            pp = info.get('power_peak') or {}
            if isinstance(pp, dict):
                pwr = pp.get('power'); rpm = pp.get('rpm')
                if pwr is not None and rpm is not None:
                    chip('Power peak', f"{pwr} hp @ {rpm} rpm")
                elif pwr is not None:
                    chip('Power peak', f"{pwr} hp")
            # torque from ui or computed
            tmax = None
            if isinstance(info.get('ui_torque_curve'), dict):
                try:
                    tmax = int(info['ui_torque_curve'].get('max', 0))
                except Exception:
                    tmax = info['ui_torque_curve'].get('max')
            elif isinstance(info.get('torque_curve'), dict):
                try:
                    tmax = int(info['torque_curve'].get('max', 0))
                except Exception:
                    tmax = info['torque_curve'].get('max')
            if tmax is not None:
                chip('Torque peak', f"{tmax} Nm")

            # Colliders and setup
            section('Colliders')
            coll_ok = no_violation('Collider ')
            chip('Colliders', 'within body extents', ok=coll_ok, tooltip='Width vs track and length vs wheelbase checks')
            locks = info.get('setup_locked') or []
            if isinstance(locks, list):
                chip('Setup locks', f"{len(locks)} items", warn=len(locks) > 0, tooltip='Controls with min==max in setup.ini')
        except Exception:
            pass

    def gen_steer(self):
        if not self._ensure_authenticated():
            return
        if self._busy:
            return
        try:
            from types import SimpleNamespace
            import car_inspector as ci
        except Exception as e:
            messagebox.showerror('Error', f'Unable to import tooling for steering generation:\n{e}')
            return
        car = Path(self.car_var.get()).resolve()
        out = car / 'analysis' / 'cm_steer.json'
        args = SimpleNamespace(car=str(car), out=str(out), cm_steer_cmd=None)
        self._set_busy(True)
        self.status.set('Generating steering JSON ...')

        def run():
            try:
                ci.cmd_gen_cm_steer(args)
                self.after(0, lambda: self.status.set('Steering JSON generated'))
            except Exception as e:
                tb = traceback.format_exc()
                self.after(0, lambda: (
                    self.status.set('Gen steering failed'),
                    messagebox.showerror('Error', f'Generate steering JSON failed:\n{e}\n\n{tb}')
                ))
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=run, daemon=True).start()

    def gen_ks(self):
        if not self._ensure_authenticated():
            return
        if self._busy:
            return
        try:
            from types import SimpleNamespace
            import car_inspector as ci
        except Exception as e:
            messagebox.showerror('Error', f'Unable to import tooling for KN5 statistics:\n{e}')
            return
        car = Path(self.car_var.get()).resolve()
        out = car / 'analysis' / 'kn5_stats.json'
        args = SimpleNamespace(car=str(car), out=str(out), ks_stats_cmd=None)
        self._set_busy(True)
        self.status.set('Generating KN5 stats JSON ...')

        def run():
            try:
                ci.cmd_gen_ks_stats(args)
                self.after(0, lambda: self.status.set('KN5 stats JSON generated'))
            except Exception as e:
                tb = traceback.format_exc()
                self.after(0, lambda: (
                    self.status.set('Gen KN5 failed'),
                    messagebox.showerror('Error', f'Generate KN5 stats failed:\n{e}\n\n{tb}')
                ))
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=run, daemon=True).start()

    def load_graph_preview(self):
        try:
            car = Path(self.car_var.get()).resolve()
            self.draw_graphs(car, preview=True)
            self.status.set('Graph preview loaded')
        except Exception as e:
            messagebox.showwarning('Graph', f'Failed to load graph: {e}')

    def _filter_report_lines(self, lines: list[str], mode: str, term: str = '') -> list[str]:
        term = term.strip().lower()
        # First pass: determine line indexes that satisfy the mode filter
        mode = mode or 'all'
        matches: set[int] = set()
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            include = False
            if mode == 'all':
                include = True
            elif mode == 'issues':
                include = ('✘' in line) or ('⚠' in line) or ('FAIL' in line and 'Overall Status' in line)
            elif mode == 'warnings':
                include = '⚠' in line
            elif mode == 'failures':
                include = ('✘' in line) or ('FAIL' in line and 'Overall Status' in line)
            if include:
                if term and term not in stripped.lower():
                    continue
                matches.add(idx)
        # Add headers preceding matched lines for context
        last_header = None
        header_lines: dict[int, int | None] = {}
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.endswith(':') or stripped.startswith('eF Drift Car Scrutineer Report'):
                last_header = idx
            header_lines[idx] = last_header
        for idx in list(matches):
            header_idx = header_lines.get(idx)
            if header_idx is not None:
                matches.add(header_idx)
        # Retain blank lines directly adjacent to matched lines for readability
        for idx, line in enumerate(lines):
            if line.strip():
                continue
            if (idx - 1) in matches or (idx + 1) in matches:
                matches.add(idx)
        if not matches:
            if term:
                return ['No report lines match the current search.']
        # Build output preserving order
        output: list[str] = []
        for idx, line in enumerate(lines):
            if idx not in matches:
                continue
            stripped = line.strip()
            is_header = stripped.endswith(':') or stripped.startswith('eF Drift Car Scrutineer Report')
            if is_header:
                if output and output[-1].strip():
                    output.append('')
                output.append(line)
                continue
            output.append(line)
        return output if output else ['No report lines match the selected filter.']

    def _strip_anti_cheat_lines(self, lines: list[str]) -> list[str]:
        try:
            if not lines:
                return lines
            out: list[str] = []
            i = 0
            while i < len(lines):
                line = lines[i]
                if line.strip().lower() == 'anti-cheat:':
                    if out and not out[-1].strip():
                        out.pop()
                    i += 1
                    while i < len(lines):
                        nxt = lines[i]
                        if not nxt.strip():
                            i += 1
                            continue
                        if nxt.startswith('- ['):
                            i += 1
                            continue
                        break
                    continue
                out.append(line)
                i += 1
            return out
        except Exception:
            return lines

    def render_report_text(self, raw_text: str | None = None):
        try:
            if raw_text is not None:
                self.report_raw_text = raw_text
            text = self.report_raw_text or ''
            if not text:
                self.txt.configure(state='normal')
                self.txt.delete('1.0', tk.END)
                self.txt.configure(state='normal')
                self._apply_report_search_highlight()
                return
            lines = text.splitlines()
            mode = getattr(self, 'report_filter_var', None)
            mode_val = mode.get() if isinstance(mode, tk.StringVar) else 'all'
            search_term = self.report_search_var.get() if hasattr(self, 'report_search_var') else ''
            filtered_lines = self._filter_report_lines(lines, mode_val, search_term or '')
            filtered_lines = self._strip_anti_cheat_lines(filtered_lines)
            display = '\n'.join(filtered_lines)
            self.txt.configure(state='normal')
            self.txt.delete('1.0', tk.END)
            self.txt.insert(tk.END, display)
            self.colorize_report_text()
        except Exception:
            pass

    def _apply_report_search_highlight(self):
        try:
            t = self.txt
            term = self.report_search_var.get().strip() if hasattr(self, 'report_search_var') else ''
            t.tag_configure('search', background='#FFE082', foreground=self.BRAND_BLACK)
            t.tag_remove('search', '1.0', tk.END)
            if not term:
                return
            start = '1.0'
            while True:
                idx = t.search(term, start, stopindex='end', nocase=True)
                if not idx:
                    break
                end = f"{idx}+{len(term)}c"
                t.tag_add('search', idx, end)
                start = end
        except Exception:
            pass

    def _set_ac_summary_style(self, bg: str, fg: str) -> None:
        try:
            if hasattr(self, 'ac_summary_frame'):
                self.ac_summary_frame.configure(bg=bg)
            if hasattr(self, 'ac_summary_label'):
                self.ac_summary_label.configure(bg=bg, fg=fg)
        except Exception:
            pass

    def _clear_report_search(self):
        try:
            if hasattr(self, 'report_search_var'):
                self.report_search_var.set('')
            self.render_report_text()
        except Exception:
            pass

    def _on_report_search_change(self):
        try:
            self.render_report_text()
        except Exception:
            pass

    def draw_graphs(self, car: Path, preview: bool = False, result=None):
        try:
            result_obj = result or getattr(self, 'last_result', None)
            info = result_obj.info if (result_obj and hasattr(result_obj, 'info') and isinstance(result_obj.info, dict)) else {}
            ref_entry = None
            if result_obj:
                ref_entry = self._get_reference_entry(getattr(result_obj, 'matched_reference', None))
            if preview:
                canvas = getattr(self, 'small_canvas', None)
                if not canvas:
                    return
                self._draw_power_chart(canvas, car, result_obj, ref_entry, preview=True)
                return
            if not hasattr(self, 'power_canvas'):
                return
            self._draw_power_chart(self.power_canvas, car, result_obj, ref_entry, preview=False)
            self._draw_gear_chart(self.gear_canvas, car, info, ref_entry)
            self._draw_chassis_chart(self.chassis_canvas, info, ref_entry)
            self._draw_tyre_chart(self.tyre_canvas, info, ref_entry)
            info_snapshot = dict(info) if isinstance(info, dict) else {}
            self._graph_state = {'car': str(car), 'result': result_obj, 'info': info_snapshot}
            self._queue_graph_redraw()
        except Exception:
            pass

    def _draw_power_chart(self, canvas, car_path: Path, result_obj, ref_entry, preview: bool = False):
        if canvas is None:
            return
        try:
            canvas.delete('all')
        except Exception:
            return

        datasets = []
        ref_notice: str | None = None
        submitted_curves = self._load_power_curves(car_path)
        missing_submitted = submitted_curves is None

        if submitted_curves:
            title = submitted_curves.get('display_name') or car_path.name
            panel_title = title if preview else f"Submitted: {title}"
            datasets.append({
                **submitted_curves,
                'panel_title': panel_title,
                'panel_role': 'Submitted',
                'power_color': self.BRAND_ORANGE,
                'torque_color': self.BRAND_NAVY,
                'line_width': 2.4,
            })

        if not preview and isinstance(ref_entry, dict):
            ref_key = getattr(result_obj, 'matched_reference', None) if result_obj else None
            ref_path = Path(ref_entry.get('path', ''))
            if not ref_path.exists() and ref_key:
                alt = self.state.reference_root / ref_key
                if alt.exists():
                    ref_path = alt
            if ref_path and ref_path.exists():
                ref_curves = self._load_power_curves(ref_path, meta=ref_entry)
                if ref_curves:
                    ui_meta = ref_entry.get('ui') if isinstance(ref_entry.get('ui'), dict) else {}
                    ref_title = ref_curves.get('display_name') or (ui_meta.get('name') if isinstance(ui_meta, dict) else '') or (ref_key or 'Reference')
                    subtitle = ''
                    if isinstance(ui_meta, dict):
                        subtitle = ui_meta.get('brand') or ''
                    datasets.append({
                        **ref_curves,
                        'panel_title': f"Reference: {ref_title}",
                        'panel_role': 'Reference',
                        'panel_subtitle': subtitle if subtitle and subtitle != ref_title else '',
                        'power_color': '#f5a572',
                        'torque_color': '#4f7ec2',
                        'line_width': 2.2,
                    })
                else:
                    ref_notice = f"No power/torque data for reference '{ref_key}'."
            else:
                if ref_key:
                    ref_notice = f"Reference '{ref_key}' not found."

        datasets = [ds for ds in datasets if ds.get('hp_pts') or ds.get('tq_pts')]
        if not datasets:
            w, h = self._get_canvas_dimensions(canvas)
            message = 'No power/torque data available.'
            if missing_submitted:
                message = 'Submitted car has no power/torque data.'
            canvas.create_text(w / 2, h / 2, text=message, fill=self.BRAND_BLACK, font=('Segoe UI', 11, 'bold'))
            if ref_notice:
                canvas.create_text(w / 2, h / 2 + 20, text=ref_notice, fill='#555555', font=('Segoe UI', 9))
            return

        w, h = self._get_canvas_dimensions(canvas)
        outer_pad_l = 26
        outer_pad_r = 20
        outer_pad_t = 30
        outer_pad_b = 36
        panel_gap = 24 if len(datasets) > 1 else 0
        panel_count = len(datasets)
        available_w = w - outer_pad_l - outer_pad_r
        panel_total_w = (available_w - panel_gap * (panel_count - 1)) / panel_count if panel_count else available_w
        panel_total_h = h - outer_pad_t - outer_pad_b
        panel_pad_l = 38
        panel_pad_r = 22
        panel_pad_t = 62
        panel_pad_b = 48

        rpm_min = min(ds['rpm_min'] for ds in datasets if ds.get('rpm_min') is not None)
        rpm_max = max(ds['rpm_max'] for ds in datasets if ds.get('rpm_max') is not None)
        if rpm_max <= rpm_min:
            rpm_max = rpm_min + 1.0
        rpm_span = rpm_max - rpm_min
        margin = rpm_span * 0.05
        rpm_min = max(0.0, rpm_min - margin)
        rpm_max += margin
        rpm_span = rpm_max - rpm_min

        has_power = any(ds['hp_pts'] for ds in datasets)
        has_torque = any(ds['tq_pts'] for ds in datasets)
        hp_axis_max = max((ds['hp_max'] for ds in datasets), default=0.0) if has_power else 0.0
        tq_axis_max = max((ds['tq_max'] for ds in datasets), default=0.0) if has_torque else 0.0
        hp_axis_max = hp_axis_max * 1.05 if hp_axis_max > 0 else 1.0
        tq_axis_max = tq_axis_max * 1.05 if tq_axis_max > 0 else 1.0

        def fmt_peak(val):
            try:
                return int(round(val))
            except Exception:
                return val

        for idx, data in enumerate(datasets):
            panel_left = outer_pad_l + idx * (panel_total_w + panel_gap)
            panel_top = outer_pad_t
            panel_right = panel_left + panel_total_w
            panel_bottom = panel_top + panel_total_h
            inner_left = panel_left + panel_pad_l
            inner_right = panel_right - panel_pad_r
            inner_bottom = panel_bottom - panel_pad_b
            inner_top = panel_top + panel_pad_t
            inner_w = inner_right - inner_left
            if inner_w <= 0:
                continue

            canvas.create_rectangle(panel_left, panel_top, panel_right, panel_bottom, outline='#d5d5d5', fill='#fbfbfb')
            title = data.get('panel_title') or data.get('display_name') or data.get('panel_role')
            subtitle = data.get('panel_subtitle') or data.get('brand') or ''

            title_text = data.get('panel_title') or data.get('display_name') or data.get('panel_role')
            subtitle = data.get('panel_subtitle') or data.get('brand') or ''
            header_y = panel_top + 12
            canvas.create_text(inner_left + 16, header_y, text=title_text, anchor='nw', font=('Segoe UI', 10, 'bold'), fill=self.BRAND_BLACK)
            header_height = 18
            if subtitle:
                canvas.create_text(inner_left + 16, header_y + header_height, text=subtitle, anchor='nw', font=('Segoe UI', 8), fill='#666666')
                header_height += 16

            legend_entries = []
            if data.get('panel_role') == 'Submitted':
                legend_entries.append(('Power', data.get('power_color', self.BRAND_ORANGE)))
                legend_entries.append(('Torque', data.get('torque_color', self.BRAND_NAVY)))
            elif data.get('panel_role') == 'Reference':
                legend_entries.append(('Power (ref)', data.get('power_color', self.BRAND_ORANGE)))
                legend_entries.append(('Torque (ref)', data.get('torque_color', self.BRAND_NAVY)))
            legend_y = header_y + header_height + 8
            for i, (label, color) in enumerate(legend_entries):
                y = legend_y + i * 18
                canvas.create_rectangle(inner_left + 16, y, inner_left + 28, y + 10, fill=color, outline=color)
                canvas.create_text(inner_left + 34, y + 5, text=label, anchor='w', font=('Segoe UI', 8), fill='#333333')

            legend_height = len(legend_entries) * 18 if legend_entries else 0
            total_header = header_height + (legend_height + 8 if legend_entries else 0)
            inner_top = panel_top + panel_pad_t + total_header + 12
            inner_bottom = panel_bottom - panel_pad_b
            inner_h = inner_bottom - inner_top
            if inner_h <= 60:
                inner_top = panel_top + panel_pad_t
                inner_bottom = panel_bottom - panel_pad_b
                inner_h = inner_bottom - inner_top

            canvas.create_rectangle(inner_left, inner_top, inner_right, inner_bottom,
                                    outline=self.BRAND_OUTLINE, fill=self.BRAND_SURFACE)

            nt_x = 6
            for i in range(nt_x):
                frac = i / (nt_x - 1) if nt_x > 1 else 0
                rpm_val = rpm_min + frac * rpm_span
                px = inner_left + frac * inner_w
                canvas.create_line(px, inner_top, px, inner_bottom, fill='#f0f0f0')
                canvas.create_line(px, inner_bottom, px, inner_bottom + 4, fill='#c8c8c8')
                label = int(round(rpm_val / 100.0) * 100)
                canvas.create_text(px, inner_bottom + 14, text=str(label), anchor='n', font=('Segoe UI', 8), fill='#444444')
            canvas.create_text((inner_left + inner_right) / 2, inner_bottom + 28,
                               text='RPM', anchor='n', font=('Segoe UI', 8, 'italic'), fill='#555555')

            nt_y = 5
            if has_power and hp_axis_max > 0:
                for i in range(nt_y):
                    frac = i / (nt_y - 1) if nt_y > 1 else 0
                    py = inner_bottom - frac * inner_h
                    val = hp_axis_max * frac
                    canvas.create_line(inner_left - 4, py, inner_left, py, fill=self.BRAND_ORANGE)
                    canvas.create_text(inner_left - 8, py, text=str(fmt_peak(val)), anchor='e',
                                       font=('Segoe UI', 8), fill=self.BRAND_ORANGE)
            if has_torque and tq_axis_max > 0:
                for i in range(nt_y):
                    frac = i / (nt_y - 1) if nt_y > 1 else 0
                    py = inner_bottom - frac * inner_h
                    val = tq_axis_max * frac
                    canvas.create_line(inner_right, py, inner_right + 4, py, fill=self.BRAND_NAVY)
                    canvas.create_text(inner_right + 8, py, text=str(fmt_peak(val)), anchor='w',
                                       font=('Segoe UI', 8), fill=self.BRAND_NAVY)

            if has_power:
                canvas.create_text(inner_left + 6, inner_top - 10, text='Power (hp)', anchor='w',
                                   font=('Segoe UI', 8, 'bold'), fill=data.get('power_color', self.BRAND_ORANGE))
            if has_torque:
                canvas.create_text(inner_right - 6, inner_top - 10, text='Torque (Nm)', anchor='e',
                                   font=('Segoe UI', 8, 'bold'), fill=data.get('torque_color', self.BRAND_NAVY))

            power_points = data.get('hp_pts') or []
            torque_points = data.get('tq_pts') or []
            line_width = data.get('line_width', 2.0)

            def plot(points, color, axis_max):
                if not points or axis_max <= 0:
                    return
                coords = []
                for rpm, val in points:
                    nx = (rpm - rpm_min) / rpm_span if rpm_span else 0.0
                    nx = max(0.0, min(1.0, nx))
                    px = inner_left + nx * inner_w
                    ny = val / axis_max if axis_max else 0.0
                    py = inner_bottom - max(0.0, ny) * inner_h
                    coords.extend([px, py])
                if len(coords) >= 4:
                    canvas.create_line(*coords, fill=color, width=line_width, smooth=True)

            if has_power:
                plot(power_points, data.get('power_color', self.BRAND_ORANGE), hp_axis_max)
            if has_torque:
                plot(torque_points, data.get('torque_color', self.BRAND_NAVY), tq_axis_max)

            peak_parts = []
            if has_power and data.get('hp_max'):
                peak_parts.append(f"{fmt_peak(data.get('hp_max'))} hp")
            if has_torque and data.get('tq_max'):
                peak_parts.append(f"{fmt_peak(data.get('tq_max'))} Nm")
            info_y = panel_bottom + 12
            center_x = (panel_left + panel_right) / 2
            if peak_parts:
                canvas.create_text(center_x, info_y, text="Peak " + " / ".join(peak_parts), anchor='n',
                                   font=('Segoe UI', 8), fill='#333333')
                info_y += 16

            if data.get('curve_source') == 'lut':
                canvas.create_text(center_x, info_y, text='Data from power.lut',
                                   anchor='n', font=('Segoe UI', 7, 'italic'), fill='#777777')

        if ref_notice:
            canvas.create_text(w / 2, h - 12, text=ref_notice, anchor='s', font=('Segoe UI', 8), fill='#555555')

    def _load_power_curves(self, car_path: Path, meta: dict | None = None):
        try:
            import json
            import math
        except Exception:
            return None

        hp_pts: list[tuple[float, float]] = []
        tq_pts: list[tuple[float, float]] = []
        curve_source = 'ui'
        display_name = car_path.name
        brand = ''
        ui_data = None

        if meta and isinstance(meta.get('ui'), dict):
            ui_data = meta['ui']
        else:
            ui_path = car_path / 'ui' / 'ui_car.json'
            if ui_path.exists():
                try:
                    ui_data = json.loads(ui_path.read_text(encoding='utf-8', errors='ignore'))
                except Exception:
                    ui_data = None

        if isinstance(ui_data, dict):
            display_name = ui_data.get('name') or display_name
            brand = ui_data.get('brand') or ''
            pc = ui_data.get('powerCurve')
            tc = ui_data.get('torqueCurve')
            if isinstance(pc, list):
                for item in pc:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        try:
                            hp_pts.append((float(item[0]), float(item[1])))
                        except Exception:
                            continue
            if isinstance(tc, list):
                for item in tc:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        try:
                            tq_pts.append((float(item[0]), float(item[1])))
                        except Exception:
                            continue

        if not hp_pts:
            lut_path = car_path / 'data' / 'power.lut'
            if lut_path.exists():
                try:
                    from inspector.lut_parser import read_lut
                    hp_pts = read_lut(lut_path)
                    tq_pts = []
                    for rpm, hp in hp_pts:
                        w = hp * 745.699872
                        torque_nm = w / (2 * math.pi * (rpm / 60.0 if rpm > 0 else 1.0))
                        tq_pts.append((rpm, torque_nm))
                    curve_source = 'lut'
                except Exception:
                    hp_pts = []
                    tq_pts = []

        hp_pts = sorted(hp_pts, key=lambda x: x[0])
        tq_pts = sorted(tq_pts, key=lambda x: x[0])
        if not hp_pts and not tq_pts:
            return None

        xs = [p[0] for p in hp_pts] + [p[0] for p in tq_pts]
        rpm_min = min(xs) if xs else 0.0
        rpm_max = max(xs) if xs else rpm_min + 1.0
        hp_max = max((p[1] for p in hp_pts), default=0.0)
        tq_max = max((p[1] for p in tq_pts), default=0.0)
        return {
            'hp_pts': hp_pts,
            'tq_pts': tq_pts,
            'hp_max': hp_max,
            'tq_max': tq_max,
            'rpm_min': rpm_min,
            'rpm_max': rpm_max,
            'display_name': display_name,
            'brand': brand,
            'curve_source': curve_source,
        }

    def _draw_gear_chart(self, canvas, car_path: Path, info: dict, ref_entry):
        if canvas is None:
            return
        try:
            canvas.delete('all')
        except Exception:
            return

        submitted = self._load_car_gearing(car_path)
        reference = self._extract_reference_gearing(ref_entry)

        if not submitted and not reference:
            w, h = self._get_canvas_dimensions(canvas)
            canvas.create_text(w / 2, h / 2, text='No drivetrain data available.', fill=self.BRAND_BLACK, font=('Segoe UI', 10, 'italic'))
            return

        datasets = []
        if submitted:
            datasets.append({'label': 'Submitted', 'color': self.BRAND_ORANGE, 'ratios': submitted['overall']})
        if reference:
            datasets.append({'label': 'Reference', 'color': '#5C7AEA', 'ratios': reference['overall']})
        overlap_detected = False
        if not datasets:
            w, h = self._get_canvas_dimensions(canvas)
            canvas.create_text(w / 2, h / 2, text='No gearing data available.', fill=self.BRAND_BLACK, font=('Segoe UI', 10, 'italic'))
            return

        max_gears = max(len(d['ratios']) for d in datasets)
        if max_gears == 0:
            w, h = self._get_canvas_dimensions(canvas)
            canvas.create_text(w / 2, h / 2, text='No gearing data available.', fill=self.BRAND_BLACK, font=('Segoe UI', 10, 'italic'))
            return

        y_max = max((max((ratio for ratio in d['ratios'] if ratio is not None), default=0.0) for d in datasets), default=0.0)
        y_max = y_max * 1.1 if y_max > 0 else 1.0

        w, h = self._get_canvas_dimensions(canvas)
        pad_l = 80
        pad_r = 40
        pad_t = 50
        pad_b = 60
        plot_left = pad_l
        plot_right = w - pad_r
        plot_top = pad_t
        plot_bottom = h - pad_b
        plot_w = max(10, plot_right - plot_left)
        plot_h = max(10, plot_bottom - plot_top)

        canvas.create_rectangle(plot_left, plot_top, plot_right, plot_bottom,
                                outline=self.BRAND_OUTLINE, fill=self.BRAND_SURFACE)
        for i in range(max_gears):
            x_frac = i / (max_gears - 1) if max_gears > 1 else 0
            x = plot_left + x_frac * plot_w
            canvas.create_line(x, plot_top, x, plot_bottom, fill='#f4f4f4')
            canvas.create_text(x, plot_bottom + 16, text=str(i + 1), anchor='n', font=('Segoe UI', 8), fill='#444444')
        canvas.create_text((plot_left + plot_right) / 2, plot_bottom + 28, text='Gear Number', anchor='n', font=('Segoe UI', 8, 'italic'), fill='#555555')

        tick_count = 5
        for i in range(tick_count):
            y_frac = i / (tick_count - 1) if tick_count > 1 else 0
            y = plot_bottom - y_frac * plot_h
            value = y_frac * y_max
            canvas.create_line(plot_left - 6, y, plot_left, y, fill='#d0d0d0')
            canvas.create_text(plot_left - 8, y, text=f"{value:.2f}", anchor='e', font=('Segoe UI', 8), fill='#555555')

        for data in datasets:
            ratios = data['ratios']
            color = data['color']
            coords = []
            for idx, ratio in enumerate(ratios):
                if ratio is None:
                    continue
                x_frac = idx / (max_gears - 1) if max_gears > 1 else 0
                x = plot_left + x_frac * plot_w
                ratio_clamped = max(0.0, min(y_max, ratio))
                y = plot_bottom - (ratio_clamped / y_max) * plot_h
                coords.extend([x, y])
            if len(coords) >= 4:
                canvas.create_line(*coords, fill=color, width=2.2, smooth=True)
            for idx, ratio in enumerate(ratios):
                if ratio is None:
                    continue
                x_frac = idx / (max_gears - 1) if max_gears > 1 else 0
                x = plot_left + x_frac * plot_w
                ratio_clamped = max(0.0, min(y_max, ratio))
                y = plot_bottom - (ratio_clamped / y_max) * plot_h
                canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline=color)

        if len(datasets) == 2 and datasets[0]['ratios'] == datasets[1]['ratios']:
            overlap_detected = True

        legend_entries = [(d['label'], d['color']) for d in datasets]
        legend_x = plot_right - 200
        legend_y = plot_top - 32
        for idx, (label, color) in enumerate(legend_entries):
            y = legend_y + idx * 16
            canvas.create_rectangle(legend_x, y, legend_x + 12, y + 10, fill=color, outline=color)
            canvas.create_text(legend_x + 18, y + 5, text=label, anchor='w', font=('Segoe UI', 8), fill=self.BRAND_BLACK)
        info_y = legend_y + len(legend_entries) * 16 + 20
        info_text = 'Overall ratio (gear × final drive)'
        if overlap_detected:
            info_text += ' — Submitted and reference gearing match exactly'
        canvas.create_text(plot_right - 20, info_y, text=info_text, anchor='ne', font=('Segoe UI', 8, 'italic'), fill='#666666')

    def _load_car_gearing(self, car_path: Path):
        try:
            from inspector.ini_parser import read_ini, get_float, get_int
        except Exception:
            return None
        drive_path = car_path / 'data' / 'drivetrain.ini'
        if not drive_path.exists():
            return None
        drive_ini = read_ini(drive_path)
        if not drive_ini:
            return None
        gears: list[float] = []
        gear_count = get_int(drive_ini, 'GEARS', 'COUNT')
        if gear_count:
            for i in range(1, gear_count + 1):
                val = get_float(drive_ini, 'GEARS', f'GEAR_{i}')
                if val is not None:
                    gears.append(val)
        else:
            idx = 1
            while True:
                val = get_float(drive_ini, 'GEARS', f'GEAR_{idx}')
                if val is None:
                    break
                gears.append(val)
                idx += 1
        if not gears:
            return None
        final_ratio = (get_float(drive_ini, 'GEARS', 'FINAL') or
                       get_float(drive_ini, 'FINAL', 'RATIO') or
                       get_float(drive_ini, 'FINAL', 'FINAL') or 1.0)
        final_ratio = final_ratio if final_ratio not in (None, 0) else 1.0
        overall = [abs(g) * abs(final_ratio) for g in gears]
        return {
            'gears': gears,
            'final': final_ratio,
            'overall': overall,
        }

    def _extract_reference_gearing(self, ref_entry):
        if not isinstance(ref_entry, dict):
            return None
        gears = ref_entry.get('gears') or []
        if not gears:
            return None
        final_ratio = ref_entry.get('final_ratio') or 1.0
        final_ratio = final_ratio if final_ratio not in (None, 0) else 1.0
        overall = [abs(g) * abs(final_ratio) for g in gears]
        return {'overall': overall}

    def _draw_chassis_chart(self, canvas, info: dict, ref_entry):
        if canvas is None:
            return
        try:
            canvas.delete('all')
        except Exception:
            return

        def get_value(data, key):
            if not isinstance(data, dict):
                return None
            val = data.get(key)
            if isinstance(val, (int, float)):
                return float(val)
            return None

        metrics = [
            {
                'label': 'Mass',
                'unit': 'kg',
                'transform': lambda v: v,
                'format': lambda v: f"{v:.0f} kg",
                'submitted': get_value(info, 'total_mass'),
                'reference': get_value(ref_entry, 'total_mass'),
            },
            {
                'label': 'CG Front Bias',
                'unit': '%',
                'transform': lambda v: v * 100.0,
                'format': lambda v: f"{v:.1f}%",
                'submitted': get_value(info, 'front_bias'),
                'reference': get_value(ref_entry, 'cg_location'),
            },
            {
                'label': 'Front Track',
                'unit': 'mm',
                'transform': lambda v: v * 1000.0,
                'format': lambda v: f"{v:.0f} mm",
                'submitted': get_value(info, 'front_track'),
                'reference': get_value(ref_entry, 'front_track'),
            },
            {
                'label': 'Rear Track',
                'unit': 'mm',
                'transform': lambda v: v * 1000.0,
                'format': lambda v: f"{v:.0f} mm",
                'submitted': get_value(info, 'rear_track'),
                'reference': get_value(ref_entry, 'rear_track'),
            },
            {
                'label': 'Wheelbase',
                'unit': 'mm',
                'transform': lambda v: v * 1000.0,
                'format': lambda v: f"{v:.0f} mm",
                'submitted': get_value(info, 'wheelbase'),
                'reference': get_value(ref_entry, 'wheelbase'),
            },
        ]

        fuel_sub = info.get('fuel_tank_pos')
        fuel_ref = ref_entry.get('fuel_tank_pos') if isinstance(ref_entry, dict) else None

        def _component(value, idx):
            try:
                if isinstance(value, (list, tuple)) and len(value) > idx:
                    return float(value[idx])
            except Exception:
                pass
            return None

        fuel_sub_x = _component(fuel_sub, 0)
        fuel_sub_z = _component(fuel_sub, 2)
        fuel_ref_x = _component(fuel_ref, 0)
        fuel_ref_z = _component(fuel_ref, 2)
        if fuel_sub_x is not None or fuel_ref_x is not None:
            metrics.append({
                'label': 'Fuel Tank X',
                'unit': 'mm',
                'transform': lambda v: v * 1000.0,
                'format': lambda v: f"{v:.0f} mm",
                'submitted': fuel_sub_x,
                'reference': fuel_ref_x,
            })
        if fuel_sub_z is not None or fuel_ref_z is not None:
            metrics.append({
                'label': 'Fuel Tank Z',
                'unit': 'mm',
                'transform': lambda v: v * 1000.0,
                'format': lambda v: f"{v:.0f} mm",
                'submitted': fuel_sub_z,
                'reference': fuel_ref_z,
            })

        steer_lock_sub = get_value(info, 'steer_lock')
        steer_lock_ref = get_value(info, 'reference_steer_lock') or get_value(ref_entry, 'steer_lock')
        if steer_lock_sub is not None or steer_lock_ref is not None:
            metrics.append({
                'label': 'Steer Lock',
                'unit': '°',
                'transform': lambda v: v,
                'format': lambda v: f"{v:.1f}°",
                'submitted': steer_lock_sub,
                'reference': steer_lock_ref,
            })
        wheel_angle_sub = get_value(info, 'derived_wheel_angle_deg') or get_value(info, 'measured_wheel_angle_deg')
        wheel_angle_ref = get_value(info, 'reference_steer_angle_deg')
        if wheel_angle_sub is not None or wheel_angle_ref is not None:
            metrics.append({
                'label': 'Wheel Angle',
                'unit': '°',
                'transform': lambda v: v,
                'format': lambda v: f"{v:.1f}°",
                'submitted': wheel_angle_sub,
                'reference': wheel_angle_ref,
            })

        rows = [m for m in metrics if m['submitted'] is not None or m['reference'] is not None]
        if not rows:
            w, h = self._get_canvas_dimensions(canvas)
            canvas.create_text(w / 2, h / 2, text='Chassis metrics unavailable.', fill=self.BRAND_BLACK, font=('Segoe UI', 10, 'italic'))
            return

        w, h = self._get_canvas_dimensions(canvas)
        plot_left = 180
        plot_right = w - 60
        plot_top = 56
        plot_bottom = h - 48
        plot_width = max(10, plot_right - plot_left)
        total_height = plot_bottom - plot_top
        row_count = len(rows)
        row_height = total_height / row_count if row_count else total_height
        bar_height = row_height * 0.32
        bar_height = max(10, min(bar_height, row_height * 0.4, 24))

        legend_items = []
        if any(m['submitted'] is not None for m in rows):
            legend_items.append(('Submitted', self.BRAND_ORANGE))
        if any(m['reference'] is not None for m in rows):
            legend_items.append(('Reference', '#4f7ec2'))
        legend_x = plot_left
        legend_y = plot_top - 36
        for idx, (label, color) in enumerate(legend_items):
            y = legend_y + idx * 16
            canvas.create_rectangle(legend_x, y, legend_x + 12, y + 10, fill=color, outline=color)
            canvas.create_text(legend_x + 18, y + 5, text=label, anchor='w', font=('Segoe UI', 8), fill=self.BRAND_BLACK)

        label_x = 16
        for idx, metric in enumerate(rows):
            row_top = plot_top + idx * row_height
            row_mid = row_top + row_height / 2
            canvas.create_text(label_x, row_top, text=metric['label'], anchor='nw', font=('Segoe UI', 9, 'bold'), fill=self.BRAND_BLACK)

            sub_val = metric['submitted']
            ref_val = metric['reference']
            transform = metric['transform']
            fmt = metric['format']

            sub_val_t = transform(sub_val) if sub_val is not None else None
            ref_val_t = transform(ref_val) if ref_val is not None else None
            magnitudes = [abs(v) for v in (sub_val_t, ref_val_t) if v is not None]
            max_abs = max(magnitudes) if magnitudes else 0.0
            if max_abs <= 0:
                max_abs = 1.0
            scale = plot_width / max_abs
            base_x = plot_left

            def draw_bar(value, color, center_y):
                if value is None:
                    canvas.create_text(base_x, center_y, text='n/a', anchor='w', font=('Segoe UI', 8, 'italic'), fill='#777777')
                    return
                magnitude = abs(value)
                width = magnitude * scale
                x1 = base_x
                x2 = base_x + width
                y1 = center_y - bar_height / 2
                y2 = center_y + bar_height / 2
                canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline=color)
                if value < 0:
                    canvas.create_line(x1, y1, x2, y1, fill=self.BAD_FG, width=2)
                    display = f"({fmt(magnitude)})"
                else:
                    display = fmt(magnitude)
                canvas.create_text(x2 + 8, center_y, text=display, anchor='w', font=('Segoe UI', 8), fill=self.BRAND_BLACK)

            max_offset = row_height / 2 - bar_height / 2 - 6
            if max_offset < 8:
                max_offset = 8
            offset = max(row_height * 0.25, 12)
            if offset > max_offset:
                offset = max_offset
            min_offset = min(10, max_offset)
            if offset < min_offset:
                offset = min_offset
            submitted_center = row_mid - offset
            reference_center = row_mid + offset

            draw_bar(sub_val_t, self.BRAND_ORANGE, submitted_center)
            draw_bar(ref_val_t, '#4f7ec2', reference_center)

    def _draw_tyre_chart(self, canvas, info: dict, ref_entry):
        if canvas is None:
            return
        try:
            canvas.delete('all')
        except Exception:
            return

        def to_mm(value):
            if value is None:
                return None
            if isinstance(value, (int, float)):
                if value > 10:
                    return float(value)
                return float(value) * 1000.0
            return None

        submitted_front = to_mm(info.get('front_tyre_width_mm'))
        submitted_rear = to_mm(info.get('rear_tyre_width_mm'))

        ref_front = None
        ref_rear = None
        if isinstance(ref_entry, dict):
            compounds = ref_entry.get('tyre_compounds') or []
            if compounds:
                comp = compounds[0]
                if isinstance(comp, dict):
                    ref_front = to_mm(comp.get('width_front'))
                    ref_rear = to_mm(comp.get('width_rear'))

        if all(v is None for v in (submitted_front, submitted_rear, ref_front, ref_rear)):
            w, h = self._get_canvas_dimensions(canvas)
            canvas.create_text(w / 2, h / 2, text='Tyre data unavailable.', fill=self.BRAND_BLACK, font=('Segoe UI', 10, 'italic'))
            return

        w, h = self._get_canvas_dimensions(canvas)
        plot_left = 160
        plot_right = w - 60
        plot_top = 48
        plot_bottom = h - 36
        plot_width = max(10, plot_right - plot_left)

        values = [v for v in (submitted_front, submitted_rear, ref_front, ref_rear) if v is not None]
        max_width = max(values) if values else 0.0
        if values:
            avg = sum(values) / len(values)
            max_width = max(max_width * 1.05, avg * 1.3)
        else:
            max_width = 1.0

        rows = []
        if submitted_front is not None or submitted_rear is not None:
            rows.append(('Submitted', submitted_front, submitted_rear, self.BRAND_ORANGE, self.BRAND_NAVY))
        if ref_front is not None or ref_rear is not None:
            rows.append(('Reference', ref_front, ref_rear, '#f5a572', '#4f7ec2'))
        if not rows:
            w, h = self._get_canvas_dimensions(canvas)
            canvas.create_text(w / 2, h / 2, text='Tyre data unavailable.', fill=self.BRAND_BLACK, font=('Segoe UI', 10, 'italic'))
            return

        row_count = len(rows)
        row_height = (plot_bottom - plot_top) / row_count
        bar_height = min(max(row_height * 0.35, 12), 24)

        for idx, (label, front_val, rear_val, front_color, rear_color) in enumerate(rows):
            row_top = plot_top + idx * row_height
            row_mid = row_top + row_height / 2
            canvas.create_text(16, row_top, text=label, anchor='nw', font=('Segoe UI', 9, 'bold'), fill=self.BRAND_BLACK)

            def draw_bar(value, color, base_y, side_label):
                if value is None:
                    canvas.create_text(plot_left, base_y, text=f'{side_label}: n/a', anchor='w', font=('Segoe UI', 8, 'italic'), fill='#777777')
                    return
                width = (value / max_width) * plot_width
                y1 = base_y - bar_height / 2
                y2 = base_y + bar_height / 2
                canvas.create_rectangle(plot_left, y1, plot_left + width, y2, fill=color, outline=color)
                canvas.create_text(plot_left + width + 8, base_y, text=f'{side_label}: {int(round(value))} mm', anchor='w', font=('Segoe UI', 8), fill=self.BRAND_BLACK)

            desired_spacing = max(bar_height + 14, row_height * 0.3)
            max_spacing = row_height / 2 - bar_height / 2 - 6
            if max_spacing < 8:
                max_spacing = 8
            spacing = min(desired_spacing, max_spacing)
            min_spacing = min(12, max_spacing)
            if spacing < min_spacing:
                spacing = min_spacing
            draw_bar(front_val, front_color, row_mid - spacing, 'Front')
            draw_bar(rear_val, rear_color, row_mid + spacing, 'Rear')

    def _get_canvas_dimensions(self, canvas):
        try:
            w = canvas.winfo_width()
            h = canvas.winfo_height()
            if not w or w <= 1:
                w_attr = canvas['width'] if 'width' in canvas.keys() else 0
                w = int(float(w_attr)) if w_attr else canvas.winfo_reqwidth()
            if not h or h <= 1:
                h_attr = canvas['height'] if 'height' in canvas.keys() else 0
                h = int(float(h_attr)) if h_attr else canvas.winfo_reqheight()
            return max(50, int(w)), max(50, int(h))
        except Exception:
            return 600, 240

    def populate_car_info(self, car: Path):
        try:
            import json
            ui_path = car / 'ui' / 'ui_car.json'
            self.info_txt.delete('1.0', tk.END)
            # Load a preview image if available
            self.preview_label.configure(image='', text='')
            # Only keep preview in Car Info tab
            def find_preview():
                # Prefer first skin's preview image
                skins_dir = car / 'skins'
                try:
                    if skins_dir.exists():
                        # pick first skin folder alphabetically
                        skins = sorted([p for p in skins_dir.iterdir() if p.is_dir()])
                        for s in skins:
                            pv = s / 'preview.png'
                            if pv.exists():
                                return pv
                            pvj = s / 'preview.jpg'
                            if pvj.exists():
                                return pvj
                except Exception:
                    pass
                # Fallback to UI folder previews (avoid logos when possible)
                for name in ('preview.png', 'preview.jpg'):
                    p = car / 'ui' / name
                    if p.exists():
                        return p
                # as a last resort, any png in ui
                for p in (car / 'ui').glob('*.png'):
                    return p
                return None
            try:
                pv = find_preview()
                if pv is not None:
                    # Try Pillow for robust JPG/PNG support; fall back to Tk PhotoImage
                    img_obj = None
                    img_small = None
                    img_large = None
                    try:
                        from PIL import Image, ImageTk  # type: ignore
                        im = Image.open(str(pv))
                        # Prepare sizes: info (400px)
                        def resized(wmax):
                            im2 = im
                            if im2.width > wmax:
                                ratio = wmax / float(im2.width)
                                im2 = im2.resize((int(im2.width * ratio), int(im2.height * ratio)), Image.LANCZOS)
                            return im2
                        im_info = resized(400)
                        img_obj = ImageTk.PhotoImage(im_info)
                    except Exception:
                        try:
                            img = tk.PhotoImage(file=str(pv))
                            # Info image
                            if img.width() > 400:
                                factor = max(1, int(img.width() / 400))
                                img_info = img.subsample(factor, factor)
                            else:
                                img_info = img
                            img_obj = img_info
                            # No additional preview variants needed
                        except Exception:
                            img_obj = None
                    if img_obj is not None:
                        self.preview_label.configure(image=img_obj)
                        self.preview_label.image = img_obj
                    # Only Car Info preview is shown
            except Exception:
                pass
            if ui_path.exists():
                data = json.loads(ui_path.read_text(encoding='utf-8', errors='ignore'))
                name = data.get('name') or ''
                brand = data.get('brand') or ''
                year = data.get('year') or ''
                cls = data.get('class') or ''
                tags = ", ".join([str(t) for t in (data.get('tags') or [])])
                self.info_txt.insert(tk.END, f"Name: {name}\n")
                self.info_txt.insert(tk.END, f"Brand: {brand}\n")
                if year:
                    self.info_txt.insert(tk.END, f"Year: {year}\n")
                if cls:
                    self.info_txt.insert(tk.END, f"Class: {cls}\n")
                if tags:
                    self.info_txt.insert(tk.END, f"Tags: {tags}\n")
                self.info_txt.insert(tk.END, "\n")
                specs = data.get('specs') or {}
                def pick(*keys, default=None):
                    for k in keys:
                        if k in specs and specs[k] not in (None, ''):
                            return specs[k]
                    return default
                if specs:
                    self.info_txt.insert(tk.END, "Key Specs:\n")
                    bhp = pick('bhp', 'power', 'powerHP')
                    if bhp is not None:
                        self.info_txt.insert(tk.END, f"- Power: {bhp} hp\n")
                    tq = pick('torque', 'torqueNm', 'maxTorque')
                    if tq is not None:
                        self.info_txt.insert(tk.END, f"- Torque: {tq} Nm\n")
                    wt = pick('weight', 'mass')
                    if wt is not None:
                        self.info_txt.insert(tk.END, f"- Weight: {wt} kg\n")
                    dt = pick('drivetrain', 'drive')
                    if dt is not None:
                        self.info_txt.insert(tk.END, f"- Drivetrain: {dt}\n")
                    tr = pick('transmission', 'gearbox')
                    if tr is not None:
                        self.info_txt.insert(tk.END, f"- Transmission: {tr}\n")
                    ts = pick('topspeed', 'top_speed', 'maxspeed')
                    if ts is not None:
                        self.info_txt.insert(tk.END, f"- Top speed: {ts} km/h\n")
                    acc = pick('acceleration', 'acc_0_100', 'acc0_100')
                    if acc is not None:
                        self.info_txt.insert(tk.END, f"- 0-100 km/h: {acc}\n")
                    country = pick('country')
                    if country:
                        self.info_txt.insert(tk.END, f"- Country: {country}\n")
                    author = pick('author', 'authors', 'made_by')
                    if author:
                        self.info_txt.insert(tk.END, f"- Author: {author}\n")
                    ver = pick('version')
                    if ver:
                        self.info_txt.insert(tk.END, f"- Version: {ver}\n")
                    self.info_txt.insert(tk.END, "\n")
                if specs:
                    self.info_txt.insert(tk.END, "All Specs:\n")
                    for k, v in specs.items():
                        self.info_txt.insert(tk.END, f"- {k}: {v}\n")
                    self.info_txt.insert(tk.END, "\n")
                desc = data.get('description') or ''
                if desc:
                    # Strip HTML breaks
                    desc = desc.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
                    self.info_txt.insert(tk.END, "Description:\n")
                    self.info_txt.insert(tk.END, desc)
            else:
                self.info_txt.insert(tk.END, 'No ui/ui_car.json found for this car.')
        except Exception:
            self.info_txt.insert(tk.END, 'Failed to load car UI info.')

    def colorize_report_text(self):
        try:
            t = self.txt
            # Define tags
            t.tag_configure('header', foreground=self.BRAND_ORANGE, font=('Segoe UI', 12, 'bold'))
            t.tag_configure('section', foreground=self.BRAND_NAVY, font=('Segoe UI', 10, 'bold'))
            t.tag_configure('ok', foreground='#188038')  # green
            t.tag_configure('bad', foreground='#D93025')  # red
            t.tag_configure('warn', foreground=self.BRAND_ORANGE)
            # Apply header to first line
            t.tag_add('header', '1.0', '1.end')
            # Colorize key checks and status
            start = '1.0'
            while True:
                idx = t.search('Key Checks:', start, stopindex='end')
                if not idx:
                    break
                line_start = idx
                line_end = f"{int(idx.split('.')[0])}.end"
                t.tag_add('section', line_start, line_end)
                start = line_end
            section_labels = (
                'Violations:',
                'Physics Mismatches (grouped):',
                'Gearing Overview:',
                'KN5 Files:',
                'Skins Breakdown:',
                'Textures:',
                'Setup Locked Items (min==max):',
                'Setup Range Issues:',
                'Data Hash Mismatches:',
                'Data Modification Analysis:',
                'Extension Folder Review:',
                'Root Folder Differences:',
                'Suspicious Root Entries:',
                'Anti-Cheat:',
                'UI Summary:',
                'Vehicle Specs:',
            )
            for label in section_labels:
                start = '1.0'
                while True:
                    idx = t.search(label, start, stopindex='end')
                    if not idx:
                        break
                    line_start = idx
                    line_end = f"{int(idx.split('.')[0])}.end"
                    t.tag_add('section', line_start, line_end)
                    start = line_end
            # Icons ✔ / ✅ / ✘ / 🛑 / ⚠ / ⚠️
            for sym, tag in (
                ('✔', 'ok'),
                ('✅', 'ok'),
                ('✘', 'bad'),
                ('🛑', 'bad'),
                ('⚠', 'warn'),
                ('⚠️', 'warn'),
            ):
                start = '1.0'
                sym_len = len(sym)
                while True:
                    idx = t.search(sym, start, stopindex='end')
                    if not idx:
                        break
                    line_end = f"{idx}+{sym_len}c"
                    t.tag_add(tag, idx, line_end)
                    start = line_end
            # Overall Status line
            idx = t.search('Overall Status: PASS', '1.0', stopindex='end')
            if idx:
                t.tag_add('ok', idx, f"{int(idx.split('.')[0])}.end")
            idx = t.search('Overall Status: FAIL', '1.0', stopindex='end')
            if idx:
                t.tag_add('bad', idx, f"{int(idx.split('.')[0])}.end")
            self._apply_report_search_highlight()
        except Exception:
            pass

    def populate_anti_cheat(self, result):
        try:
            self.ac_text.configure(state='normal')
            self.ac_text.delete('1.0', tk.END)
            icon_map = {'fail': '🛑', 'warn': '⚠️', 'pass': '✅'}
            row_tag_map = {'fail': 'row_fail', 'warn': 'row_warn', 'pass': 'row_pass'}
            status_tag_map = {'fail': 'status_fail', 'warn': 'status_warn', 'pass': 'status_pass'}
            if result is None:
                self.ac_summary_var.set('Run Inspect to populate anti-cheat checks.')
                self._set_ac_summary_style(self.BRAND_LIGHT, self.BRAND_BLACK)
                self.ac_text.insert(tk.END, 'No data yet. Run Inspect to populate anti-cheat analysis.')
                return
            info = result.info or {}
            raw_checks = list(info.get('anti_cheat') or [])
            if not raw_checks:
                self.ac_summary_var.set('Anti-cheat module did not produce any results for this inspection.')
                self._set_ac_summary_style(self.BRAND_LIGHT, self.BRAND_BLACK)
                self.ac_text.insert(tk.END, 'No anti-cheat checks were generated. Re-run the inspection with anti-cheat enabled.')
                return
            from collections import Counter
            counts = Counter(str(item.get('status') or '').lower() for item in raw_checks)
            fail_total = counts.get('fail', 0)
            warn_total = counts.get('warn', 0)
            pass_total = counts.get('pass', 0)
            flagged_total = fail_total + warn_total
            count_bits: list[str] = []
            if fail_total:
                count_bits.append(f"🛑 Fails {fail_total}")
            if warn_total:
                count_bits.append(f"⚠ Warnings {warn_total}")
            if pass_total:
                count_bits.append(f"✅ Passes {pass_total}")
            checks = [i for i in raw_checks if str(i.get('status') or '').lower() in ('warn', 'fail')]
            f = (self.ac_filter_var.get() if hasattr(self, 'ac_filter_var') else 'all')
            q = (self.ac_search_var.get().strip().lower() if hasattr(self, 'ac_search_var') else '')
            def _match(item):
                st = str(item.get('status') or '').lower()
                if f != 'all' and st != f:
                    return False
                if q:
                    hay = ' '.join([str(item.get('id') or ''), str(item.get('label') or ''), str(item.get('detail') or '')]).lower()
                    if q not in hay:
                        return False
                return True
            checks = [i for i in checks if _match(i)]
            checks.sort(key=lambda c: (0 if str(c.get('status') or '').lower() == 'fail' else 1, str(c.get('id') or '')))
            if flagged_total:
                if checks:
                    summary_text = f"Showing {len(checks)} of {flagged_total} flagged checks"
                    if count_bits:
                        summary_text += " — " + ' · '.join(count_bits)
                else:
                    summary_text = "No anti-cheat checks match the current filter/search."
                    if count_bits:
                        summary_text += ' — ' + ' · '.join(count_bits)
            else:
                summary_text = "✅ All anti-cheat checks passed."
                if count_bits:
                    summary_text += f" ({' · '.join(count_bits)})"
            self.ac_summary_var.set(summary_text)
            if fail_total:
                self._set_ac_summary_style('#FDECEA', '#8B1A1A')
            elif warn_total:
                self._set_ac_summary_style('#FFF7ED', '#8B5E00')
            else:
                self._set_ac_summary_style('#F1F8E9', '#1B5E20')
            if not checks:
                if flagged_total:
                    self.ac_text.insert(tk.END, 'No anti-cheat checks match the current filter or search terms.')
                else:
                    msg = 'All anti-cheat checks passed. No warnings or failures detected.'
                    self.ac_text.insert(tk.END, msg)
                    self.ac_text.tag_add('row_pass', '1.0', 'end-1c')
                return
            car = Path(self.car_var.get()).resolve()
            def _open_os_path(p: Path | str):
                try:
                    import platform, subprocess, os
                    sys = platform.system()
                    sp = str(p)
                    if sys == 'Windows':
                        os.startfile(sp)  # type: ignore
                    elif sys == 'Darwin':
                        subprocess.Popen(['open', sp])
                    else:
                        subprocess.Popen(['xdg-open', sp])
                except Exception:
                    pass
            for item in checks:
                status = str(item.get('status') or '').lower()
                icon = icon_map.get(status, '⚠️')
                row_tag = row_tag_map.get(status, 'row_warn')
                status_tag = status_tag_map.get(status, 'status_warn')
                line = f"{icon} [{item.get('id','')}] {item.get('label','')}"
                line_start = self.ac_text.index('end')
                self.ac_text.insert(tk.END, line + "\n")
                line_end = self.ac_text.index('end-1c')
                self.ac_text.tag_add(row_tag, line_start, line_end)
                try:
                    icon_idx = self.ac_text.search(icon, line_start, line_end)
                    if icon_idx:
                        self.ac_text.tag_add(status_tag, icon_idx, f"{icon_idx}+{len(icon)}c")
                except Exception:
                    pass
                detail = str(item.get('detail') or AC_HINTS.get(item.get('id') or '', '') or 'See competition guidelines for remediation.')
                if detail:
                    detail_text = f"    • {detail}\n"
                    detail_start = self.ac_text.index('end')
                    self.ac_text.insert(tk.END, detail_text)
                    detail_end = self.ac_text.index('end-1c')
                    self.ac_text.tag_add(row_tag, detail_start, detail_end)
                    self.ac_text.tag_add('detail_text', detail_start, detail_end)
                items = item.get('items') or []
                for it in items[:50]:
                    p = Path(it)
                    if not p.is_absolute():
                        p = car / it
                    disp = f"      ↳ {it}\n"
                    s = self.ac_text.index('end')
                    self.ac_text.insert(tk.END, disp)
                    e = self.ac_text.index('end-1c')
                    self.ac_text.tag_add(row_tag, s, e)
                    self.ac_text.tag_add('detail_text', s, e)
                    tagname = f"link_{item.get('id','')}_{hash(it)}"
                    self.ac_text.tag_add(tagname, s, e)
                    self.ac_text.tag_config(tagname, foreground=self.BRAND_NAVY, underline=True)
                    def _mk_open(path_str: str):
                        return lambda _e: _open_os_path(path_str)
                    self.ac_text.tag_bind(tagname, '<Button-1>', _mk_open(str(p)))
                    try:
                        parent_path = str(Path(p).parent)
                        self.ac_text.tag_bind(tagname, '<Button-3>', _mk_open(parent_path))
                    except Exception:
                        pass
                if items and len(items) > 50:
                    more_start = self.ac_text.index('end')
                    self.ac_text.insert(tk.END, f"      ↳ ... and {len(items)-50} more\n")
                    more_end = self.ac_text.index('end-1c')
                    self.ac_text.tag_add(row_tag, more_start, more_end)
                    self.ac_text.tag_add('detail_text', more_start, more_end)
        except Exception:
            pass

    def export_html(self):
        if not self._ensure_authenticated():
            return
        if self._busy:
            return
        try:
            if not hasattr(self, 'last_result'):
                messagebox.showinfo('Export HTML', 'No report available. Run Inspect first.')
                return
            # Build simple HTML with brand colors
            res = getattr(self, 'last_result', None)
            html = self.build_html_report(res)
            dest = filedialog.asksaveasfilename(title='Export Colored Report (HTML)', defaultextension='.html',
                                                filetypes=[('HTML', '*.html'), ('All files', '*.*')])
            if not dest:
                return
            Path(dest).write_text(html, encoding='utf-8')
            self.status.set(f'Exported HTML to {dest}')
            # Auto-open the exported HTML
            try:
                import platform, subprocess, os
                sys = platform.system()
                if sys == 'Windows':
                    os.startfile(dest)  # type: ignore
                elif sys == 'Darwin':
                    subprocess.Popen(['open', dest])
                else:
                    subprocess.Popen(['xdg-open', dest])
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror('Export HTML', f'Export failed: {e}')

    def build_html_report(self, result):
        # HTML with brand header and embedded icon image
        from inspector.report import format_report_text
        import html as _html, base64, io
        esc = _html.escape
        # Prepare header icon as data URI (PNG), if available
        icon_data_uri = ''
        try:
            icon_path = Path('icon.ico')
            if icon_path.exists():
                try:
                    from PIL import Image
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore', UserWarning)
                        with Image.open(str(icon_path)) as im:
                            bio = io.BytesIO()
                            im.save(bio, format='PNG')
                            b64 = base64.b64encode(bio.getvalue()).decode('ascii')
                            icon_data_uri = f'data:image/png;base64,{b64}'
                except Exception:
                    # Try to embed raw .ico
                    b = icon_path.read_bytes()
                    b64 = base64.b64encode(b).decode('ascii')
                    icon_data_uri = f'data:image/x-icon;base64,{b64}'
        except Exception:
            pass
        # Body text with simple colorization
        txt = format_report_text(result)
        # Remove ASCII power/torque curves from export body
        lines = txt.splitlines()
        filtered = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith('Power Curve (') or line.startswith('Torque Curve ('):
                # Skip this line and next 2 lines ((spark + max))
                i += 3
                continue
            filtered.append(line)
            i += 1
        filtered = self._strip_anti_cheat_lines(filtered)
        txt = '\n'.join(filtered)
        def colorize(s: str) -> str:
            s = s.replace('✅', '<span style="color:#188038;">✅</span>')
            s = s.replace('✔', '<span style="color:#188038;">✔</span>')
            s = s.replace('🛑', '<span style="color:#D93025;">🛑</span>')
            s = s.replace('✘', '<span style="color:#D93025;">✘</span>')
            s = s.replace('⚠️', f'<span style="color:{self.BRAND_ORANGE};">⚠️</span>')
            s = s.replace('⚠', f'<span style="color:{self.BRAND_ORANGE};">⚠</span>')
            s = s.replace('eF Drift Car Scrutineer Report', f'<span style="color:{self.BRAND_ORANGE}; font-weight:bold;">eF Drift Car Scrutineer Report</span>')
            for label in (
                'Key Checks:',
                'Violations:',
                'Physics Mismatches (grouped):',
                'Gearing Overview:',
                'KN5 Files:',
                'Skins Breakdown:',
                'Textures:',
                'Setup Locked Items (min==max):',
                'Setup Range Issues:',
                'Data Hash Mismatches:',
                'Data Modification Analysis:',
                'Extension Folder Review:',
                'Root Folder Differences:',
                'Suspicious Root Entries:',
                'Anti-Cheat:',
                'UI Summary:',
                'Vehicle Specs:',
            ):
                s = s.replace(label, f'<span style="color:{self.BRAND_NAVY}; font-weight:bold;">{label}</span>')
            s = s.replace('Overall Status: PASS', '<span style="color:#188038; font-weight:bold;">Overall Status: PASS</span>')
            s = s.replace('Overall Status: FAIL', '<span style="color:#D93025; font-weight:bold;">Overall Status: FAIL</span>')
            return s
        body = '<br/>'.join(colorize(esc(line)) for line in txt.splitlines())
        # Header info
        car_name = Path(self.car_var.get()).name or 'Unknown Car'
        try:
            ui = getattr(self, 'last_result', None)
            if ui and isinstance(ui.info, dict):
                nm = ui.info.get('ui', {}).get('name')
                if nm:
                    car_name = str(nm)
        except Exception:
            pass
        icon_html = f"<img src='{icon_data_uri}' alt='icon' style='width:28px;height:28px;margin-right:10px;vertical-align:middle;'/>" if icon_data_uri else ''
        # Embed first skin preview under header
        preview_data_uri = ''
        try:
            car = Path(self.car_var.get()).resolve()
            def _find_preview_file(c: Path):
                skins = c / 'skins'
                try:
                    if skins.exists():
                        for s in sorted([p for p in skins.iterdir() if p.is_dir()]):
                            pv = s / 'preview.png'
                            if pv.exists():
                                return pv
                            pvj = s / 'preview.jpg'
                            if pvj.exists():
                                return pvj
                except Exception:
                    pass
                for name in ('preview.png', 'preview.jpg'):
                    p = c / 'ui' / name
                    if p.exists():
                        return p
                for p in (c / 'ui').glob('*.png'):
                    return p
                return None
            pvf = _find_preview_file(car)
            if pvf is not None:
                mime = 'image/png' if pvf.suffix.lower() == '.png' else 'image/jpeg'
                try:
                    from PIL import Image
                    with Image.open(str(pvf)) as im:
                        wmax = 640
                        if im.width > wmax:
                            ratio = wmax / float(im.width)
                            im = im.resize((int(im.width * ratio), int(im.height * ratio)), Image.LANCZOS)
                        bio2 = io.BytesIO()
                        im.save(bio2, format='PNG')
                        b64p = base64.b64encode(bio2.getvalue()).decode('ascii')
                        preview_data_uri = f'data:image/png;base64,{b64p}'
                except Exception:
                    b = pvf.read_bytes()
                    b64p = base64.b64encode(b).decode('ascii')
                    preview_data_uri = f'data:{mime};base64,{b64p}'
        except Exception:
            pass
        preview_html = f"<div style='margin:8px 0 16px 0;'><img src='{preview_data_uri}' alt='preview' style='max-width:100%; width:640px; border:1px solid #eee; border-radius:6px;'/></div>" if preview_data_uri else ''

        # Build inline SVG graph for Power/Torque
        def build_graph_svg():
            try:
                # Recreate hp/tq points similarly to draw_graphs
                import json, math
                car = Path(self.car_var.get()).resolve()
                hp_pts = []
                tq_pts = []
                ui_path = car / 'ui' / 'ui_car.json'
                if ui_path.exists():
                    try:
                        ui = json.loads(ui_path.read_text(encoding='utf-8', errors='ignore'))
                        pc = ui.get('powerCurve')
                        tc = ui.get('torqueCurve')
                        if isinstance(pc, list) and isinstance(tc, list):
                            hp_pts = [(float(x), float(y)) for x, y in pc]
                            tq_pts = [(float(x), float(y)) for x, y in tc]
                    except Exception:
                        pass
                if not hp_pts:
                    from inspector.lut_parser import read_lut
                    lut = car / 'data' / 'power.lut'
                    if lut.exists():
                        hp_pts = read_lut(lut)
                        tq_pts = []
                        for (rpm, hp) in hp_pts:
                            w = hp * 745.699872
                            t_nm = w / (2 * math.pi * (rpm/60.0 if rpm > 0 else 1.0))
                            tq_pts.append((rpm, t_nm))
                if not hp_pts and not tq_pts:
                    return ''
                # Dimensions and padding
                W, H = 820, 260
                pad_l, pad_r, pad_t, pad_b = 40, 10, 10, 25
                plot_w = W - pad_l - pad_r
                plot_h = H - pad_t - pad_b
                xs = [p[0] for p in (hp_pts + tq_pts)]
                min_x, max_x = min(xs), max(xs)
                if max_x <= min_x:
                    max_x = min_x + 1.0
                hp_max = max([p[1] for p in hp_pts]) if hp_pts else 1.0
                tq_max = max([p[1] for p in tq_pts]) if tq_pts else 1.0
                def scale(points, y_max):
                    out = []
                    for (x,y) in points:
                        nx = (x - min_x) / (max_x - min_x)
                        ny = (y / y_max) if y_max else 0
                        px = pad_l + nx * plot_w
                        py = pad_t + (1.0 - ny) * plot_h
                        out.append(f"{px:.1f},{py:.1f}")
                    return ' '.join(out)
                hp_poly = scale(hp_pts, hp_max) if hp_pts else ''
                tq_poly = scale(tq_pts, tq_max) if tq_pts else ''
                # Build simple SVG with axes ticks and two polylines
                svg = [f"<svg width='{W}' height='{H}' xmlns='http://www.w3.org/2000/svg'>"]
                # Background and plot area
                svg.append(f"<rect x='0' y='0' width='{W}' height='{H}' fill='white' />")
                svg.append(f"<rect x='{pad_l}' y='{pad_t}' width='{plot_w}' height='{plot_h}' fill='none' stroke='{self.BRAND_LIGHT}' />")
                # X ticks
                nt = 6
                for i in range(nt):
                    v = min_x + (max_x - min_x) * i / (nt - 1)
                    label = int(round(v / 50.0) * 50)
                    nx = (v - min_x) / (max_x - min_x)
                    px = pad_l + nx * plot_w
                    yb = pad_t + plot_h
                    svg.append(f"<line x1='{px:.1f}' y1='{yb}' x2='{px:.1f}' y2='{yb+4}' stroke='{self.BRAND_LIGHT}' />")
                    svg.append(f"<text x='{px:.1f}' y='{yb+16}' font-size='10' text-anchor='middle' fill='{self.BRAND_BLACK}'>{label}</text>")
                # Y ticks (left hp)
                nt_y = 5
                for i in range(nt_y):
                    v = hp_max * i / (nt_y - 1)
                    ny = (v / hp_max) if hp_max else 0
                    py = pad_t + (1.0 - ny) * plot_h
                    svg.append(f"<line x1='{pad_l-4}' y1='{py:.1f}' x2='{pad_l}' y2='{py:.1f}' stroke='{self.BRAND_ORANGE}' />")
                    svg.append(f"<text x='{pad_l-6}' y='{py+3:.1f}' font-size='10' text-anchor='end' fill='{self.BRAND_ORANGE}'>{int(round(v))}</text>")
                # Y ticks (right Nm)
                for i in range(nt_y):
                    v = tq_max * i / (nt_y - 1)
                    ny = (v / tq_max) if tq_max else 0
                    py = pad_t + (1.0 - ny) * plot_h
                    x2 = pad_l + plot_w
                    svg.append(f"<line x1='{x2}' y1='{py:.1f}' x2='{x2+4}' y2='{py:.1f}' stroke='{self.BRAND_NAVY}' />")
                    svg.append(f"<text x='{x2+6}' y='{py+3:.1f}' font-size='10' text-anchor='start' fill='{self.BRAND_NAVY}'>{int(round(v))}</text>")
                # Curves
                if hp_poly:
                    svg.append(f"<polyline fill='none' stroke='{self.BRAND_ORANGE}' stroke-width='2' points='{hp_poly}' />")
                if tq_poly:
                    svg.append(f"<polyline fill='none' stroke='{self.BRAND_NAVY}' stroke-width='2' points='{tq_poly}' />")
                svg.append(f"<text x='{pad_l+10}' y='{pad_t+14}' font-size='12' fill='{self.BRAND_ORANGE}'>Power (hp)</text>")
                svg.append(f"<text x='{pad_l+10}' y='{pad_t+30}' font-size='12' fill='{self.BRAND_NAVY}'>Torque (Nm)</text>")
                svg.append("</svg>")
                return '\n'.join(svg)
            except Exception:
                return ''

        graph_svg = build_graph_svg()
        def build_gearing_svg():
            try:
                car = Path(self.car_var.get()).resolve()
                submitted = self._load_car_gearing(car)
                ref_entry = self._get_reference_entry(getattr(result, 'matched_reference', None))
                reference = self._extract_reference_gearing(ref_entry)
                if not submitted and not reference:
                    return ''
                datasets = []
                if submitted:
                    datasets.append(('Submitted', self.BRAND_ORANGE, submitted['overall']))
                if reference:
                    datasets.append(('Reference', '#4f7ec2', reference['overall']))
                max_gears = max(len(d[2]) for d in datasets)
                if max_gears == 0:
                    return ''
                y_max = max(max((r for r in ratios if r is not None), default=0.0) for _, _, ratios in datasets)
                if y_max <= 0:
                    y_max = 1.0
                pad_l, pad_r, pad_t, pad_b = 60, 40, 40, 50
                width, height = 720, 260
                plot_w = width - pad_l - pad_r
                plot_h = height - pad_t - pad_b
                svg = [f"<svg viewBox='0 0 {width} {height}' preserveAspectRatio='xMidYMid meet'>",
                       f"<rect x='{pad_l}' y='{pad_t}' width='{plot_w}' height='{plot_h}' fill='{self.BRAND_SURFACE}' stroke='{self.BRAND_OUTLINE}' />"]
                overlap = False
                if len(datasets) == 2 and datasets[0][2] == datasets[1][2]:
                    overlap = True
                # grid
                for i in range(max_gears):
                    frac = i / (max_gears - 1) if max_gears > 1 else 0
                    x = pad_l + frac * plot_w
                    svg.append(f"<line x1='{x:.1f}' y1='{pad_t}' x2='{x:.1f}' y2='{pad_t+plot_h}' stroke='#2d2d2d' />")
                    svg.append(f"<line x1='{x:.1f}' y1='{pad_t+plot_h}' x2='{x:.1f}' y2='{pad_t+plot_h+6}' stroke='#444444' />")
                    svg.append(f"<text x='{x:.1f}' y='{pad_t+plot_h+18}' font-size='10' text-anchor='middle' fill='{self.BRAND_BLACK}'>G{i+1}</text>")
                svg.append(f"<text x='{(pad_l+plot_w/2):.1f}' y='{pad_t+plot_h+32}' font-size='10' text-anchor='middle' fill='#555555'>Gear Number</text>")
                for i in range(5):
                    frac = i / 4 if 4 else 0
                    y = pad_t + plot_h - frac * plot_h
                    value = frac * y_max
                    svg.append(f"<line x1='{pad_l-4}' y1='{y:.1f}' x2='{pad_l}' y2='{y:.1f}' stroke='{self.BRAND_OUTLINE}' />")
                    svg.append(f"<text x='{pad_l-8}' y='{y+3:.1f}' font-size='10' text-anchor='end' fill='#555555'>{value:.2f}</text>")
                for label, color, ratios in datasets:
                    points = []
                    for idx, ratio in enumerate(ratios):
                        if ratio is None:
                            continue
                        frac_x = idx / (max_gears - 1) if max_gears > 1 else 0
                        x = pad_l + frac_x * plot_w
                        frac_y = ratio / y_max if y_max else 0
                        y = pad_t + plot_h - frac_y * plot_h
                        points.append((x, y))
                    if len(points) >= 2:
                        pts = ' '.join(f"{x:.1f},{y:.1f}" for x, y in points)
                        svg.append(f"<polyline fill='none' stroke='{color}' stroke-width='2' points='{pts}' />")
                    for x, y in points:
                        svg.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='3' fill='{color}' />")
                legend_x = pad_l + 10
                legend_y = pad_t - 24
                for label, color, _ in datasets:
                    svg.append(f"<rect x='{legend_x}' y='{legend_y}' width='12' height='12' fill='{color}' />")
                    svg.append(f"<text x='{legend_x+18}' y='{legend_y+10}' font-size='11' fill='{self.BRAND_BLACK}'>{label}</text>")
                    legend_y += 16
                if overlap:
                    svg.append(f"<text x='{pad_l+plot_w}' y='{pad_t - 10}' font-size='10' text-anchor='end' fill='{self.BRAND_BLACK}'>Submitted and reference gearing identical</text>")
                svg.append("</svg>")
                return '\n'.join(svg)
            except Exception:
                return ''

        def build_chassis_html():
            try:
                info = getattr(result, 'info', {}) or {}
                metrics = []
                def val(key):
                    v = info.get(key)
                    return float(v) if isinstance(v, (int, float)) else None
                metrics.append(('Mass (kg)', val('total_mass'), val('reference_total_mass') if 'reference_total_mass' in info else None, 'kg'))
                fb = val('front_bias')
                ref_fb = None
                if isinstance(info.get('reference_front_bias'), (int, float, float)):
                    ref_fb = float(info['reference_front_bias'])
                if fb is not None:
                    metrics.append(('CG Front Bias', fb, ref_fb, 'ratio'))
                metrics.append(('Front Track (m)', val('front_track'), info.get('reference_front_track') if isinstance(info.get('reference_front_track'), (int, float)) else None, 'm'))
                metrics.append(('Rear Track (m)', val('rear_track'), info.get('reference_rear_track') if isinstance(info.get('reference_rear_track'), (int, float)) else None, 'm'))
                metrics.append(('Wheelbase (m)', val('wheelbase'), info.get('reference_wheelbase') if isinstance(info.get('reference_wheelbase'), (int, float)) else None, 'm'))
                fuel = info.get('fuel_tank_pos')
                if isinstance(fuel, (list, tuple)) and len(fuel) >= 3:
                    fx = float(fuel[0])
                    fz = float(fuel[2])
                    metrics.append(('Fuel Tank X (m)', fx, None, 'm'))
                    metrics.append(('Fuel Tank Z (m)', fz, None, 'm'))
                metrics.append(('Steer Lock (°)', val('steer_lock'), info.get('reference_steer_lock') if isinstance(info.get('reference_steer_lock'), (int, float)) else None, 'deg'))
                metrics.append(('Wheel Angle (°)', val('derived_wheel_angle_deg'), info.get('reference_steer_angle_deg') if isinstance(info.get('reference_steer_angle_deg'), (int, float)) else None, 'deg'))
                processed = []
                for label, sub, ref, unit in metrics:
                    if sub is None and ref is None:
                        continue
                    lab = label
                    if unit == 'ratio':
                        lab = f"{label} (%)"
                        if sub is not None:
                            sub = sub * 100.0
                        if ref is not None:
                            ref = ref * 100.0
                    processed.append((lab, sub, ref))
                if not processed:
                    return ''
                magnitudes = []
                for _, sub_val, ref_val in processed:
                    if sub_val is not None:
                        magnitudes.append(abs(sub_val))
                    if ref_val is not None:
                        magnitudes.append(abs(ref_val))
                max_mag = max(magnitudes) if magnitudes else 1.0
                if max_mag == 0:
                    max_mag = 1.0
                max_width = 280
                def bar_html(value, cls):
                    if value is None:
                        return "<div class='metric-bar empty'>n/a</div>"
                    mag = abs(value)
                    width = max(4, (mag / max_mag) * max_width)
                    label = f"{mag:.3f}" if mag != int(mag) else f"{int(mag)}"
                    if value < 0:
                        label = f"({label})"
                        cls += ' negative'
                    return f"<div class='metric-bar {cls}' style='width:{width}px'><span>{label}</span></div>"
                html = ["<div class='chart-section'><div class='chart-title'>Chassis Balance</div>"]
                for label, sub_val, ref_val in processed:
                    html.append(f"<div class='metric-row'><div class='metric-label'>{label}</div><div class='metric-bars'>{bar_html(sub_val, 'submitted')} {bar_html(ref_val, 'reference')}</div></div>")
                html.append("</div>")
                return '\n'.join(html)
            except Exception:
                return ''

        def build_tyre_html():
            try:
                info = getattr(result, 'info', {}) or {}
                submitted_front = info.get('front_tyre_width_mm')
                submitted_rear = info.get('rear_tyre_width_mm')
                ref_front = info.get('reference_front_tyre_width_mm')
                ref_rear = info.get('reference_rear_tyre_width_mm')
                rows = []
                if submitted_front is not None or submitted_rear is not None:
                    rows.append(('Submitted', submitted_front, submitted_rear))
                if ref_front is not None or ref_rear is not None:
                    rows.append(('Reference', ref_front, ref_rear))
                if not rows:
                    return ''
                values = [v for row in rows for v in row[1:] if isinstance(v, (int, float))]
                max_width = max(values) if values else 1.0
                if max_width == 0:
                    max_width = 1.0
                max_px = 260
                html = ["<div class='chart-section'><div class='chart-title'>Tyre Footprint</div>"]
                for label, front, rear in rows:
                    def bar(value, cls):
                        if value is None:
                            return "<div class='metric-bar empty'>n/a</div>"
                        width = max(6, (value / max_width) * max_px)
                        return f"<div class='metric-bar {cls}' style='width:{width}px'><span>{int(value)}</span></div>"
                    html.append(f"<div class='tyre-row'><div class='tyre-label'>{label}</div><div class='metric-bars'>{bar(front, 'submitted')} {bar(rear, 'reference')}</div></div>")
                html.append("</div>")
                return '\n'.join(html)
            except Exception:
                return ''

        def build_summary_html():
            try:
                info = getattr(result, 'info', {}) or {}
                violations = result.rule_violations or []

                def no_violation(sub: str) -> bool:
                    return not any(sub in v for v in violations)

                sections: dict[str, list[dict[str, object]]] = {}
                spec_compare = info.get('spec_compare') or {}

                def html_spec_value(spec_key: str, base_value: str, extra_suffix: str = '', base_tooltip: str = '') -> tuple[str, str, bool]:
                    cmp = spec_compare.get(spec_key)
                    tooltip_parts: list[str] = []
                    if base_tooltip:
                        tooltip_parts.append(base_tooltip)
                    if cmp:
                        value = f"{cmp.get('submitted_display', base_value)} (ref {cmp.get('reference_display', '')}){extra_suffix}"
                        tooltip_parts.append(f"Ref {cmp.get('reference_display', '')} (Δ {cmp.get('delta_display', '')})")
                        spec_fail = not cmp.get('within_tolerance', True)
                    else:
                        value = f"{base_value}{extra_suffix}"
                        spec_fail = False
                    tooltip_text = ' | '.join(p for p in tooltip_parts if p)
                    return value, tooltip_text, spec_fail

                default_tooltips = {
                    'Overall': 'PASS when physics fingerprint matches and no rule violations are present.',
                    'Matched Ref': 'Reference car matched from reference_cars index for this inspection.',
                    'Year': 'Model year sourced from ui/ui_car.json.',
                    'Name': 'Display name from ui/ui_car.json.',
                    'Brand': 'Manufacturer from ui/ui_car.json.',
                    'Drivetrain': 'Traction type from data/drivetrain.ini; competition expects RWD.',
                    'Mass': 'TOTALMASS from data/car.ini versus the enforced minimum.',
                    'Final Drive': 'Overall final drive ratio compared with drift target range.',
                    '3rd Gear Overall': '3rd overall ratio compared with drift target range.',
                    'Wheelbase': 'Wheelbase from data/suspensions.ini.',
                    'Front track': 'Front track width from data/suspensions.ini:FRONT:TRACK.',
                    'Rear track': 'Rear track width from data/suspensions.ini:REAR:TRACK.',
                    'Fuel Tank': 'Fuel tank position from data/car.ini:FUELTANK; hover for clearance notes.',
                    'Front Bias': 'CG_LOCATION front weight bias vs enforced target.',
                    'Front Tyre': 'Front tyre width and allowed range from tyres.ini.',
                    'Rear Tyre': 'Rear tyre width and maximum from tyres.ini.',
                    'Steering angle': 'Measured/derived steering angle versus rule limit.',
                    'Steer inner': 'Inner steering angle sample from CM/simulation data.',
                    'Steer outer': 'Outer steering angle sample from CM/simulation data.',
                    'Steer L': 'Left steering lock sample.',
                    'Steer R': 'Right steering lock sample.',
                    'STEER_LOCK': 'STEER_LOCK from data/car.ini compared with reference.',
                    'STEER_RATIO': 'STEER_RATIO from data/car.ini compared with reference.',
                    'KN5 sizes': 'Largest KN5 file compared against allowed size.',
                    'Skin sizes': 'Largest skin folder size against rule limit.',
                    'KN5 files': 'Number of KN5 model files detected.',
                    'Model caps': 'Triangles/objects total against competition caps.',
                    'Caps source': 'Indicates triangle/object stats source.',
                    'Skins': 'Number of skin folders included with the car.',
                    'Largest skin': 'Largest skin folder size.',
                    'Data Files': 'Delta between submitted data/ files and reference list.',
                    'Data files': 'Delta between submitted data/ files and reference list.',
                    'Fallback ref': 'Fallback reference used when no exact match found.',
                    'Audit': 'Texture audit summary; unchecked files require review.',
                    'Power peak': 'Maximum horsepower and corresponding RPM.',
                    'Torque peak': 'Maximum torque recorded from curves.',
                    'Torque @4k': 'Interpolated torque at 4,000 rpm vs target.',
                    'Torque @5.5k': 'Interpolated torque at 5,500 rpm vs target.',
                    'Power @6.5k': 'Interpolated power at 6,500 rpm vs target.',
                    'Colliders': 'Collider dimensions validated against track/wheelbase.',
                    'Setup locks': 'Count of locked setup sliders (MIN == MAX).',
                }

                def add(section: str, label: str, value, ok=None, warn: bool = False, tooltip: str = '') -> None:
                    if value is None:
                        return
                    val_str = str(value)
                    if not val_str:
                        return
                    tip = tooltip or default_tooltips.get(label, '')
                    sections.setdefault(section, []).append({
                        'label': label,
                        'value': val_str,
                        'ok': ok,
                        'warn': warn,
                        'tooltip': tip,
                    })

                overall_ok = result.exact_physics_match and not violations
                add('Status', 'Overall', 'PASS' if overall_ok else 'FAIL', ok=overall_ok, warn=not overall_ok)
                add('Status', 'Matched Ref', result.matched_reference or 'None', ok=bool(result.matched_reference))

                ui_meta = info.get('ui') or {}
                year_val = info.get('year')
                if year_val is not None:
                    add('Vehicle', 'Year', year_val, ok=no_violation('Year '))
                if isinstance(ui_meta, dict):
                    nm = ui_meta.get('name')
                    br = ui_meta.get('brand')
                    if nm:
                        add('Vehicle', 'Name', nm)
                    if br:
                        add('Vehicle', 'Brand', br)

                dtype = info.get('drivetrain') or ''
                ref_drive = info.get('reference_drivetrain')
                drive_value = dtype
                drive_ok = str(dtype).upper() == 'RWD'
                drive_tooltip = default_tooltips.get('Drivetrain', '')
                if ref_drive:
                    if dtype:
                        drive_value = f"{dtype} (ref {ref_drive})"
                    else:
                        drive_value = f"ref {ref_drive}"
                    drive_tooltip = f"Reference drivetrain: {ref_drive}"
                    if dtype and str(dtype).strip().upper() != str(ref_drive).strip().upper():
                        drive_ok = False
                add('Drivetrain & Mass', 'Drivetrain', drive_value, ok=drive_ok, tooltip=drive_tooltip)
                tm = info.get('total_mass')
                exp_tm = info.get('expected_min_total_mass_kg')
                if tm is not None:
                    base_tooltip = f"Min {exp_tm} kg" if exp_tm is not None else ''
                    mass_value, mass_tooltip, mass_fail = html_spec_value('total_mass', f"{tm} kg", '', base_tooltip)
                    mass_ok = (no_violation('TOTALMASS') if exp_tm is not None else True) and not mass_fail
                    add('Drivetrain & Mass', 'Mass', mass_value, ok=mass_ok, tooltip=mass_tooltip)
                final_ratio = info.get('final_drive_ratio')
                drift_fd_range = info.get('drift_final_ratio_range') or (None, None)
                if final_ratio is not None:
                    suffix = ''
                    base_tooltip = ''
                    if drift_fd_range[0] is not None and drift_fd_range[1] is not None:
                        suffix = f" (target {drift_fd_range[0]:.1f}-{drift_fd_range[1]:.1f})"
                        base_tooltip = f"Target {drift_fd_range[0]:.1f}-{drift_fd_range[1]:.1f}"
                    final_value, final_tooltip, final_fail = html_spec_value('final_drive_ratio', f"{final_ratio:.2f}", suffix, base_tooltip)
                    drift_warn = bool(info.get('drift_final_ratio_warn'))
                    ok_flag = (not drift_warn) and not final_fail
                    warn_flag = drift_warn and not final_fail
                    add('Drivetrain & Mass', 'Final Drive', final_value, ok=ok_flag, warn=warn_flag, tooltip=final_tooltip)
                third_ratio = info.get('third_gear_overall')
                drift_third_range = info.get('drift_third_ratio_range') or (None, None)
                if third_ratio is not None:
                    suffix = ''
                    base_tooltip = ''
                    if drift_third_range[0] is not None and drift_third_range[1] is not None:
                        suffix = f" (target {drift_third_range[0]:.1f}-{drift_third_range[1]:.1f})"
                        base_tooltip = f"Target {drift_third_range[0]:.1f}-{drift_third_range[1]:.1f}"
                    third_value, third_tooltip, third_fail = html_spec_value('third_gear_overall', f"{third_ratio:.2f}", suffix, base_tooltip)
                    drift_warn = bool(info.get('drift_third_ratio_warn'))
                    ok_flag = (not drift_warn) and not third_fail
                    warn_flag = drift_warn and not third_fail
                    add('Drivetrain & Mass', '3rd Gear Overall', third_value, ok=ok_flag, warn=warn_flag, tooltip=third_tooltip)

                wb = info.get('wheelbase')
                if wb is not None:
                    wb_value, wb_tooltip, wb_fail = html_spec_value('wheelbase', f"{wb} m", '', 'data/suspensions.ini:BASIC:WHEELBASE')
                    add('Chassis', 'Wheelbase', wb_value, ok=not wb_fail, tooltip=wb_tooltip)
                ft = info.get('front_track')
                if ft is not None:
                    ft_value, ft_tooltip, ft_fail = html_spec_value('front_track', f"{ft} m", '', 'data/suspensions.ini:FRONT:TRACK')
                    add('Chassis', 'Front track', ft_value, ok=not ft_fail, tooltip=ft_tooltip)
                rt = info.get('rear_track')
                if rt is not None:
                    rt_value, rt_tooltip, rt_fail = html_spec_value('rear_track', f"{rt} m", '', 'data/suspensions.ini:REAR:TRACK')
                    add('Chassis', 'Rear track', rt_value, ok=not rt_fail, tooltip=rt_tooltip)
                ftp = info.get('fuel_tank_pos')
                fuel_flags = info.get('fuel_tank_flags') or []
                tip_parts: list[str] = ['data/car.ini:FUELTANK:POSITION']
                spec_fail = False
                for axis_key in ('fuel_tank_x', 'fuel_tank_y', 'fuel_tank_z'):
                    cmp = spec_compare.get(axis_key)
                    if cmp:
                        tip_parts.append(f"{cmp['label']}: ref {cmp['reference_display']} (Δ {cmp['delta_display']})")
                        spec_fail = spec_fail or not cmp.get('within_tolerance', True)
                tip_parts.extend(fuel_flags)
                d_front = info.get('fuel_tank_distance_to_front_axle')
                d_rear = info.get('fuel_tank_distance_to_rear_axle')
                try:
                    if isinstance(d_front, (int, float)):
                        tip_parts.append(f"front axle clearance {d_front:.2f} m")
                except Exception:
                    pass
                try:
                    if isinstance(d_rear, (int, float)):
                        tip_parts.append(f"rear axle clearance {d_rear:.2f} m")
                except Exception:
                    pass
                tooltip = ' | '.join(tip_parts)
                ok_flag = (not fuel_flags) and no_violation('Fuel tank POSITION') and not spec_fail
                value: str | None = None
                if isinstance(ftp, (list, tuple)) and len(ftp) == 3:
                    try:
                        fx, fy, fz = ftp
                        value = f"({fx:.3f}, {fy:.3f}, {fz:.3f})"
                    except Exception:
                        value = str(ftp)
                elif ftp is not None:
                    value = str(ftp)
                if value is not None:
                    add('Chassis', 'Fuel Tank', value, ok=ok_flag, warn=False, tooltip=tooltip)

                fb = info.get('front_bias')
                exp_fb = info.get('expected_front_bias')
                if fb is not None:
                    fb_base_tooltip = f"Expected {exp_fb:.3f}±0.005" if exp_fb is not None else ''
                    fb_value, fb_tooltip, fb_fail = html_spec_value('front_bias', f"{fb:.3f}", '', fb_base_tooltip)
                    fb_ok = (no_violation('Front bias') if exp_fb is not None else True) and not fb_fail
                    add('Balance & Tyres', 'Front Bias', fb_value, ok=fb_ok, tooltip=fb_tooltip)
                ftw = info.get('front_tyre_width_mm')
                exp_fr = info.get('expected_front_tyre_range_mm')
                if ftw is not None:
                    suffix = ''
                    base_tooltip = 'data/tyres.ini:FRONT:WIDTH'
                    if isinstance(exp_fr, (list, tuple)) and len(exp_fr) == 2:
                        suffix = f" (exp {exp_fr[0]}-{exp_fr[1]} mm)"
                        base_tooltip = f"Front tyre width target {exp_fr[0]}-{exp_fr[1]} mm"
                    ftw_value, ftw_tooltip, ftw_fail = html_spec_value('front_tyre_width_mm', f"{ftw} mm", suffix, base_tooltip)
                    ftw_ok = (no_violation('Front tyre WIDTH') if exp_fr else True) and not ftw_fail
                    add('Balance & Tyres', 'Front Tyre', ftw_value, ok=ftw_ok, tooltip=ftw_tooltip)
                rtw = info.get('rear_tyre_width_mm')
                exp_r = info.get('expected_rear_tyre_max_mm')
                if rtw is not None:
                    suffix = ''
                    base_tooltip = 'data/tyres.ini:REAR:WIDTH'
                    if exp_r is not None:
                        suffix = f" (max {exp_r} mm)"
                        base_tooltip = f"Rear tyre width max {exp_r} mm"
                    rtw_value, rtw_tooltip, rtw_fail = html_spec_value('rear_tyre_width_mm', f"{rtw} mm", suffix, base_tooltip)
                    rtw_ok = (no_violation('Rear tyre WIDTH') if exp_r is not None else True) and not rtw_fail
                    add('Balance & Tyres', 'Rear Tyre', rtw_value, ok=rtw_ok, tooltip=rtw_tooltip)

                steer_lock_val = info.get('steer_lock')
                if steer_lock_val is not None:
                    lock_value, lock_tooltip, lock_fail = html_spec_value('steer_lock', f"{steer_lock_val}°", '', 'data/car.ini:CONTROLS:STEER_LOCK')
                    add('Steering', 'STEER_LOCK', lock_value, ok=not lock_fail, tooltip=lock_tooltip)
                steer_ratio_val = info.get('steer_ratio')
                if steer_ratio_val is not None:
                    ratio_value, ratio_tooltip, ratio_fail = html_spec_value('steer_ratio', f"{steer_ratio_val}", '', 'data/car.ini:CONTROLS:STEER_RATIO')
                    add('Steering', 'STEER_RATIO', ratio_value, ok=not ratio_fail, tooltip=ratio_tooltip)
                ang = info.get('measured_wheel_angle_deg')
                if ang is None:
                    src_data = info.get('cm_steer') or info.get('sim_steer')
                    if isinstance(src_data, dict):
                        if 'max_wheel_angle_deg' in src_data:
                            try:
                                ang = round(abs(float(src_data['max_wheel_angle_deg'])), 2)
                            except Exception:
                                ang = src_data['max_wheel_angle_deg']
                        elif 'left_max_deg' in src_data and 'right_max_deg' in src_data:
                            try:
                                ang = round(max(abs(float(src_data['left_max_deg'])), abs(float(src_data['right_max_deg']))), 2)
                            except Exception:
                                pass
                exp_sa = info.get('expected_max_steer_angle_deg')
                src_val = str(info.get('steer_source') or '').lower()
                if ang is not None and exp_sa is not None:
                    parts = [f"{ang}°"]
                    ref_angle = info.get('reference_steer_angle_deg')
                    delta = info.get('steer_reference_delta')
                    try:
                        if ref_angle is not None:
                            ref_angle_f = float(ref_angle)
                            parts.append(f"vs ref {ref_angle_f:.2f}°")
                            if delta is not None and abs(float(delta)) > 0.01:
                                parts.append(f"(Δ {float(delta):+0.2f}°)")
                    except Exception:
                        pass
                    parts.append(f"(max {exp_sa}°)")
                    if 'cm' in src_val or 'normalized' in src_val:
                        parts.append('CM')
                    elif 'derived' in src_val or 'ini' in src_val:
                        parts.append('INI')
                    warn_flag = 'derived' in src_val
                    ok_flag = no_violation('wheel angle')
                    if delta is not None:
                        try:
                            delta_f = float(delta)
                            warn_flag = warn_flag or abs(delta_f) > 0.5
                            ok_flag = ok_flag and abs(delta_f) <= 0.5
                        except Exception:
                            pass
                    add('Steering', 'Steering Angle', ' '.join(parts), ok=ok_flag, warn=warn_flag)

                kn5_sizes = info.get('kn5_sizes') or {}
                if kn5_sizes:
                    try:
                        largest_name, largest_val = max(kn5_sizes.items(), key=lambda kv: float(kv[1] or 0.0))
                        label_txt = f"{float(largest_val):.1f} MB ({largest_name})"
                    except Exception:
                        largest_val = None
                        label_txt = str(kn5_sizes)
                    limit = info.get('expected_max_kn5_mb')
                    warn_flag = False
                    if isinstance(largest_val, (int, float)) and isinstance(limit, (int, float)):
                        warn_flag = largest_val > float(limit) + 1e-6
                        label_txt += f" / max {limit} MB"
                    add('Files & Skins', 'Largest KN5', label_txt, warn=warn_flag, ok=(not warn_flag if warn_flag else None))

                skins_count = info.get('skins_count')
                if skins_count is not None:
                    add('Files & Skins', 'Skins', f"{skins_count} (expected 1)", ok=(skins_count == 1), warn=(skins_count != 1))
                max_skin = info.get('max_skin') or {}
                if isinstance(max_skin, dict) and 'size_mb' in max_skin:
                    try:
                        sz = float(max_skin.get('size_mb') or 0.0)
                        label = f"{sz:.1f} MB"
                    except Exception:
                        label = str(max_skin.get('size_mb'))
                    warn_flag = (not no_violation('Largest skin'))
                    add('Files & Skins', 'Largest Skin', label, warn=warn_flag, ok=(not warn_flag if warn_flag else None))
                if info.get('data_files_ok') is not None:
                    if info.get('data_files_ok'):
                        add('Files & Skins', 'Data Files', 'Match reference', ok=True)
                    else:
                        extra = len(info.get('data_files_extra') or [])
                        missing = len(info.get('data_files_missing') or [])
                        add('Files & Skins', 'Data Files', f"diff (+{extra}/-{missing})", ok=False)
                mismatches = info.get('hash_mismatches') or []
                if mismatches:
                    first = mismatches[0] if mismatches else {}
                    tooltip = ''
                    if isinstance(first, dict):
                        tooltip = str(first.get('path') or '')
                    add('Files & Skins', 'Data Hashes', f"{len(mismatches)} mismatched", ok=False, warn=False, tooltip=tooltip)
                root_extra = len(info.get('root_extra_dirs') or []) + len(info.get('root_extra_files') or [])
                root_missing = len(info.get('root_missing_dirs') or []) + len(info.get('root_missing_files') or [])
                root_suspicious = len(info.get('root_suspicious_dirs') or []) + len(info.get('root_suspicious_files') or [])
                if root_extra or root_missing or root_suspicious:
                    detail = []
                    if root_extra:
                        detail.append(f"extra={root_extra}")
                    if root_missing:
                        detail.append(f"missing={root_missing}")
                    if root_suspicious:
                        detail.append(f"suspicious={root_suspicious}")
                    add('Files & Skins', 'Root Inventory', ' | '.join(detail) or 'differences', ok=False, warn=True)
                data_mods = info.get('data_modifications') or []
                if data_mods:
                    high = sum(1 for m in data_mods if m.get('severity') == 'high')
                    medium = sum(1 for m in data_mods if m.get('severity') == 'medium')
                    low = sum(1 for m in data_mods if m.get('severity') == 'low')
                    detail = []
                    if high:
                        detail.append(f"high={high}")
                    if medium:
                        detail.append(f"medium={medium}")
                    if low:
                        detail.append(f"low={low}")
                    add('Files & Skins', 'Data Changes', ' | '.join(detail) or f"changes={len(data_mods)}", ok=False, warn=False)
                if info.get('fallback_used'):
                    add('Files & Skins', 'Fallback Ref', info.get('fallback_reference') or 'fallback', warn=True)

                textures_unchecked = info.get('textures_unchecked')
                if textures_unchecked:
                    add('Textures', 'Unchecked Textures', f"{len(textures_unchecked)} items", warn=True)

                ext_summary = info.get('extension_summary') or {}
                if ext_summary:
                    status = ext_summary.get('status') or 'unknown'
                    files = ext_summary.get('files') or []
                    extra = ext_summary.get('extra') or []
                    missing = ext_summary.get('missing') or []
                    mismatched = ext_summary.get('mismatched') or []
                    detail_bits = [status]
                    if files:
                        detail_bits.append(f"files={len(files)}")
                    if extra:
                        detail_bits.append(f"extra={len(extra)}")
                    if missing:
                        detail_bits.append(f"missing={len(missing)}")
                    if mismatched:
                        detail_bits.append(f"mismatch={len(mismatched)}")
                    detail = ' | '.join(detail_bits)
                    warn_flag = status in ('match', 'unexpected', 'missing')
                    ok_flag = False if (extra or missing or mismatched or status == 'unexpected') else (None if warn_flag else True)
                    add('Extension', 'CSP Configs', detail, ok=ok_flag, warn=True if warn_flag else False)

                power_peak = info.get('power_peak') or {}
                if isinstance(power_peak, dict) and power_peak.get('power') is not None:
                    add('Performance', 'Power Peak', f"{power_peak['power']} hp @ {power_peak.get('rpm', '?')} rpm")
                ui_pc = info.get('ui_power_curve') or {}
                if ui_pc.get('max') is not None:
                    add('Performance', 'UI Power Max', f"{ui_pc['max']} hp")
                ui_tc = info.get('ui_torque_curve') or {}
                if ui_tc.get('max') is not None:
                    add('Performance', 'UI Torque Max', f"{ui_tc['max']} Nm")
                torque_4k = info.get('torque_at_4000')
                torque_55 = info.get('torque_at_5500')
                hp_65 = info.get('hp_at_6500')
                drift_torque_warn = bool(info.get('drift_torque_warn'))
                targets = info.get('drift_torque_targets') or {}
                if torque_4k is not None:
                    target = targets.get('torque', [500.0, 450.0])[0] if isinstance(targets.get('torque'), list) else 500.0
                    add('Performance', 'Torque @4k', f"{torque_4k:.0f} Nm (target ≥{int(target)} Nm)",
                        ok=not drift_torque_warn, warn=drift_torque_warn)
                if torque_55 is not None:
                    target55 = targets.get('torque', [500.0, 450.0])[1] if isinstance(targets.get('torque'), list) and len(targets.get('torque')) > 1 else 450.0
                    add('Performance', 'Torque @5.5k', f"{torque_55:.0f} Nm (target ≥{int(target55)} Nm)",
                        ok=not drift_torque_warn, warn=drift_torque_warn)
                if hp_65 is not None:
                    target_hp = targets.get('hp_6500', 600.0)
                    add('Performance', 'Power @6.5k', f"{hp_65:.0f} hp (target ≥{int(target_hp)} hp)",
                        ok=not drift_torque_warn, warn=drift_torque_warn)

                if not sections:
                    return ''
                html_parts = ["<div class='summary-section'><div class='summary-title'>Summary</div>"]
                for section, cards in sections.items():
                    if not cards:
                        continue
                    html_parts.append(f"<div class='summary-group'><div class='summary-group-title'>{esc(section)}</div><div class='summary-grid'>")
                    for card in cards:
                        classes = ['summary-card']
                        if card['warn']:
                            classes.append('warn')
                        elif card['ok'] is True:
                            classes.append('ok')
                        elif card['ok'] is False:
                            classes.append('fail')
                        tooltip = esc(card['tooltip']) if card['tooltip'] else ''
                        icon = ''
                        if card['warn']:
                            icon = '⚠'
                        elif card['ok'] is True:
                            icon = '✔'
                        elif card['ok'] is False:
                            icon = '✘'
                        parts_html = [f"<div class='{' '.join(classes)}" + (f" title='{tooltip}'" if tooltip else '') + ">"]
                        if icon:
                            parts_html.append(f"<span class='status-icon'>{icon}</span>")
                        parts_html.append("<div class='content'>")
                        parts_html.append(f"<span class='label'>{esc(card['label'])}</span>")
                        parts_html.append(f"<span class='value'>{esc(card['value'])}</span>")
                        parts_html.append("</div></div>")
                        html_parts.append(''.join(parts_html))
                    html_parts.append("</div></div>")
                html_parts.append("</div>")
                return '\n'.join(html_parts)
            except Exception:
                return ''

        def build_anti_cheat_html():
            try:
                info = getattr(result, 'info', {}) or {}
                checks = info.get('anti_cheat') or []
                if not checks:
                    return ''
                skip_ids = {'AC007', 'AC008', 'AC009', 'AC015', 'AC016', 'AC017', 'AC018'}
                records: list[dict[str, object]] = []
                for item in checks:
                    ident = str(item.get('id') or '').strip()
                    if not ident or ident in skip_ids:
                        continue
                    status = str(item.get('status') or '').lower()
                    if status not in ('pass', 'warn', 'fail'):
                        status = 'pass' if status == 'ok' else 'warn'
                    label = item.get('label') or ident
                    detail = item.get('detail') or AC_HINTS.get(ident, '')
                    items = item.get('items') if isinstance(item.get('items'), list) else None
                    records.append({
                        'id': ident,
                        'status': status,
                        'label': label,
                        'detail': detail,
                        'items': items,
                    })
                if not records:
                    return ''
                status_order = {'fail': 0, 'warn': 1, 'pass': 2}
                records.sort(key=lambda r: (status_order.get(r.get('status'), 3), r.get('id')))
                from collections import Counter
                counts = Counter(r.get('status') for r in records)
                icon_map = {'fail': '🛑', 'warn': '⚠️', 'pass': '✅'}
                summary_bits = []
                for key in ('fail', 'warn', 'pass'):
                    if counts.get(key):
                        summary_bits.append(f"{icon_map.get(key, '•')} {key.title()} {counts[key]}")
                html_parts = ["<div class='chart-section anti-section'>", "<div class='chart-title'>Anti-Cheat Checks</div>"]
                if summary_bits:
                    html_parts.append(f"<div class='anti-summary'>{esc(' · '.join(summary_bits))}</div>")
                html_parts.append("<div class='anti-grid'>")
                for row in records:
                    status = row['status']
                    cls = status if status in ('fail', 'warn', 'pass') else ''
                    icon = icon_map.get(status, '•')
                    html_parts.append(f"<div class='anti-card {cls}'>")
                    html_parts.append("<div class='anti-card-header'>")
                    html_parts.append(f"<span class='anti-icon'>{icon}</span>")
                    html_parts.append(f"<span class='anti-code'>{esc(str(row['id']))}</span>")
                    html_parts.append(f"<span class='anti-label'>{esc(str(row['label']))}</span>")
                    html_parts.append("</div>")
                    detail = row.get('detail')
                    if detail:
                        html_parts.append(f"<div class='anti-detail'>{esc(str(detail))}</div>")
                    items = row.get('items')
                    if isinstance(items, list) and items:
                        html_parts.append("<ul class='anti-items'>")
                        for entry in items:
                            html_parts.append(f"<li>{esc(str(entry))}</li>")
                        html_parts.append("</ul>")
                    html_parts.append("</div>")
                html_parts.append("</div></div>")
                return '\n'.join(html_parts)
            except Exception:
                return ''

        graph_svg = build_graph_svg()
        graph_html = f"<div class='chart-section power-chart'>{graph_svg}</div>" if graph_svg else ''
        gear_svg = build_gearing_svg()
        gear_html = f"<div class='chart-section gear-chart'>{gear_svg}</div>" if gear_svg else ''
        chassis_html = build_chassis_html()
        tyre_html = build_tyre_html()
        summary_html = build_summary_html()
        anti_html = build_anti_cheat_html()
        html = f"""
<!doctype html>
<html>
<head>
  <meta charset='utf-8'/>
  <title>eF Drift Car Scrutineer Report</title>
  <style>
    body {{ background:{self.BRAND_LIGHT}; color:{self.BRAND_BLACK}; font-family: Segoe UI, Arial, sans-serif; }}
    .container {{ max-width: 960px; margin: 20px auto; padding: 16px; background: #fff; border-radius: 8px; }}
    .header {{ display:flex; align-items:center; border-bottom:1px solid #ddd; padding-bottom:8px; margin-bottom:10px; }}
    .title {{ color:{self.BRAND_NAVY}; font-weight:bold; font-size: 18px; margin:0; }}
    .subtitle {{ color:#555; font-size:12px; margin:2px 0 0 0; }}
    hr {{ border:none; border-top:1px solid #ddd; margin: 12px 0; }}
    .chart-section {{ margin:24px 0; }}
    .chart-title {{ color:{self.BRAND_NAVY}; font-weight:600; margin-bottom:8px; }}
    .power-chart svg, .gear-chart svg {{ width:100%; max-width:720px; }}
    .metric-row {{ margin-bottom:16px; }}
    .metric-label {{ font-weight:600; color:{self.BRAND_NAVY}; margin-bottom:4px; }}
    .metric-bars {{ display:flex; gap:12px; align-items:flex-end; flex-wrap:wrap; }}
    .metric-bar {{ position:relative; display:inline-block; height:18px; min-width:32px; border-radius:4px; background:{self.BRAND_ORANGE}; }}
    .metric-bar.reference {{ background:#4f7ec2; }}
    .metric-bar.negative {{ box-shadow: inset 0 0 0 2px #D93025; }}
    .metric-bar.empty {{ background:#dcdcdc; color:#555; display:flex; align-items:center; justify-content:center; padding:0 10px; height:18px; font-size:11px; }}
    .metric-bar span {{ position:absolute; top:-18px; left:0; font-size:11px; color:{self.BRAND_NAVY}; }}
    .tyre-row {{ margin-bottom:16px; }}
    .tyre-label {{ font-weight:600; color:{self.BRAND_NAVY}; margin-bottom:4px; }}
    .summary-section {{ margin:32px 0; }}
    .summary-title {{ color:{self.BRAND_NAVY}; font-weight:700; margin-bottom:12px; font-size:16px; }}
    .summary-group {{ margin-bottom:20px; }}
    .summary-group-title {{ color:{self.BRAND_NAVY}; font-weight:600; margin-bottom:10px; text-transform:uppercase; font-size:13px; }}
    .summary-grid {{ display:flex; flex-wrap:wrap; gap:12px; }}
    .summary-card {{ flex:1 1 220px; max-width:260px; min-width:200px; background:#ffffff; border:1px solid #d5dbe8; border-radius:8px; padding:10px 14px; display:flex; align-items:flex-start; gap:10px; }}
    .summary-card .status-icon {{ flex:0 0 auto; font-size:15px; line-height:1; }}
    .summary-card .content {{ flex:1; display:flex; flex-direction:column; gap:4px; }}
    .summary-card .label {{ color:#4a5568; font-weight:600; font-size:11px; letter-spacing:0.02em; text-transform:uppercase; }}
    .summary-card .value {{ color:{self.BRAND_BLACK}; font-size:13px; font-weight:600; word-break:break-word; }}
    .summary-card.ok {{ background:#F1F8E9; border-color:#c6e3b8; }}
    .summary-card.fail {{ background:#FDECEA; border-color:#f5c6cb; }}
    .summary-card.warn {{ background:#FFF7ED; border-color:#f5d1a3; }}
    .summary-card .status-icon {{ color:{self.BRAND_NAVY}; }}
    .summary-card.ok .status-icon {{ color:#188038; }}
    .summary-card.fail .status-icon {{ color:#D93025; }}
    .summary-card.warn .status-icon {{ color:{self.BRAND_ORANGE}; }}
    .anti-section {{ margin:32px 0; }}
    .anti-summary {{ color:#555; font-size:12px; margin-bottom:12px; }}
    .anti-grid {{ display:flex; flex-wrap:wrap; gap:14px; }}
    .anti-card {{ flex:1 1 calc(50% - 14px); min-width:260px; background:#ffffff; border:1px solid #d5dbe8; border-radius:8px; padding:14px 16px; display:flex; flex-direction:column; gap:8px; }}
    .anti-card.pass {{ background:#F1F8E9; border-color:#c6e3b8; }}
    .anti-card.warn {{ background:#FFF7ED; border-color:#f5d1a3; }}
    .anti-card.fail {{ background:#FDECEA; border-color:#f5c6cb; }}
    .anti-card-header {{ display:flex; align-items:flex-start; gap:8px; flex-wrap:wrap; }}
    .anti-icon {{ font-size:16px; color:{self.BRAND_NAVY}; line-height:1; }}
    .anti-card.fail .anti-icon {{ color:#D93025; }}
    .anti-card.warn .anti-icon {{ color:{self.BRAND_ORANGE}; }}
    .anti-card.pass .anti-icon {{ color:#188038; }}
    .anti-code {{ font-size:12px; font-weight:600; color:{self.BRAND_NAVY}; background:#e9eefb; padding:2px 6px; border-radius:4px; letter-spacing:0.04em; }}
    .anti-label {{ flex:1; font-weight:600; color:{self.BRAND_BLACK}; font-size:13px; min-width:140px; }}
    .anti-detail {{ font-size:12px; color:#374151; line-height:1.5; }}
    .anti-items {{ margin:4px 0 0 20px; padding:0; list-style:disc; color:#4a5568; font-size:12px; }}
    .anti-items li {{ margin-bottom:4px; }}
    .export-actions {{ margin:18px 0 12px; display:flex; justify-content:flex-end; }}
    .export-actions button {{ background:{self.BRAND_ORANGE}; color:white; border:none; border-radius:24px; padding:8px 18px; font-size:13px; font-weight:600; letter-spacing:0.02em; cursor:pointer; box-shadow:0 2px 6px rgba(0,0,0,0.12); transition:background 0.15s ease, transform 0.15s ease; }}
    .export-actions button:hover {{ background:#ff9a52; }}
    .export-actions button:active {{ transform:translateY(1px); }}
    @media print {{
      .export-actions {{ display:none; }}
      @page {{ margin: 12mm 8mm; }}
      body {{ margin:0; }}
      body::after {{ content:''; display:none; }}
    }}
  </style>
  </head>
<body>
  <div class='container'>
    <div class='header'>
      {icon_html}
      <div>
        <div class='title'>eF Drift Car Scrutineer Report</div>
        <div class='subtitle'>{esc(car_name)}</div>
      </div>
    </div>
    <div class='export-actions'>
      <button type='button' onclick='window.print()'>Save as PDF</button>
    </div>
    {preview_html}
    {summary_html}
    {anti_html}
    {graph_html}
    {gear_html}
    {chassis_html}
    {tyre_html}
    {body}
  </div>
</body>
</html>
"""
        return html

    # PDF export removed per request; HTML export is the single export path
    
    def export_diffs(self):
        try:
            if not hasattr(self, 'last_result'):
                messagebox.showinfo('Export Diffs', 'No report available. Run Inspect first.')
                return
            res = self.last_result
            if not res.matched_reference:
                messagebox.showinfo('Export Diffs', 'Diffs require a matched reference.')
                return
            from inspector.diffs import build_diffs_html
            car = Path(self.car_var.get()).resolve()
            html = build_diffs_html(car, Path(self.state.reference_root), res.matched_reference, res.physics_mismatches or [])
            dest = filedialog.asksaveasfilename(title='Export Diffs (HTML)', defaultextension='.html',
                                                filetypes=[('HTML', '*.html'), ('All files', '*.*')])
            if not dest:
                return
            Path(dest).write_text(html, encoding='utf-8')
            self.status.set(f'Exported diffs to {dest}')
        except Exception as e:
            messagebox.showerror('Export Diffs', f'Export failed: {e}')

    def update_pass_indicator(self, passed: bool | None):
        try:
            if passed is True:
                self.pass_label.configure(text='● Inspection: PASS', bg='#188038', fg='white')
            elif passed is False:
                self.pass_label.configure(text='● Inspection: FAIL', bg='#D93025', fg='white')
            else:
                self.pass_label.configure(text='Inspection: Ready', bg=self.BRAND_NAVY, fg='white')
        except Exception:
            pass

    def _is_in_temp_extract(self, path: Path) -> bool:
        temp_root = getattr(self, '_temp_car_extract', None)
        if not temp_root:
            return False
        try:
            Path(path).resolve().relative_to(Path(temp_root).resolve())
            return True
        except Exception:
            return False

    def _include_root_in_zip(self, source_dir: Path) -> bool:
        try:
            temp_root = getattr(self, '_temp_car_extract', None)
            if temp_root and Path(source_dir).resolve() == Path(temp_root).resolve():
                return False
        except Exception:
            return True
        return True

    def _is_widget_descendant(self, widget, parent) -> bool:
        try:
            while widget is not None:
                if widget == parent:
                    return True
                widget = widget.master
        except Exception:
            pass
        return False

    def _is_widget_in_summary(self, widget) -> bool:
        return self._is_widget_descendant(widget, getattr(self, 'summary_canvas', None)) or \
               self._is_widget_descendant(widget, getattr(self, 'summary_inner', None))

    def _is_widget_in_graph(self, widget) -> bool:
        return self._is_widget_descendant(widget, getattr(self, 'graph_canvas', None))

    def _zip_directory(self, source_dir: Path, dest_zip: Path, include_root: bool = True) -> None:
        import os
        source_dir = Path(source_dir)
        dest_zip = Path(dest_zip)
        with zipfile.ZipFile(dest_zip, 'w', zipfile.ZIP_DEFLATED) as z:
            for root, _dirs, files in os.walk(source_dir):
                for fn in files:
                    fp = Path(root) / fn
                    rel = fp.relative_to(source_dir)
                    if include_root:
                        arc = Path(source_dir.name) / rel
                    else:
                        arc = rel
                    z.write(fp, arc)

    def _extract_archive(self, archive_path: Path) -> Path | None:
        archive_path = Path(archive_path)
        suffix = archive_path.suffix.lower()
        if suffix not in ('.zip', '.rar'):
            messagebox.showerror('Import Archive', 'Only ZIP or RAR archives are supported.')
            return None
        if getattr(self, '_temp_car_extract', None):
            shutil.rmtree(self._temp_car_extract, ignore_errors=True)
            self._temp_car_extract = None
        temp_root = Path(tempfile.mkdtemp(prefix='car_inspector_'))
        try:
            if suffix == '.zip':
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    zf.extractall(temp_root)
            else:
                try:
                    import rarfile  # type: ignore
                except ImportError:
                    shutil.rmtree(temp_root, ignore_errors=True)
                    messagebox.showerror('Import Archive', 'RAR support requires the "rarfile" package and an unrar-compatible backend. Install it or extract manually.')
                    return None
                try:
                    with rarfile.RarFile(archive_path) as rf:
                        rf.extractall(temp_root)
                except Exception as e:
                    shutil.rmtree(temp_root, ignore_errors=True)
                    messagebox.showerror('Import Archive', f'Failed to unpack RAR archive:\n{e}')
                    return None
        except Exception as e:
            shutil.rmtree(temp_root, ignore_errors=True)
            messagebox.showerror('Import Archive', f'Failed to unpack archive:\n{e}')
            return None
        self._temp_car_extract = temp_root
        try:
            self._source_archive = archive_path.resolve()
        except Exception:
            self._source_archive = archive_path
        candidates = [p for p in temp_root.iterdir() if p.is_dir()]
        if len(candidates) == 1:
            return candidates[0]
        return temp_root

    def _offer_archive_export(self, source_dir: Path, title: str, prompt: str, default_suffix: str) -> Path | None:
        if not getattr(self, '_source_archive', None):
            return None
        if not self._is_in_temp_extract(source_dir):
            return None
        if not messagebox.askyesno(title, prompt):
            return None
        archive_path = Path(self._source_archive)
        initial_dir = str(archive_path.parent)
        default_name = f"{archive_path.stem}{default_suffix}.zip"
        dest = filedialog.asksaveasfilename(
            title=title,
            defaultextension='.zip',
            initialdir=initial_dir,
            initialfile=default_name,
            filetypes=[('ZIP', '*.zip'), ('All files', '*.*')]
        )
        if not dest:
            return None
        dest_path = Path(dest)
        try:
            self.status.set('Creating archive ...')
            include_root = self._include_root_in_zip(source_dir)
            self._zip_directory(Path(source_dir), dest_path, include_root=include_root)
            self.status.set(f'Saved archive to {dest_path}')
            messagebox.showinfo(title, f'Saved updated archive:\n{dest_path}')
            try:
                self._source_archive = dest_path.resolve()
            except Exception:
                self._source_archive = dest_path
            return dest_path
        except Exception as e:
            messagebox.showerror(title, f'Failed to create archive:\n{e}')
        return None

    def fix_and_export(self):
        if not self._ensure_authenticated():
            return
        if self._busy:
            return
        def run():
            try:
                if not hasattr(self, 'last_result'):
                    messagebox.showinfo('Fix & Export', 'Run Inspect first to identify issues.')
                    return
                car = Path(self.car_var.get()).resolve()
                if not car.exists():
                    messagebox.showerror('Fix & Export', 'Please select a valid submitted car folder first.')
                    return
                # Rebuild a RulebookConfig from current toggles
                def to_int(v, default=None):
                    try:
                        return int(float(v))
                    except Exception:
                        return default
                def to_float(v, default=None):
                    try:
                        return float(str(v).replace(',', '.'))
                    except Exception:
                        return default
                from inspector.validator import RulebookConfig
                # Fallback to expected values from last_result.info if toggles are off
                exp = getattr(self, 'last_result', None).info if hasattr(self, 'last_result') and getattr(self, 'last_result') else {}
                def fallback_num(val, exp_key):
                    return val if val is not None else (exp.get(exp_key) if isinstance(exp, dict) else None)
                min_mass = to_float(self.min_mass_var.get()) if self.enf_mass_var.get() else None
                min_mass = fallback_num(min_mass, 'expected_min_total_mass_kg')
                front_bias = to_float(self.cg_var.get()) if self.enf_cg_var.get() else None
                front_bias = fallback_num(front_bias, 'expected_front_bias')
                rear_max = to_int(self.rear_tyre_var.get()) if self.enf_rear_tyre_var.get() else None
                rear_max = fallback_num(rear_max, 'expected_rear_tyre_max_mm')
                if rear_max is not None:
                    try:
                        rear_max = int(rear_max)
                    except Exception:
                        pass
                front_range = (to_int(self.front_tyre_lo_var.get()), to_int(self.front_tyre_hi_var.get())) if self.enf_front_tyre_var.get() else None
                if front_range is None:
                    fr = exp.get('expected_front_tyre_range_mm') if isinstance(exp, dict) else None
                    if isinstance(fr, (list, tuple)) and len(fr) == 2:
                        front_range = (int(fr[0]), int(fr[1]))
                steer_max = to_float(self.steer_max_var.get()) if self.enf_steer_var.get() else None
                steer_max = fallback_num(steer_max, 'expected_max_steer_angle_deg')
                rb = RulebookConfig(
                    enforce_body_types=False,
                    min_year=to_int(self.min_year_var.get(), 1965) if self.enf_year_var.get() else 0,
                    enforce_rwd=self.enf_rwd_var.get(),
                    enforce_front_engine=False,
                    min_total_mass_kg=min_mass,
                    enforce_front_bias=front_bias,
                    enforce_rear_tyre_max_mm=rear_max,
                    enforce_front_tyre_range_mm=front_range,
                    max_kn5_mb=None,
                    max_skin_mb=None,
                    max_triangles=None,
                    max_objects=None,
                    max_steer_angle_deg=steer_max,
                    require_cm_steer_file=False,
                    require_kn5_stats_file=False,
                    fallback_reference_key='vdc_bmw_e92_public' if self.e92_fallback_var.get() else None,
                )
                # Preview physics changes
                from inspector.fixer import plan_physics_changes, fix_issues, SERIES_PREFIX
                planned = plan_physics_changes(car, rb)
                # Build and show scrollable modal on the main thread; wait for user decision
                decision = {'ok': False, 'force_ref': False}
                gate = threading.Event()
                def show_modal():
                    try:
                        tl = tk.Toplevel(self)
                        tl.title('Fix Physics & Export — Planned Changes')
                        tl.configure(bg=self.BRAND_LIGHT)
                        tl.transient(self)
                        tl.grab_set()
                        self._center_modal(tl, 820, 560)
                        try:
                            tl.minsize(700, 420)
                        except Exception:
                            pass
                        # Header
                        lbl = tk.Label(tl, text='The following PHYSICS changes will be applied to a copied car:', bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK, font=self.base_font, anchor='w')
                        lbl.pack(fill='x', padx=10, pady=(10,4))
                        # Scrollable text
                        frm = tk.Frame(tl, bg=self.BRAND_LIGHT)
                        frm.pack(fill='both', expand=True, padx=10, pady=4)
                        txt = tk.Text(frm, wrap='char', bg='white', fg=self.BRAND_BLACK,
                                      font=('Consolas', 10))
                        vsb = ttk.Scrollbar(frm, orient='vertical', command=txt.yview)
                        txt.configure(yscrollcommand=vsb.set)
                        txt.pack(side='left', fill='both', expand=True)
                        vsb.pack(side='right', fill='y')
                        # Compose preview text: planned fixes and other issues
                        lines = []
                        lines.append('Planned physics changes:')
                        if planned:
                            for x in planned:
                                lines.append(f'- {x}')
                        else:
                            lines.append('- None (will still create a copy for export)')
                        lines.append('')
                        lines.append(f'Series naming updates (auto-applied):')
                        lines.append(f'- Folder/UI/car.ini/KN5 will be prefixed with {SERIES_PREFIX}')
                        # Also list other violations/mismatches for context
                        try:
                            lines.append('')
                            lines.append('Other issues detected (not auto-fixed here):')
                            # Rule violations
                            vlist = getattr(self, 'last_result', None).rule_violations if hasattr(self, 'last_result') else []
                            if vlist:
                                for v in vlist[:200]:
                                    lines.append(f'- {v}')
                                if len(vlist) > 200:
                                    lines.append(f'- ... and {len(vlist)-200} more')
                            else:
                                lines.append('- None')
                            # Physics mismatches summary
                            res = getattr(self, 'last_result', None)
                            mlist = res.physics_mismatches if (res and res.physics_mismatches) else []
                            if mlist:
                                lines.append('')
                                lines.append('Physics mismatches:')
                                for m in mlist[:200]:
                                    lines.append(f'- {m}')
                                if len(mlist) > 200:
                                    lines.append(f'- ... and {len(mlist)-200} more')
                        except Exception:
                            pass
                        txt.insert('1.0', '\n'.join(lines))
                        # Options row (force reference)
                        opt_fr = tk.Frame(tl, bg=self.BRAND_LIGHT)
                        opt_fr.pack(fill='x', padx=10, pady=(4,0))
                        force_ref_var = tk.BooleanVar(value=bool(getattr(self.last_result, 'matched_reference', None)))
                        cbx = tk.Checkbutton(opt_fr, text='Force exact physics match: replace data/* from matched reference', variable=force_ref_var, bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK)
                        if not getattr(self.last_result, 'matched_reference', None):
                            cbx.configure(state='disabled')
                        cbx.pack(anchor='w')
                        # Buttons
                        btns = tk.Frame(tl, bg=self.BRAND_LIGHT)
                        btns.pack(fill='x', padx=10, pady=(6,10))
                        def _ok():
                            decision['ok'] = True
                            decision['force_ref'] = bool(force_ref_var.get())
                            try:
                                tl.grab_release()
                            except Exception:
                                pass
                            tl.destroy()
                            gate.set()
                        def _cancel():
                            decision['ok'] = False
                            try:
                                tl.grab_release()
                            except Exception:
                                pass
                            tl.destroy()
                            gate.set()
                        okb = ttk.Button(btns, text='Proceed', command=_ok, style='Primary.TButton')
                        cb = ttk.Button(btns, text='Cancel', command=_cancel, style='Neutral.TButton')
                        # Center buttons
                        okb.pack(side='right', padx=(0,6))
                        cb.pack(side='right')
                        # Key bindings
                        tl.bind('<Return>', lambda e: _ok())
                        tl.bind('<Escape>', lambda e: _cancel())
                    except Exception:
                        # Fallback: accept by default if modal fails
                        decision['ok'] = True
                        gate.set()
                self.after(0, show_modal)
                gate.wait()
                if not decision['ok']:
                    return
                # Start background job for fix + re-inspect + zip + UI update
                def job(force_ref: bool):
                    try:
                        self._set_busy(True)
                        self.status.set('Applying automated physics fixes ...')
                        # Always rebuild reference data before applying fixes
                        ref_idx, fps = self._refresh_reference_data(need_fingerprints=True)
                        if fps is None:
                            fps = {}
                        # Fix
                        fixed_dir, changes = fix_issues(car, self.last_result, rb, ref_idx, force_reference=force_ref)
                        # Re-inspect
                        from inspector.validator import validate_submitted_car
                        fixed_res = validate_submitted_car(fixed_dir, fps, ref_idx, rb)
                        # Ask for export path on main thread
                        dest_holder = {'p': None}
                        ev = threading.Event()
                        def ask_path():
                            if self._source_archive:
                                initial_dir = str(Path(self._source_archive).parent)
                                initial_name = f"{Path(self._source_archive).stem}_fixed.zip"
                            else:
                                initial_dir = str(Path.cwd())
                                initial_name = f"{fixed_dir.name}.zip"
                            d = filedialog.asksaveasfilename(title='Export Fixed Car (ZIP)', defaultextension='.zip',
                                                             filetypes=[('ZIP', '*.zip'), ('All files', '*.*')],
                                                             initialdir=initial_dir, initialfile=initial_name)
                            dest_holder['p'] = d
                            ev.set()
                        self.after(0, ask_path)
                        ev.wait()
                        dest = dest_holder['p']
                        if not dest:
                            self._set_busy(False)
                            return
                        # Zip in background
                        self.status.set('Zipping fixed car ...')
                        include_root = self._include_root_in_zip(fixed_dir)
                        self._zip_directory(fixed_dir, Path(dest), include_root=include_root)
                        # Push UI updates to main thread
                        def apply():
                            try:
                                self.status.set(f'Fixed car exported to {dest}')
                                # Show summary
                                report_intro = ['Automated Fix Summary:']
                                if changes:
                                    report_intro += [f'- {c}' for c in changes[:200]]
                                    if len(changes) > 200:
                                        report_intro.append(f'- ... and {len(changes)-200} more')
                                else:
                                    report_intro.append('- No direct file changes applied')
                                report_intro.append('')
                                from inspector.report import format_report_text
                                fixed_text = format_report_text(fixed_res)
                                content = '\n'.join(report_intro) + fixed_text
                                self.render_report_text(content)
                                self.last_result = fixed_res
                                self.populate_summary(fixed_res)
                                self.update_report_header(fixed_dir, fixed_res)
                                self.draw_graphs(fixed_dir, result=fixed_res)
                                # Success modal
                                try:
                                    tl = tk.Toplevel(self)
                                    tl.title('Export Complete')
                                    tl.configure(bg=self.BRAND_LIGHT)
                                    tl.transient(self)
                                    tl.grab_set()
                                    self._center_modal(tl, 520, 160)
                                    msg = tk.Label(tl, text=f'Fixed car exported to:\n{dest}', bg=self.BRAND_LIGHT, fg=self.BRAND_BLACK, font=self.base_font, anchor='w', justify='left')
                                    msg.pack(fill='both', expand=True, padx=10, pady=(10,6))
                                    btns = tk.Frame(tl, bg=self.BRAND_LIGHT)
                                    btns.pack(fill='x', padx=10, pady=(0,10))
                                    import platform, subprocess, os
                                    def _open_path(p):
                                        try:
                                            sys = platform.system()
                                            if sys == 'Windows':
                                                os.startfile(str(p))  # type: ignore
                                            elif sys == 'Darwin':
                                                subprocess.Popen(['open', str(p)])
                                            else:
                                                subprocess.Popen(['xdg-open', str(p)])
                                        except Exception:
                                            pass
                                    def _open_fixed():
                                        _open_path(str(fixed_dir))
                                    def _open_zip():
                                        _open_path(str(dest))
                                    def _close():
                                        try:
                                            tl.grab_release()
                                        except Exception:
                                            pass
                                        tl.destroy()
                                    b_fixed = ttk.Button(btns, text='Open Fixed Folder', command=_open_fixed, style='Secondary.TButton')
                                    b_zip = ttk.Button(btns, text='Open ZIP', command=_open_zip, style='Primary.TButton')
                                    b_close = ttk.Button(btns, text='Close', command=_close, style='Neutral.TButton')
                                    b_close.pack(side='right')
                                    b_zip.pack(side='right', padx=(0,6))
                                    b_fixed.pack(side='right', padx=(0,6))
                                    tl.bind('<Escape>', lambda e: _close())
                                except Exception:
                                    pass
                            finally:
                                self._set_busy(False)
                        self.after(0, apply)
                    except Exception as e:
                        tb = traceback.format_exc()
                        def show_err():
                            self.status.set('Fix & Export failed')
                            messagebox.showerror('Fix & Export', f'Failed to fix/export:\n{e}\n\n{tb}')
                            self._set_busy(False)
                        self.after(0, show_err)
                threading.Thread(target=lambda: job(decision['force_ref']), daemon=True).start()
            except Exception as e:
                tb = traceback.format_exc()
                def show_err():
                    self.status.set('Fix & Export failed')
                    messagebox.showerror('Fix & Export', f'Failed to fix/export:\n{e}\n\n{tb}')
                    self._set_busy(False)
                self.after(0, show_err)
        threading.Thread(target=run, daemon=True).start()

    def open_in_cm(self):
        if not self._ensure_authenticated():
            return
        if self._busy:
            return
        def run():
            try:
                import os, platform
                car = Path(self.car_var.get()).resolve()
                # Choose a KN5 to open (prefer non-collider, largest file)
                kn5s = list(car.glob('*.kn5'))
                if not kn5s:
                    messagebox.showwarning('Open KN5', 'No KN5 files found in the selected car folder.')
                    return
                def kn5_score(p: Path):
                    name = p.name.lower()
                    pref = 0
                    if 'collider' in name:
                        pref -= 10
                    try:
                        size = p.stat().st_size
                    except Exception:
                        size = 0
                    return (pref, size)
                kn5 = sorted(kn5s, key=kn5_score, reverse=True)[0]
                # Open with system default associated app
                sys = platform.system()
                if sys == 'Windows':
                    os.startfile(str(kn5))  # type: ignore
                elif sys == 'Darwin':
                    import subprocess
                    subprocess.Popen(['open', str(kn5)])
                else:
                    import subprocess
                    subprocess.Popen(['xdg-open', str(kn5)])
                self.status.set(f'Opened KN5: {kn5.name}')
            except Exception as e:
                messagebox.showinfo('Open KN5', f'Failed to open KN5: {e}')
        threading.Thread(target=run, daemon=True).start()

    def clear_preview(self):
        # Clear report text and cached data
        self.render_report_text('')
        self.report_raw_text = ''
        try:
            if hasattr(self, 'report_filter_var'):
                self.report_filter_var.set('all')
            if hasattr(self, 'report_search_var'):
                self.report_search_var.set('')
        except Exception:
            pass
        # Reset selected car
        try:
            self.car_var.set('')
        except Exception:
            pass
        self._pending_auto_inspect = None
        if self._auto_inspect_job is not None:
            try:
                self.after_cancel(self._auto_inspect_job)
            except Exception:
                pass
            self._auto_inspect_job = None
        self._graph_state = None
        # Reset status indicators and state
        self.status.set('Cleared')
        self.last_report_path = None
        self.last_report_json_path = None
        self.last_result = None
        self._source_archive = None
        for canvas_attr in ('power_canvas', 'gear_canvas', 'chassis_canvas', 'tyre_canvas'):
            try:
                canvas = getattr(self, canvas_attr, None)
                if canvas:
                    canvas.delete('all')
            except Exception:
                pass
        try:
            if hasattr(self, 'graph_canvas'):
                self.graph_canvas.yview_moveto(0)
        except Exception:
            pass
        # Clear Car Info preview and text
        try:
            if hasattr(self, 'preview_label'):
                self.preview_label.configure(image='', text='')
                self.preview_label.image = None
            if hasattr(self, 'info_txt'):
                self.info_txt.delete('1.0', tk.END)
            if hasattr(self, 'ac_text'):
                self.ac_text.delete('1.0', tk.END)
                self.ac_text.insert(tk.END, 'No anti-cheat data loaded.')
            if hasattr(self, 'ac_filter_var'):
                self.ac_filter_var.set('all')
            if hasattr(self, 'ac_search_var'):
                self.ac_search_var.set('')
        except Exception:
            pass
        # Reset report header and banner
        try:
            self.report_title_label.configure(text='No car selected')
            self.report_meta_label.configure(text='')
            self.report_status_label.configure(text='', bg=self.BRAND_LIGHT)
            self.update_pass_indicator(None)
        except Exception:
            pass
        # Clear summary chips
        try:
            for w in list(self.summary_inner.children.values()):
                w.destroy()
        except Exception:
            pass

    def export_report(self):
        try:
            content = self.txt.get('1.0', tk.END)
            if not content.strip():
                messagebox.showinfo('Export', 'Nothing to export. Run Inspect first.')
                return
            initialfile = None
            if hasattr(self, 'last_report_path') and self.last_report_path:
                initialfile = self.last_report_path.name
            dest = filedialog.asksaveasfilename(title='Export Report As', defaultextension='.txt', initialfile=initialfile,
                                                filetypes=[('Text report', '*.txt'), ('All files', '*.*')])
            if not dest:
                return
            Path(dest).write_text(content, encoding='utf-8')
            # Optionally export JSON if available
            if hasattr(self, 'last_report_json_path') and self.last_report_json_path:
                if messagebox.askyesno('Export JSON', 'Also export JSON report?'):
                    try:
                        shutil.copyfile(self.last_report_json_path, Path(dest).with_suffix('.json'))
                    except Exception as e:
                        messagebox.showwarning('Export JSON', f'Failed to export JSON: {e}')
            self.status.set(f'Exported to {dest}')
        except Exception as e:
            messagebox.showerror('Export', f'Export failed: {e}')

    def update_physics(self):
        if not self._ensure_authenticated():
            return
        if self._busy:
            return
        try:
            car = Path(self.car_var.get()).resolve()
            if not car.exists():
                messagebox.showerror('Update Physics', 'Please select a valid submitted car folder first.')
                return
            src = filedialog.askdirectory(title='Select physics source (car folder or data folder)')
            if not src:
                return
            src_path = Path(src)
            src_data = src_path / 'data' if (src_path / 'data').exists() else src_path
            if src_data.name.lower() != 'data' or not src_data.exists():
                messagebox.showerror('Update Physics', 'Selected folder must be a car folder containing a data subfolder, or the data folder itself.')
                return
            target_data = car / 'data'
            if not messagebox.askyesno('Confirm', f'Overwrite physics in:\n{target_data}\n\nfrom:\n{src_data}\n\nA backup will be created.'):
                return
            self._set_busy(True)
            self.status.set('Backing up existing physics ...')
            backup_dir = car / 'analysis' / f'backup_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
            try:
                if target_data.exists():
                    shutil.copytree(target_data, backup_dir)
            except Exception as e:
                messagebox.showwarning('Backup', f'Backup failed: {e}')
            self.status.set('Replacing physics ...')
            try:
                if target_data.exists():
                    shutil.rmtree(target_data)
                shutil.copytree(src_data, target_data)
            except Exception as e:
                messagebox.showerror('Update Physics', f'Failed to copy physics: {e}')
                return
            acd = car / 'data.acd'
            note = ''
            if acd.exists():
                note = '\nNote: data.acd exists; AC will prefer data/ over data.acd when present.'
            self.status.set('Physics updated successfully')
            messagebox.showinfo('Update Physics', f'Physics replaced successfully.{note}')
            saved_archive = self._offer_archive_export(car, 'Save Updated Archive',
                                                       'This car was loaded from an archive. Save the updated files as a new ZIP?',
                                                       '_updated')
            if saved_archive:
                refreshed = self._extract_archive(saved_archive)
                if refreshed and refreshed.exists():
                    car = refreshed
                    self.car_var.set(str(car))
                    self.last_result = None
                    try:
                        self.populate_car_info(car)
                        self.update_report_header(car, None)
                    except Exception:
                        pass
            # Offer re-inspection
            if messagebox.askyesno('Re-inspect', 'Do you want to re-run the inspection now?'):
                self.inspect()
        finally:
            self._set_busy(False)


if __name__ == '__main__':
    app = InspectorUI()
    app.geometry('900x700')
    try:
        # Always check based on configured update channel from Settings
        ch = None
        try:
            ch = app.update_channel_var.get()
        except Exception:
            ch = None
        updater.maybe_check_for_updates_in_background(app, channel=ch)
    except Exception:
        pass
    app.mainloop()
