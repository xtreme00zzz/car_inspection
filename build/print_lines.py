import sys
from pathlib import Path

path = Path(sys.argv[1])
start = int(sys.argv[2])
count = int(sys.argv[3])
lines = path.read_text(encoding='utf-8', errors='ignore').splitlines()
end = min(len(lines), start - 1 + count)
for i in range(start, end + 1):
    print(f"{i:05d}: {lines[i-1]}")

