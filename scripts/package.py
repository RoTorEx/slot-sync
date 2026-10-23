"""Create checksum files for the built Python artifacts."""
import hashlib
from pathlib import Path
import sys
import re
root = Path(sys.argv[1])
metadata = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
match = re.search(r'^version = "(\d+\.\d+\.\d+)"$', metadata, re.MULTILINE)
if not match:
    raise ValueError("Missing native project version")
version = match.group(1)
if not any(p.name.startswith("slot_sync-" + version + "-") or p.name == "slot_sync-" + version + ".tar.gz" for p in root.iterdir()):
    raise ValueError("Build the current package before pruning old build artifacts")
for previous in list(root.iterdir()):
    match = re.match(r"slot[-_]sync-(\d+\.\d+\.\d+)(?:-|\.)", previous.name)
    if (match and match.group(1) != version and previous.is_file() and not previous.is_symlink()
            and any(previous.name.endswith(suffix) for suffix in (".whl", ".tar.gz", ".whl.sha256", ".tar.gz.sha256"))):
        previous.unlink()
for p in root.iterdir():
    if p.suffix == '.whl' or p.name.endswith('.tar.gz'):
        p.with_name(p.name + '.sha256').write_text(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n')
