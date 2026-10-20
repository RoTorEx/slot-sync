"""Interactive kernel-compliant release preparation and explicit push."""
from datetime import datetime
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from zoneinfo import ZoneInfo


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def run(*args):
    subprocess.run(args, check=True)


if git('branch', '--show-current') != 'main' or git('status', '--porcelain'):
    raise SystemExit('Release requires a clean main branch')
current = tomllib.loads(Path('pyproject.toml').read_text())['project']['version']
if sys.argv[1:] == ['--push']:
    if git('rev-parse', 'v' + current + '^{}') != git('rev-parse', 'HEAD'):
        raise SystemExit('Release tag must point to HEAD')
    run('git', 'push', 'origin', 'main', 'refs/tags/v' + current)
elif sys.argv[1:]:
    raise SystemExit('Use make release or make release-push')
else:
    run('git', 'fetch', 'origin', 'main', '--tags')
    run('git', 'merge-base', '--is-ancestor', 'origin/main', 'HEAD')
    version = input(f'Current version: {current}\nRelease version (MAJOR.MINOR.PATCH): ').strip()
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise SystemExit('Invalid version')
    if tuple(map(int, version.split('.'))) <= tuple(map(int, current.split('.'))):
        raise SystemExit('Release version must increase')
    if subprocess.run(['git', 'rev-parse', '--verify', 'refs/tags/v' + version], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise SystemExit('Tag already exists')
    run('make', 'check')
    p = Path('pyproject.toml')
    p.write_text(p.read_text().replace(f'version = "{current}"', f'version = "{version}"', 1))
    p = Path('src/callendars_syncer/__init__.py')
    p.write_text(p.read_text().replace(f'__version__ = "{current}"', f'__version__ = "{version}"'))
    p = Path('CHANGELOG.md')
    text = p.read_text()
    if text.count('## [Unreleased]') != 1:
        raise SystemExit('Expected one Unreleased section')
    date = datetime.now(ZoneInfo('Europe/Warsaw')).date().isoformat()
    p.write_text(text.replace('## [Unreleased]', f'## [Unreleased]\n\n## [{version}] - {date}', 1))
    run('uv', 'lock')
    run('make', 'check')
    run('git', 'add', 'pyproject.toml', 'uv.lock', 'src/callendars_syncer/__init__.py', 'CHANGELOG.md')
    run('git', 'commit', '-m', 'build: release v' + version)
    run('git', 'tag', '-a', 'v' + version, '-m', 'Release ' + version)
    print('Prepared v' + version + '; run make release-push')
