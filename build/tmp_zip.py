import zipfile
from pathlib import Path

src = Path('dist/efdrift-scrutineer-setup.exe')
dst = Path('dist/efdrift-scrutineer-setup.zip')
z = zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED)
z.write(src, arcname=src.name)
z.close()
print(dst.resolve())

