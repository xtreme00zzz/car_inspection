import importlib.util
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
dist = root / 'dist'
src = dist / '_installer' / 'efdrift-scrutineer-setup.exe'

# Load app_version without importing package context
app_version_path = root / 'app_version.py'
spec = importlib.util.spec_from_file_location('app_version', str(app_version_path))
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)
ver = getattr(mod, 'APP_VERSION', '0.0.0')
dst = dist / f'efdrift-scrutineer-setup-{ver}.zip'

if not src.exists():
    raise SystemExit(f'Source installer not found: {src}')

dst.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as z:
    z.write(src, arcname=src.name)
print(dst)

