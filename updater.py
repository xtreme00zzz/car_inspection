from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

try:
    from tkinter import messagebox
except Exception:  # when importing in non-GUI contexts
    messagebox = None

try:
    from app_version import APP_VERSION, UPDATE_CHANNEL, GITHUB_OWNER, GITHUB_REPO
except Exception:
    APP_VERSION = "BETA-0.0.0"
    UPDATE_CHANNEL = "beta"
    GITHUB_OWNER = ""
    GITHUB_REPO = ""


@dataclass
class ReleaseAsset:
    name: str
    url: str  # browser_download_url
    size: int


@dataclass
class ReleaseInfo:
    tag: str
    prerelease: bool
    assets: List[ReleaseAsset]


def _data_root() -> Path:
    # Match ui_app default path semantics without importing it (avoid heavy import)
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
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def _list_releases(owner: str, repo: str) -> List[ReleaseInfo]:
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"
    payload = _http_get_json(url)
    releases: List[ReleaseInfo] = []
    if isinstance(payload, list):
        for r in payload:
            tag = str(r.get('tag_name') or '')
            prerelease = bool(r.get('prerelease'))
            assets_json = r.get('assets') or []
            assets: List[ReleaseAsset] = []
            for a in assets_json:
                name = str(a.get('name') or '')
                url = str(a.get('browser_download_url') or '')
                size = int(a.get('size') or 0)
                assets.append(ReleaseAsset(name, url, size))
            releases.append(ReleaseInfo(tag, prerelease, assets))
    return releases


def _parse_version_tag(tag: str) -> Optional[tuple]:
    # Accept tags like: BETA-0.1.0 or v0.1.0-beta
    t = tag.strip()
    if not t:
        return None
    # Normalize to numeric triple
    digits: List[int] = []
    num = ''
    for ch in t:
        if ch.isdigit():
            num += ch
        else:
            if num:
                digits.append(int(num))
                num = ''
    if num:
        digits.append(int(num))
    if len(digits) >= 1:
        while len(digits) < 3:
            digits.append(0)
        return tuple(digits[:3])
    return None


def _parse_version_text(text: str) -> Optional[tuple]:
    return _parse_version_tag(text)


def _is_newer(remote: str, current: str) -> bool:
    rc = _parse_version_text(remote) or (0, 0, 0)
    cc = _parse_version_text(current) or (0, 0, 0)
    return rc > cc


def _select_beta_release(releases: List[ReleaseInfo]) -> Optional[ReleaseInfo]:
    # Prefer prerelease entries with a tag that includes 'BETA' or 'beta'
    beta = [r for r in releases if r.prerelease or ('beta' in r.tag.lower() or 'beta' in r.tag.lower())]
    if not beta:
        return None
    # Sort by parsed version desc
    beta.sort(key=lambda r: _parse_version_tag(r.tag) or (0, 0, 0), reverse=True)
    return beta[0]


def _pick_asset_for_beta(assets: List[ReleaseAsset]) -> Optional[ReleaseAsset]:
    # Prefer the onefile executable for beta
    preferred_names = [
        'eF Drift Car Scrutineer Beta.exe',
        'ef-drift-scrutineer-beta.exe',
    ]
    for name in preferred_names:
        for a in assets:
            if a.name == name:
                return a
    # Fallback: any .exe
    for a in assets:
        if a.name.lower().endswith('.exe'):
            return a
    return None


def _download(url: str, dest: Path) -> bool:
    tmp = dest.with_suffix('.part')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'ef-scrutineer-updater'})
        with urllib.request.urlopen(req, timeout=30) as resp, open(tmp, 'wb') as f:
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


def _install_downloaded(downloaded: Path) -> None:
    # Best-effort: run the downloaded executable and exit current process.
    # Full self-replacement is complex on Windows; for beta we launch the new exe.
    try:
        if sys.platform.startswith('win'):
            os.startfile(str(downloaded))  # type: ignore[attr-defined]
        else:
            import subprocess
            subprocess.Popen([str(downloaded)])
    except Exception:
        pass


def check_for_update_synchronously(parent=None) -> None:
    if UPDATE_CHANNEL.lower() != 'beta':
        return
    if not (GITHUB_OWNER and GITHUB_REPO):
        return

    releases = _list_releases(GITHUB_OWNER, GITHUB_REPO)
    if not releases:
        return
    latest = _select_beta_release(releases)
    if not latest:
        return
    # Extract numeric-like text from tag
    latest_ver_text = latest.tag
    if not _is_newer(latest_ver_text, APP_VERSION):
        return

    # Ask user
    if messagebox is None:
        return
    if not messagebox.askyesno('Update Available', f'A new beta version is available (tag {latest.tag}).\n\nCurrent: {APP_VERSION}\nUpdate now?'):
        return

    asset = _pick_asset_for_beta(latest.assets)
    if not asset:
        messagebox.showinfo('Update', 'No suitable asset found in the latest beta release.')
        return

    updates_dir = _data_root() / 'updates'
    updates_dir.mkdir(parents=True, exist_ok=True)
    dest = updates_dir / asset.name
    ok = _download(asset.url, dest)
    if not ok:
        messagebox.showerror('Update', 'Failed to download update. Please try again later.')
        return

    if messagebox.askyesno('Install Update', 'Update downloaded. Launch the new version now?'):
        _install_downloaded(dest)
        # Encourage current app to exit; caller can decide to do so.


def maybe_check_for_updates_in_background(parent=None) -> None:
    # Non-blocking check on a worker thread
    t = threading.Thread(target=check_for_update_synchronously, args=(parent,), daemon=True)
    t.start()

