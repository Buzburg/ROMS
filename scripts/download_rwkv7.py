"""Verify supplied GGUF inputs or acquire an explicitly identified HTTPS artifact."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import tempfile
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'config/build-inputs.json'
MAX_BYTES = 64 * 1024**3


def validate_spec(spec: dict) -> None:
    if (spec.get('format') != 'GGUF' or type(spec.get('bytes')) is not int
            or not 24 <= spec['bytes'] <= MAX_BYTES
            or not re.fullmatch('[a-f0-9]{64}', spec.get('sha256', ''))):
        raise ValueError('GGUF format, exact size and lowercase SHA-256 are required')


def validate_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or any(ord(character) < 33 for character in url)):
        raise ValueError('Use an explicit HTTPS URL without credentials, fragments or whitespace')
    return url


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def check_header(header: bytes) -> None:
    if len(header) != 24:
        raise ValueError('Truncated GGUF header')
    magic, version, tensors, metadata = struct.unpack('<4sIQQ', header)
    if magic != b'GGUF' or version != 3 or not tensors or not metadata:
        raise ValueError('Expected a little-endian GGUF v3 model; no format conversion is performed')


def verify_file(path: Path, spec: dict) -> dict:
    validate_spec(spec)
    path_before = path.lstat()
    if path.suffix.lower() != '.gguf' or stat.S_ISLNK(path_before.st_mode):
        raise ValueError('Use a regular .gguf file, not a symlink or renamed checkpoint')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
    with os.fdopen(fd, 'rb') as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size != spec['bytes']:
            raise ValueError('Model size or file type does not match the input record')
        check_header(source.read(24))
        source.seek(0)
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
        after = os.fstat(source.fileno())
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        path_after = path.lstat()
        # Windows Python can give fstat and lstat different ctime semantics.
        # Track each API's full identity separately, and match the shared file
        # identity/size/mtime across APIs without comparing their ctime values.
        shared = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if (identity(before) != identity(after)
                or identity(path_before) != identity(path_after)
                or shared(after) != shared(path_after)
                or not stat.S_ISREG(path_after.st_mode)):
            raise ValueError('Model changed during verification')
        if digest != spec['sha256']:
            raise ValueError('Model SHA-256 does not match the input record')
    return {'status': 'verified_local_bytes', 'path': str(path), 'format': 'GGUF',
            'bytes': after.st_size, 'sha256': digest,
            'publisher_provenance': spec.get('publisher_provenance', 'unverified')}


def acquire(url: str, destination: Path, spec: dict) -> dict:
    validate_spec(spec)
    validate_url(url)
    if destination.suffix.lower() != '.gguf':
        raise ValueError('GGUF downloads must retain a .gguf filename')
    if destination.exists() or destination.is_symlink():
        return verify_file(destination, spec)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination.parent).free < spec['bytes']:
        raise ValueError('Insufficient space for the exact model size')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), HTTPSRedirect())
    fd, temporary = tempfile.mkstemp(prefix='.' + destination.stem + '-', suffix='.part', dir=destination.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, 'wb') as output:
            request = urllib.request.Request(url, headers={'Accept-Encoding': 'identity'})
            with opener.open(request, timeout=30) as response:
                validate_url(response.geturl())
                if response.status != 200 or response.headers.get('Content-Encoding', 'identity') != 'identity':
                    raise ValueError('Expected an unencoded complete HTTP 200 response')
                length = response.headers.get('Content-Length')
                if length is not None and int(length) != spec['bytes']:
                    raise ValueError('Download Content-Length does not match the input record')
                digest, header, total = hashlib.sha256(), bytearray(), 0
                deadline = time.monotonic() + 1800
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Download exceeded its total deadline')
                    chunk = response.read(min(1024**2, spec['bytes'] + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > spec['bytes']:
                        raise ValueError('Download exceeds the expected size')
                    header.extend(chunk[:max(0, 24 - len(header))])
                    digest.update(chunk)
                    output.write(chunk)
                if total != spec['bytes'] or digest.hexdigest() != spec['sha256']:
                    raise ValueError('Incomplete download or SHA-256 mismatch')
                check_header(bytes(header))
            output.flush()
            os.fsync(output.fileno())
        # Same-filesystem hard link publishes a complete file without replacing an existing path.
        os.link(temporary, destination)
        if hasattr(os, 'O_DIRECTORY'):
            directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return {'status': 'verified_download', 'path': str(destination), 'format': 'GGUF',
                'bytes': total, 'sha256': digest.hexdigest(),
                'publisher_provenance': spec.get('publisher_provenance', 'unverified')}
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    inputs = json.loads(MANIFEST.read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=inputs['models'], default=inputs['default_model'])
    parser.add_argument('--target-dir', type=Path, default=ROOT.parent,
                        help='Folder containing the supplied model, or destination for an explicit download')
    parser.add_argument('--url', help='Operator-reviewed HTTPS source; downloaded bytes must match the input record')
    parser.add_argument('--dry-run', action='store_true', help='Show the plan without network, hashing or writes')
    parser.add_argument('--build-librwkv', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.build_librwkv:
        parser.error('The unpinned librwkv build was removed; use scripts/build_llama.py for the pinned GGUF runtime')
    spec = inputs['models'][args.model]
    validate_spec(spec)
    if args.url:
        validate_url(args.url)
    destination = args.target_dir / spec['filename']
    if args.dry_run:
        result = {'status': 'planned_not_verified', 'path': str(destination), 'expected': spec,
                  'network_planned': bool(args.url), 'note': 'No URL connectivity or local file identity was verified'}
    elif args.url:
        result = acquire(args.url, destination, spec)
    else:
        result = verify_file(destination, spec)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit('Model input verification failed: ' + str(error)) from error
