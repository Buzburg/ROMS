"""Filesystem regressions use only disposable workspaces and outside fixtures."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from app.prefrontal_cortex import WorkspaceTimeMachine


class SnapshotSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'workspace'
        self.root.mkdir()
        self.machine = WorkspaceTimeMachine(str(self.base / 'state'))
        self.first = self.root / 'first.txt'
        self.first.write_text('original first')
        self.nested = self.root / 'nested'
        self.nested.mkdir()
        self.last = self.nested / 'last.txt'
        self.last.write_text('original last')
        self.snapshot = self.machine.snapshot(workspace_root=str(self.root))
        self.first.write_text('changed first')
        self.last.write_text('changed last')

    def rewind(self):
        return self.machine.rewind(self.snapshot['id'], str(self.root))

    def manifest(self):
        return json.loads(Path(self.machine.manifest_file).read_text())

    def change_manifest(self, change):
        data = self.manifest()
        change(data['snapshots'][0])
        Path(self.machine.manifest_file).write_text(json.dumps(data))

    def assert_unchanged(self):
        self.assertEqual(self.first.read_text(), 'changed first')

    def link(self, target, path, directory=False):
        try:
            path.symlink_to(target, target_is_directory=directory)
        except OSError as error:
            self.skipTest(f'Symlink permission unavailable: {error}')

    def test_success_restores_modified_and_deleted_files(self):
        self.last.unlink()
        result = self.rewind()
        self.assertTrue(result['success'])
        self.assertEqual(result['files_restored'], 2)
        self.assertEqual(self.first.read_text(), 'original first')
        self.assertEqual(self.last.read_text(), 'original last')

    def test_symlink_leaf_rejected_before_any_write(self):
        outside = self.base / 'outside.txt'
        outside.write_text('outside')
        self.last.unlink()
        self.link(outside, self.last)
        with self.assertRaises(ValueError): self.rewind()
        self.assert_unchanged()
        self.assertEqual(outside.read_text(), 'outside')

    def test_symlink_directory_rejected_before_any_write(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'last.txt').write_text('outside')
        self.last.unlink()
        self.nested.rmdir()
        self.link(outside, self.nested, True)
        with self.assertRaises(ValueError): self.rewind()
        self.assert_unchanged()
        self.assertEqual((outside / 'last.txt').read_text(), 'outside')

    def test_hard_link_does_not_overwrite_outside_inode(self):
        outside = self.base / 'outside.txt'
        outside.write_text('outside')
        self.last.unlink()
        os.link(outside, self.last)
        self.assertTrue(self.rewind()['success'])
        self.assertEqual(outside.read_text(), 'outside')
        self.assertEqual(self.last.read_text(), 'original last')

    def test_missing_blob_rejected_before_any_write(self):
        digest = self.manifest()['snapshots'][0]['files']['nested/last.txt']
        (Path(self.machine.cas_dir) / digest).unlink()
        with self.assertRaises(ValueError): self.rewind()
        self.assert_unchanged()
        self.assertEqual(self.last.read_text(), 'changed last')

    def test_corrupt_blob_rejected_before_any_write(self):
        digest = self.manifest()['snapshots'][0]['files']['nested/last.txt']
        (Path(self.machine.cas_dir) / digest).write_text('corrupted')
        with self.assertRaises(ValueError): self.rewind()
        self.assert_unchanged()

    def test_blob_symlink_rejected(self):
        digest = self.manifest()['snapshots'][0]['files']['nested/last.txt']
        blob = Path(self.machine.cas_dir) / digest
        outside = self.base / 'blob-copy'
        outside.write_bytes(blob.read_bytes())
        blob.unlink()
        self.link(outside, blob)
        with self.assertRaises(ValueError): self.rewind()
        self.assert_unchanged()

    def test_invalid_paths_rejected_before_any_write(self):
        for path in ['../outside', '/outside', 'nested/../../outside', 'C:/outside',
                     'nested\\outside', 'nested//last.txt', '.git/config', '.GIT/config', '.git./config', 'NUL.txt']:
            with self.subTest(path=path):
                original = self.manifest()
                self.change_manifest(lambda s: s['files'].update({path: next(iter(s['files'].values()))}))
                with self.assertRaises(ValueError): self.rewind()
                self.assert_unchanged()
                Path(self.machine.manifest_file).write_text(json.dumps(original))

    def test_invalid_blob_identifier_rejected(self):
        self.change_manifest(lambda s: s['files'].update({'first.txt': '../../outside'}))
        with self.assertRaises(ValueError): self.rewind()
        self.assert_unchanged()

    def test_file_directory_conflict_rejected(self):
        self.change_manifest(lambda s: s['files'].update({'first.txt/child': next(iter(s['files'].values()))}))
        with self.assertRaises(ValueError): self.rewind()
        self.assert_unchanged()

    def test_snapshot_bound_to_original_workspace(self):
        other = self.base / 'other'
        other.mkdir()
        with self.assertRaises(ValueError): self.machine.rewind(self.snapshot['id'], str(other))
        self.assertEqual(list(other.iterdir()), [])

    def test_legacy_unbound_snapshot_preserved_and_rejected(self):
        self.change_manifest(lambda s: s.pop('workspace_root'))
        before = Path(self.machine.manifest_file).read_bytes()
        with self.assertRaises(ValueError): self.rewind()
        self.assertEqual(Path(self.machine.manifest_file).read_bytes(), before)
        self.assert_unchanged()

    def test_state_link_rejected_before_initialization(self):
        outside = self.base / 'outside-state'
        outside.mkdir()
        linked = self.base / 'linked-state'
        self.link(outside, linked, True)
        machine = WorkspaceTimeMachine(str(linked))
        with self.assertRaises(ValueError): machine.snapshot(workspace_root=str(self.root))
        self.assertEqual(list(outside.iterdir()), [])

    def test_snapshot_refuses_external_symlink(self):
        outside = self.base / 'private.txt'
        outside.write_text('outside private')
        self.link(outside, self.root / 'linked.txt')
        before = Path(self.machine.manifest_file).read_bytes()
        with self.assertRaises(ValueError): self.machine.snapshot(workspace_root=str(self.root))
        self.assertEqual(Path(self.machine.manifest_file).read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
