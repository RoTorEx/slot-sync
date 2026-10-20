"""Read-only syntax, metadata and service-contract checks."""
import ast
from pathlib import Path
import subprocess
import tomllib

root = Path(__file__).resolve().parent.parent
for directory in ('src', 'tests', 'scripts'):
    for p in (root / directory).rglob('*.py'):
        ast.parse(p.read_text(), filename=str(p))
for p in root.rglob('*.toml'):
    if not any(part.startswith('.') for part in p.relative_to(root).parts):
        tomllib.loads(p.read_text())
for p in (root / 'scripts').glob('*.sh'):
    subprocess.run(['sh', '-n', str(p)], check=True)
print('Syntax and TOML checks passed')

metadata = tomllib.loads((root / 'pyproject.toml').read_text())
version_tree = ast.parse((root / 'src/slot_sync/__init__.py').read_text())
version = next(ast.literal_eval(n.value) for n in version_tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__version__' for t in n.targets))
assert version == metadata['project']['version'], 'Package version sources differ'
