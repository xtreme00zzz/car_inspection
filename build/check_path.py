from pathlib import Path
import sys
p = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('dist/efdrift-scrutineer-setup-0.2.0.zip')
print('CWD:', Path().resolve())
print('PATH:', p)
print('EXISTS:', p.exists())
if p.exists():
    print('SIZE:', p.stat().st_size)

