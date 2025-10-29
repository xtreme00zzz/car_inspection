from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import sys
import time
from pathlib import Path


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(args: list[str]) -> None:
    try:
        params = ' '.join(f'"{a}"' for a in args)
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        sys.exit(0)
    except Exception:
        sys.exit(5)


def wait_for_pid(pid: int, timeout: float = 120.0) -> None:
    if pid <= 0:
        return
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            # On Windows, os.kill not reliable; use OpenProcess
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                exit_code = ctypes.c_ulong()
                ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                ctypes.windll.kernel32.CloseHandle(handle)
                # STILL_ACTIVE == 259
                if exit_code.value != 259:
                    return
            else:
                return
        except Exception:
            return
        time.sleep(0.25)


def try_replace_file(src: Path, dest: Path) -> None:
    # Ensure dest dir exists
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Backup old
    backup = dest.with_suffix(dest.suffix + '.bak')
    for _ in range(20):
        try:
            if dest.exists():
                try:
                    if backup.exists():
                        backup.unlink(missing_ok=True)  # type: ignore[arg-type]
                except Exception:
                    pass
                try:
                    # Try in-place replacement
                    os.replace(dest, backup)
                except PermissionError:
                    pass
            # Copy new over
            shutil.copy2(src, dest)
            return
        except PermissionError:
            time.sleep(0.25)
        except Exception:
            time.sleep(0.25)
    # Final attempt
    shutil.copy2(src, dest)


def main() -> int:
    p = argparse.ArgumentParser(description='Windows updater stub')
    p.add_argument('--target', required=True, help='Path to existing executable to replace')
    p.add_argument('--package', required=True, help='Path to downloaded new executable')
    p.add_argument('--wait-pid', type=int, default=0, help='PID to wait for exit')
    p.add_argument('--launch', action='store_true', help='Launch the updated app after replacing')
    args = p.parse_args()

    target = Path(args.target).resolve()
    package = Path(args.package).resolve()

    # Wait for running process to exit, if provided
    wait_for_pid(args.wait_pid)

    # If we cannot write to target directory, request elevation
    try:
        test_path = target.parent / '.__update_test__'
        with open(test_path, 'wb') as f:
            f.write(b'1')
        try:
            test_path.unlink()
        except Exception:
            pass
    except PermissionError:
        if os.name == 'nt' and not is_admin():
            # Relaunch elevated with same args
            relaunch_as_admin(sys.argv[1:])
        else:
            return 2

    # Attempt replacement
    try:
        try_replace_file(package, target)
    except PermissionError:
        return 3
    except Exception:
        return 4

    if args.launch:
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())

