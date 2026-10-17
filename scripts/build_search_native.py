"""Build the Mojo search extension atomically and record compiler/source identity."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mojo', default=shutil.which('mojo') or str(Path(sys.executable).parent / 'mojo'))
    args = parser.parse_args()
    sources = ['app_mojo/roms_search_native.mojo', 'app_mojo/search_kernels.mojo', 'app_mojo/document_text.mojo']
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    before = {name: digest(ROOT / name) for name in sources}
    version = subprocess.check_output([args.mojo, '--version'], text=True).strip()
    target = ROOT / 'app/roms_search_native.so'
    with tempfile.TemporaryDirectory(prefix='roms-search-build-', dir=ROOT / 'app') as work:
        output = Path(work) / target.name
        subprocess.run([args.mojo, 'build', str(ROOT / sources[0]), '-I', str(ROOT),
                        '--emit', 'shared-lib', '--Werror', '-o', str(output)], check=True)
        if any(digest(ROOT / name) != value for name, value in before.items()):
            raise RuntimeError('Search sources changed during compilation')
        manifest = {'compiler': version, 'sources': before, 'binary_sha256': digest(output)}
        os.replace(output, target)
    (ROOT / 'docs/verification/local-search-mojo-artifact.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'Built {target} with {version}')


if __name__ == '__main__':
    main()
