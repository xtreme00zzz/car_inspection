from __future__ import annotations

import json
import os
import sys
import time
import threading
import urllib.error
import urllib.request
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

try:
    from tkinter import messagebox
except Exception:
    messagebox = None

try:
    from app_version import APP_VERSION, UPDATE_CHANNEL, GITHUB_OWNER, GITHUB_REPO
except Exception:
    APP_VERSION = "0.0.0"
    UPDATE_CHANNEL = "stable"
    GITHUB_OWNER = ""
    GITHUB_REPO = ""

# Resolve base dir similar to ui_app without importing it
APP_BASE_DIR = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


@dataclass
class ReleaseAsset:
    name: str
    url: str  # browser_download_url
    size: int


@dataclass
class ReleaseInfo:
    tag: str
    prerelease: bool
    draft: bool
    assets: List[ReleaseAsset]


def _data_root() -> Path:
    override = os.getenv('EF_SCRUTINEER_DATA_DIR')
    if override:
        return Path(override).expanduser()
    if sys.platform.startswith('win'):
        local_appdata = os.getenv('LOCALAPPDATA')
        if local_appdata:
            return Path(local_appdata) / 'eFDriftScrutineer'
        return Path.home() / 'AppData' / 'Local' / 'eFDriftScrutineer'
    return Path.home() / '.ef_drift_scrutineer'


def _http_get_json(url: str) -> Optional[object]:
    req = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'ef-scrutineer-updater'
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            return json.loads(data.decode('utf-8', errors='replace'))
    except Exception:
        return None


def _list_releases(owner: str, repo: str) -> List[ReleaseInfo]:
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"
    payload = _http_get_json(url)
    releases: List[ReleaseInfo] = []
    if isinstance(payload, list):
        for r in payload:
            tag = str(r.get('tag_name') or '')
            prerelease = bool(r.get('prerelease'))
            draft = bool(r.get('draft'))
            assets_json = r.get('assets') or []
            assets: List[ReleaseAsset] = []
            for a in assets_json:
                name = str(a.get('name') or '')
                url = str(a.get('browser_download_url') or '')
                size = int(a.get('size') or 0)
                assets.append(ReleaseAsset(name, url, size))
            releases.append(ReleaseInfo(tag, prerelease, draft, assets))
    return releases


def _parse_version_tag(tag: str) -> Optional[tuple]:
    t = tag.strip()
    if not t:
        return None
    digits: List[int] = []
    num = ''
    for ch in t:
        if ch.isdigit():
            num += ch
        else:
            if num:
                try:
                    digits.append(int(num))
                except ValueError:
                    return None
                num = ''
    if num:
        try:
            digits.append(int(num))
        except ValueError:
            return None
    if len(digits) >= 1:
        while len(digits) < 3:
            digits.append(0)
        return tuple(digits[:3])
    return None


def _is_newer(remote: str, current: str) -> bool:
    rc = _parse_version_tag(remote) or (0, 0, 0)
    cc = _parse_version_tag(current) or (0, 0, 0)
    return rc > cc


def _select_release_for_channel(releases: List[ReleaseInfo], channel: str) -> Optional[ReleaseInfo]:
    channel = (channel or '').lower()
    if channel == 'beta':
        cand = [r for r in releases if not r.draft and (r.prerelease or 'beta' in r.tag.lower())]
    elif channel == 'alpha':
        cand = [r for r in releases if not r.draft and ('alpha' in r.tag.lower())]
    else:  # stable
        cand = [r for r in releases if not r.draft and not r.prerelease]
    if not cand:
        return None
    cand.sort(key=lambda r: _parse_version_tag(r.tag) or (0, 0, 0), reverse=True)
    return cand[0]


def _pick_asset_for_channel(assets: List[ReleaseAsset], channel: str) -> Optional[ReleaseAsset]:
    names = []
    if channel == 'beta':
        names.extend([
            'eF Drift Car Scrutineer Beta.exe',
            'ef-drift-scrutineer-beta.exe',
        ])
    elif channel == 'alpha':
        names.extend([
            'eF Drift Car Scrutineer Alpha.exe',
            'ef-drift-scrutineer-alpha.exe',
        ])
    else:
        names.extend([
            'eF Drift Car Scrutineer.exe',
            'ef-drift-scrutineer.exe',
        ])
    for n in names:
        for a in assets:
            if a.name == n:
                return a
    for a in assets:
        if a.name.lower().endswith('.exe'):
            return a
    return None


def _download(url: str, dest: Path) -> bool:
    tmp = dest.with_suffix('.part')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'ef-scrutineer-updater'})
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, 'wb') as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
        tmp.replace(dest)
        return True
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False


def _find_updater_stub() -> Optional[Path]:
    exe_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else APP_BASE_DIR
    candidates = [
        exe_dir / 'eF Drift Car Scrutineer Updater.exe',
        exe_dir / 'updater_stub.exe',
        APP_BASE_DIR / 'eF Drift Car Scrutineer Updater.exe',
        APP_BASE_DIR / 'updater_stub.exe',
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _launch_updater_stub(target_exe: Path, package: Path, relaunch: bool = True) -> bool:
    stub = _find_updater_stub()
    if not stub:
        return False
    args = [
        str(stub),
        '--target', str(target_exe),
        '--package', str(package),
        '--wait-pid', str(os.getpid()),
    ]
    if relaunch:
        args.append('--launch')
    try:
        # Use ShellExecute to avoid a console window; fallback to Popen
        if sys.platform.startswith('win') and hasattr(os, 'startfile'):
            # startfile can't pass args; use Popen
            subprocess.Popen(args, close_fds=True)
        else:
            subprocess.Popen(args, close_fds=True)
        return True
    except Exception:
        return False


def _install_downloaded(downloaded: Path) -> None:
    try:
        if sys.platform.startswith('win'):
            os.startfile(str(downloaded))  # type: ignore[attr-defined]
        else:
            subprocess.Popen([str(downloaded)])
    except Exception:
        pass


def check_for_update_synchronously(parent=None, manual: bool = False, channel: Optional[str] = None) -> None:
    ch = (channel or UPDATE_CHANNEL or 'stable').lower()
    if not (GITHUB_OWNER and GITHUB_REPO):
        if manual and messagebox:
            messagebox.showinfo('Update', 'Updates are not configured for this build.')
        return

    releases = _list_releases(GITHUB_OWNER, GITHUB_REPO)
    if not releases:
        if manual and messagebox:
            messagebox.showinfo('Update', 'No releases found or network unavailable.')
        return
    latest = _select_release_for_channel(releases, ch)
    if not latest:
        if manual and messagebox:
            messagebox.showinfo('Update', f'No {ch} release found.')
        return

    latest_ver_text = latest.tag
    if not _is_newer(latest_ver_text, APP_VERSION):
        if manual and messagebox:
            messagebox.showinfo('Update', f'You are up to date. Version {APP_VERSION}.')
        return

    if messagebox is None:
        return
    if not messagebox.askyesno('Update Available', f'New {ch} version available (tag {latest.tag}).\n\nCurrent: {APP_VERSION}\nDownload and install now?'):
        return

    asset = _pick_asset_for_channel(latest.assets, ch)
    if not asset:
        messagebox.showinfo('Update', 'No suitable installer found in the latest release.')
        return

    updates_dir = _data_root() / 'updates'
    updates_dir.mkdir(parents=True, exist_ok=True)
    dest = updates_dir / asset.name
    ok = _download(asset.url, dest)
    if not ok:
        messagebox.showerror('Update', 'Failed to download update. Please try again later.')
        return

    # If running a frozen executable, try to use the updater stub for in-place replace
    if getattr(sys, 'frozen', False):
        target_exe = Path(sys.executable)
        launched = _launch_updater_stub(target_exe, dest, relaunch=True)
        if launched:
            messagebox.showinfo('Update', 'Installer will replace the app and relaunch. The app will now exit.')
            try:
                # Give stub time to start
                time.sleep(0.2)
            finally:
                os._exit(0)
        else:
            # Fallback: launch downloaded installer
            if messagebox.askyesno('Install Update', 'Updater stub not found. Launch the downloaded installer now?'):
                _install_downloaded(dest)
    else:
        # Dev mode: just offer to open the downloaded installer
        if messagebox.askyesno('Update Downloaded', 'Update downloaded. Launch the installer now?'):
            _install_downloaded(dest)


def maybe_check_for_updates_in_background(parent=None, channel: Optional[str] = None) -> None:
    t = threading.Thread(target=check_for_update_synchronously, kwargs={'parent': parent, 'manual': False, 'channel': channel}, daemon=True)
    t.start()
