"""Model acquisition cannot publish incomplete, renamed or unverified bytes."""
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import urllib.error

import pytest

from scripts import download_rwkv7 as models

PAYLOAD = struct.pack('<4sIQQ', b'GGUF', 3, 1, 1) + b'fixture-data'
SPEC = {'format': 'GGUF', 'bytes': len(PAYLOAD), 'sha256': hashlib.sha256(PAYLOAD).hexdigest()}
URL = 'https://model.example/pinned/model.gguf'


class Response(io.BytesIO):
    status = 200
    headers = {}

    def geturl(self):
        return URL


@pytest.fixture
def destination(tmp_path):
    return tmp_path / 'model.gguf'


def fake_open(monkeypatch, response):
    class Opener:
        def open(self, request, timeout):
            assert timeout == 30 and request.full_url == URL
            if isinstance(response, BaseException):
                raise response
            return response
    monkeypatch.setattr(models.urllib.request, 'build_opener', lambda *_: Opener())


def test_success_and_cached_identity_are_verified(destination, monkeypatch):
    fake_open(monkeypatch, Response(PAYLOAD))
    result = models.acquire(URL, destination, SPEC)
    assert result['status'] == 'verified_download' and destination.read_bytes() == PAYLOAD
    assert result['publisher_provenance'] == 'unverified'
    fake_open(monkeypatch, AssertionError('Verified cache must not access the network'))
    assert models.acquire(URL, destination, SPEC)['status'] == 'verified_local_bytes'
    assert list(destination.parent.iterdir()) == [destination]


@pytest.mark.parametrize('data,spec', [
    (PAYLOAD[:-2], SPEC), (PAYLOAD + b'extra', SPEC),
    (PAYLOAD, dict(SPEC, sha256='0' * 64)),
    (b'PK00' + PAYLOAD[4:], dict(SPEC, sha256=hashlib.sha256(b'PK00' + PAYLOAD[4:]).hexdigest())),
])
def test_invalid_download_never_becomes_cache(destination, monkeypatch, data, spec):
    fake_open(monkeypatch, Response(data))
    with pytest.raises(ValueError):
        models.acquire(URL, destination, spec)
    assert not list(destination.parent.iterdir())


@pytest.mark.parametrize('failure', [OSError('transfer interrupted'),
    urllib.error.HTTPError(URL, 404, 'Not found', {}, None), KeyboardInterrupt()])
def test_failure_and_cancellation_remove_owned_partial_file(destination, monkeypatch, failure):
    class Interrupted(Response):
        def read(self, *_):
            if self.tell():
                raise failure
            return super().read(10)
    fake_open(monkeypatch, Interrupted(PAYLOAD))
    with pytest.raises(type(failure)):
        models.acquire(URL, destination, SPEC)
    assert not list(destination.parent.iterdir())


def test_http_open_failure_removes_partial_file(destination, monkeypatch):
    fake_open(monkeypatch, urllib.error.HTTPError(URL, 404, 'Not found', {}, None))
    with pytest.raises(urllib.error.HTTPError):
        models.acquire(URL, destination, SPEC)
    assert not list(destination.parent.iterdir())


def test_existing_wrong_cache_is_preserved_and_rejected(destination, monkeypatch):
    destination.write_bytes(PAYLOAD[:-1] + b'X')
    fake_open(monkeypatch, AssertionError('Never replace an existing wrong cache'))
    with pytest.raises(ValueError, match='SHA-256'):
        models.acquire(URL, destination, SPEC)
    assert destination.read_bytes() == PAYLOAD[:-1] + b'X'


def test_concurrent_destination_is_not_overwritten(destination, monkeypatch):
    class Concurrent(Response):
        def read(self, *args):
            data = super().read(*args)
            if not data:
                destination.write_text('user-owned concurrent file')
            return data
    fake_open(monkeypatch, Concurrent(PAYLOAD))
    with pytest.raises(FileExistsError):
        models.acquire(URL, destination, SPEC)
    assert destination.read_text() == 'user-owned concurrent file'
    assert list(destination.parent.iterdir()) == [destination]


@pytest.mark.parametrize('url', ['http://model.example/a', 'file:///etc/passwd', 'https://user:password@model.example/a',
                               'https://model.example/a#fragment', 'https://model.example/a\n'])
def test_unsafe_url_rejected_before_any_write(destination, url):
    with pytest.raises(ValueError):
        models.acquire(url, destination, SPEC)
    assert not list(destination.parent.iterdir())


def test_redirect_cannot_downgrade_transport():
    with pytest.raises(ValueError):
        models.HTTPSRedirect().redirect_request(None, None, 302, 'Found', {}, 'http://model.example/a')


def test_symlink_is_not_a_verified_cache(destination):
    original = destination.with_name('original.gguf')
    original.write_bytes(PAYLOAD)
    destination.symlink_to(original)
    with pytest.raises(ValueError, match='symlink'):
        models.verify_file(destination, SPEC)
    assert original.read_bytes() == PAYLOAD


def test_dry_run_has_no_network_hash_or_directory_side_effects(tmp_path, monkeypatch, capsys):
    destination = tmp_path / 'absent'
    monkeypatch.setattr(sys, 'argv', ['download_rwkv7.py', '--dry-run', '--target-dir', str(destination)])
    monkeypatch.setattr(models, 'verify_file', lambda *_: pytest.fail('Dry run hashed a model'))
    monkeypatch.setattr(models, 'acquire', lambda *_: pytest.fail('Dry run downloaded a model'))
    models.main()
    assert json.loads(capsys.readouterr().out)['status'] == 'planned_not_verified'
    assert not destination.exists()


def test_lockfile_identity_matches_reviewed_manifest():
    inputs = json.loads(models.MANIFEST.read_text())
    assert hashlib.sha256((models.ROOT / inputs['environment']['lockfile']).read_bytes()).hexdigest() == inputs['environment']['sha256']
    assert inputs['default_model'] == '2.9b'
    for spec in inputs['models'].values():
        models.validate_spec(spec)
        assert spec['filename'].endswith('.gguf')
        assert models.validate_url(spec['url']) == spec['url']
        assert '/' + spec['publisher_revision'] + '/' in spec['url']
        assert (models.ROOT / spec['publisher_pointer']).read_text().splitlines() == [
            'version https://git-lfs.github.com/spec/v1', 'oid sha256:' + spec['sha256'], 'size ' + str(spec['bytes'])]


@pytest.mark.parametrize('dirty,origin', [(True, 'expected'), (False, 'https://unexpected.example/source.git')])
def test_runtime_builder_refuses_modified_source_or_wrong_origin(tmp_path, monkeypatch, dirty, origin):
    from scripts import build_llama
    calls = []
    def git(command, **kwargs):
        calls.append(command)
        if command[-2:] == ['status', '--porcelain']:
            return b' M src/llama.cpp' if dirty else b''
        return origin
    monkeypatch.setattr(build_llama.subprocess, 'check_output', git)
    with pytest.raises(RuntimeError):
        build_llama.verify_clean_source(tmp_path)
    assert all(command[0] == 'git' for command in calls)


def test_runtime_revision_comes_from_input_manifest():
    from scripts import build_llama
    assert build_llama.REVISION == json.loads(models.MANIFEST.read_text())['runtime']['revision']


def test_path_and_handle_ctime_can_differ_without_content_change(destination, monkeypatch):
    # Windows Python 3.12+ can expose change time through fstat and birth time
    # through lstat. Each API is stable, but cross-API ctime equality is invalid.
    from types import SimpleNamespace
    destination.write_bytes(PAYLOAD)
    original = models.os.fstat
    def handle_stat(fd):
        info = original(fd)
        values = {name: getattr(info, name) for name in
                  ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
        values['st_ctime_ns'] += 1000000000
        return SimpleNamespace(**values)
    monkeypatch.setattr(models.os, 'fstat', handle_stat)
    assert models.verify_file(destination, SPEC)['status'] == 'verified_local_bytes'


@pytest.mark.parametrize('api', ['handle', 'path'])
def test_ctime_change_within_either_api_is_still_rejected(destination, monkeypatch, api):
    from types import SimpleNamespace
    destination.write_bytes(PAYLOAD)
    original = models.os.fstat if api == 'handle' else Path.lstat
    calls = []
    def changed_stat(value, *args, **kwargs):
        info = original(value, *args, **kwargs)
        calls.append(1)
        values = {name: getattr(info, name) for name in
                  ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
        if len(calls) > 1:
            values['st_ctime_ns'] += 1000000000
        return SimpleNamespace(**values)
    if api == 'handle':
        monkeypatch.setattr(models.os, 'fstat', changed_stat)
    else:
        monkeypatch.setattr(Path, 'lstat', changed_stat)
    with pytest.raises(ValueError, match='changed during verification'):
        models.verify_file(destination, SPEC)
