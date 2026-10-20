"""Create checksum files for the built Python artifacts."""
import hashlib
from pathlib import Path
import sys
root = Path(sys.argv[1])
for p in root.iterdir():
    if p.suffix == '.whl' or p.name.endswith('.tar.gz'):
        p.with_name(p.name + '.sha256').write_text(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n')
