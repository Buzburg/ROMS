# Snapshot recovery boundaries

Restore validates the snapshot workspace, all recorded destination paths, and all required content blobs before it changes workspace files. Absolute paths, parent traversal, symlinks, Windows junctions and writes into snapshot metadata are rejected. Missing or corrupt saved content is an error, not a successful recovery.

Each restored file is written to a temporary sibling and atomically replaces its directory entry. This prevents truncating an outside file through a hard link. It is not a transaction over the entire workspace: an I/O failure during restoration can leave some files restored and others unchanged. Stop other writers before taking or restoring a snapshot. These checks are not a sandbox against another local process racing directory renames or filesystem changes.

New snapshots record their original workspace location. Automatic restore refuses snapshots from another location and older snapshots without that binding. Existing snapshot files and blobs are preserved. Keep them for deliberate manual recovery into a disposable directory; do not edit a manifest to bypass validation. Create a new snapshot to use automatic recovery with the current format.

Snapshots save regular file contents, not a complete filesystem image or permission/ownership history. Keep independent backups. Restore replaces recorded file contents; it does not remove files added after the snapshot. Snapshot creation refuses included symlinks rather than reading files outside the workspace.
