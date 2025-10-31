from __future__ import annotations

import json
import os
import sys
import time
import threading
import urllib.error
import urllib.request
import urllib.parse
import subprocess
from dataclasses import dataclass
import re
import zipfile
from pathlib import Path
from typing import Optional, List, Dict, Any

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


def _github_headers() -> dict:
    headers = {
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'ef-scrutineer-updater',
    }
    token = os.getenv('EF_SCRUTINEER_GITHUB_TOKEN') or os.getenv('GITHUB_TOKEN')
    if token:
        # Support PAT or GH app tokens
        headers['Authorization'] = f'Bearer {token}'
    return headers


def _http_get_json(url: str) -> Optional[object]:
    req = urllib.request.Request(url, headers=_github_headers())
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            return json.loads(data.decode('utf-8', errors='replace'))
    except Exception:
        return None


def _http_get_bytes(url: str) -> Optional[bytes]:
    headers = _github_headers()
    # Request raw content for release assets
    headers['Accept'] = 'application/octet-stream'
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
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
            'efdrift-scrutineer-setup.exe',
        ])
    for n in names:
        for a in assets:
            if a.name == n:
                return a
    for a in assets:
        if a.name.lower().endswith('.exe'):
            return a
    return None


def _try_manifest_from_assets(assets: List[ReleaseAsset]) -> Optional[ReleaseAsset]:
    """If the release includes a small JSON manifest asset, use it to resolve
    the actual download URL (e.g., Cloudflare R2 URL). Expected JSON shape:
    {"name": "efdrift-scrutineer-setup.exe", "url": "https://.../setup.exe", "size": 0, "sha256": "..."}
    """
    manifest_names = {
        'update.json', 'latest.json', 'manifest.json',
        'efdrift-scrutineer-update.json', 'efdrift-update.json',
    }
    manifest_asset: Optional[ReleaseAsset] = None
    for a in assets:
        if a.name.lower() in manifest_names:
            manifest_asset = a
            break
    if not manifest_asset:
        return None
    data = _http_get_bytes(manifest_asset.url)
    if not data:
        return None
    try:
        payload = json.loads(data.decode('utf-8', errors='replace'))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    url = str(payload.get('url') or '')
    if not url:
        return None
    name = str(payload.get('name') or Path(urllib.parse.urlparse(url).path).name or 'efdrift-scrutineer-setup.exe')
    size = int(payload.get('size') or 0)
    return ReleaseAsset(name=name, url=url, size=size)


def _env_override_asset(channel: str) -> Optional[ReleaseAsset]:
    """Allow overriding update asset via environment variable.

    EF_SCRUTINEER_UPDATE_URL or EF_SCRUTINEER_UPDATE_URL_<CHANNEL>
    (e.g., EF_SCRUTINEER_UPDATE_URL_STABLE) can point to a direct .exe URL.
    """
    url = os.getenv('EF_SCRUTINEER_UPDATE_URL')
    if not url:
        url = os.getenv(f'EF_SCRUTINEER_UPDATE_URL_{(channel or "stable").upper()}')
    if not url:
        return None
    try:
        name = Path(urllib.parse.urlparse(url).path).name or 'efdrift-scrutineer-setup.exe'
    except Exception:
        name = 'efdrift-scrutineer-setup.exe'
    return ReleaseAsset(name=name, url=url, size=0)


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


def _gdrive_file_id_from_url(url: str) -> Optional[str]:
    try:
        # Match /file/d/<id>/ or id=<id>
        m = re.search(r"/file/d/([A-Za-z0-9_-]+)", url)
        if m:
            return m.group(1)
        m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", url)
        if m:
            return m.group(1)
        return None
    except Exception:
        return None


def _download_gdrive(file_id: str, dest: Path) -> bool:
    # Public link flow using confirm token
    base = "https://drive.google.com/uc?export=download"
    params = f"id={file_id}"
    url1 = f"{base}&{params}"
    headers = {'User-Agent': 'ef-scrutineer-updater'}
    tmp = dest.with_suffix('.part')
    try:
        req1 = urllib.request.Request(url1, headers=headers)
        with urllib.request.urlopen(req1, timeout=30) as resp1:
            data = resp1.read().decode('utf-8', errors='replace')
            cookie = resp1.headers.get('Set-Cookie', '')
        m = re.search(r"confirm=([0-9A-Za-z_]+)", data)
        confirm = m.group(1) if m else None
        url2 = url1
        if confirm:
            url2 = f"{base}&confirm={confirm}&{params}"
        headers2 = {'User-Agent': 'ef-scrutineer-updater'}
        if cookie:
            headers2['Cookie'] = cookie
        req2 = urllib.request.Request(url2, headers=headers2)
        with urllib.request.urlopen(req2, timeout=300) as resp2, open(tmp, 'wb') as f:
            while True:
                chunk = resp2.read(65536)
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


def _handle_zip_and_launch(zip_path: Path) -> bool:
    try:
        extract_dir = zip_path.parent / f"extracted_{int(time.time())}"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_dir)
        # Prefer setup/installer exe
        candidates = []
        for p in extract_dir.rglob('*.exe'):
            candidates.append(p)
        if not candidates:
            return False
        # Pick installer-like exe if present
        exe = None
        for p in candidates:
            n = p.name.lower()
            if 'setup' in n or 'installer' in n:
                exe = p; break
        if exe is None:
            # Fallback to app exe
            for p in candidates:
                if p.name.lower().endswith('.exe'):
                    exe = p; break
        if exe is None:
            return False
        _install_downloaded(exe)
        return True
    except Exception:
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

    # Allow environment override for the asset URL; if not set, use GitHub Releases
    asset = _env_override_asset(ch)
    latest = None
    latest_ver_text = ''
    if asset is None:
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
        # Prefer manifest asset that points to external hosting (e.g., Cloudflare R2),
        # then fallback to a direct .exe asset.
        asset = _try_manifest_from_assets(latest.assets)
        if not asset:
            asset = _pick_asset_for_channel(latest.assets, ch)
        if not asset:
            messagebox.showinfo('Update', 'No suitable installer found in the latest release.')
            return

    updates_dir = _data_root() / 'updates'
    updates_dir.mkdir(parents=True, exist_ok=True)
    dest = updates_dir / asset.name
    # Support Google Drive public link via uc?export=download&id= or /file/d/<id>/...
    ok = False
    file_id = _gdrive_file_id_from_url(asset.url) if ('drive.google.com' in asset.url) else None
    if file_id:
        ok = _download_gdrive(file_id, dest)
    else:
        ok = _download(asset.url, dest)
    if not ok:
        messagebox.showerror('Update', 'Failed to download update. Please try again later.')
        return

    # If the asset is a zip, extract and launch contained installer/app
    if dest.suffix.lower() == '.zip':
        if _handle_zip_and_launch(dest):
            return
    # If the asset looks like an installer, launch it instead of in-place replace
    if asset.name.lower().find('setup') >= 0 or asset.name.lower().find('installer') >= 0:
        _install_downloaded(dest)
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
