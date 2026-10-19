"""Validated, per-file atomic snapshot restoration for a quiescent workspace.

This is not a multi-file transaction or a sandbox against concurrent local
filesystem changes. Stop other writers before taking or restoring a snapshot.
"""
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile


def checked_path(path):
    """Reject symlinks, Windows junctions and non-directory ancestors."""
    path = Path(os.path.abspath(path))
    for item in [*reversed(path.parents), path]:
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError(f'Snapshot path must not traverse a link: {item}')
        if item != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError(f'Snapshot ancestor is not a directory: {item}')
    return path


def workspace_path(root):
    root = checked_path(root)
    if not root.is_dir():
        raise ValueError('Snapshot workspace must be an existing directory')
    return root


def validate_relative(relative):
    if not isinstance(relative, str) or not relative or any(c in relative for c in ('\\', ':', '\x00')):
        raise ValueError('Invalid snapshot relative path')
    devices = {'con', 'prn', 'aux', 'nul'} | {f'{p}{i}' for p in ('com', 'lpt') for i in range(1, 10)}
    for part in relative.split('/'):
        if (part in ('', '.', '..') or part.rstrip(' .') != part or
                part.lower() == '.git' or part.split('.')[0].lower() in devices):
            raise ValueError('Invalid snapshot relative path')


def restore_files(snapshot, root, state_dir):
    root = workspace_path(root)
    if snapshot.get('workspace_root') != str(root):
        raise ValueError('Snapshot belongs to another workspace or predates workspace binding; '
                         'preserve it for manual recovery and create a new bound snapshot')
    state = checked_path(state_dir)
    files = snapshot.get('files')
    if not isinstance(files, dict):
        raise ValueError('Invalid snapshot file map')
    planned = []
    for relative, digest in files.items():
        validate_relative(relative)
        destination = checked_path(root / relative)
        if destination == state or state in destination.parents:
            raise ValueError('Snapshot cannot restore into its own state directory')
        if destination.exists() and not destination.is_file():
            raise ValueError('Snapshot destination is not a regular file')
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{24}', digest):
            raise ValueError('Invalid snapshot blob identifier')
        blob = checked_path(state / 'cas' / digest)
        if not blob.is_file():
            raise ValueError(f'Snapshot blob missing or not a regular file: {digest}')
        data = blob.read_bytes()
        if hashlib.sha256(data).hexdigest()[:24] != digest:
            raise ValueError(f'Snapshot blob checksum mismatch: {digest}')
        planned.append((destination, blob, digest))
    # Validate the whole manifest before creating any directories or files.
    destinations = {destination for destination, _, _ in planned}
    if any(parent in destinations for destination in destinations for parent in destination.parents):
        raise ValueError('Snapshot file paths conflict with directory paths')
    for destination, blob, digest in planned:
        data = checked_path(blob).read_bytes()
        if hashlib.sha256(data).hexdigest()[:24] != digest:
            raise ValueError(f"Snapshot blob changed during restore: {digest}")
        checked_path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        checked_path(destination)
        mode = stat.S_IMODE(destination.stat().st_mode) if destination.exists() else 0o600
        fd, temporary = tempfile.mkstemp(prefix='.snapshot-', dir=destination.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            checked_path(destination)
            # Replace the directory entry, never truncate a hard-linked target.
            os.replace(temporary, destination)
        finally:
            if os.path.lexists(temporary):
                os.unlink(temporary)
    return len(planned)
