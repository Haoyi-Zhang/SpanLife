"""Publish a generated file set with rollback on ordinary replacement failures."""
from pathlib import Path
import os
import shutil
import tempfile


class PublicationRollbackError(RuntimeError):
    def __init__(self, backup_directory, errors):
        self.backup_directory = Path(backup_directory)
        super().__init__(f'Asset rollback incomplete; recovery backup retained at '
                         f'{self.backup_directory}: ' + '; '.join(errors))


def publish_tree(staged, destination):
    """Keep unrelated files; restore replaced bytes if any installation fails.

    The caller owns a complete, validated staging tree. This is an exception-
    rollback transaction, not a durable transaction across process termination.
    """
    staged, destination = Path(staged), Path(destination)
    files = sorted(path.relative_to(staged) for path in staged.rglob('*') if path.is_file())
    if not files:
        raise ValueError('No generated files to publish')
    for relative in files:
        target = destination / relative
        if target.exists() and (not target.is_file() or target.is_symlink()):
            raise ValueError(f'Not a regular publication target: {target}')
    # Keep recovery files outside the caller's disposable staging tree.
    backup_parent = destination.parent
    while not backup_parent.exists():
        backup_parent = backup_parent.parent
    backup = Path(tempfile.mkdtemp(prefix='.asset-backup-', dir=backup_parent))
    preserve_backup = False
    try:
        originals = set()
        for relative in files:
            target = destination / relative
            if target.exists():
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
                originals.add(relative)
        installed, created_dirs = [], []
        try:
            for relative in files:
                target = destination / relative
                missing = []
                parent = target.parent
                while not parent.exists():
                    missing.append(parent)
                    parent = parent.parent
                for parent in reversed(missing):
                    parent.mkdir()
                    created_dirs.append(parent)
                os.replace(staged / relative, target)
                installed.append(relative)
        except BaseException as publication_error:
            preserve_backup = True
            errors = []
            for relative in reversed(installed):
                target = destination / relative
                try:
                    if relative in originals:
                        os.replace(backup / relative, target)
                    else:
                        target.unlink()
                except OSError as exc:
                    errors.append(f'{relative}: {exc}')
            for parent in reversed(created_dirs):
                try:
                    parent.rmdir()
                except OSError as exc:
                    errors.append(f'{parent}: {exc}')
            if errors:
                raise PublicationRollbackError(backup, errors) from publication_error
            preserve_backup = False
            raise
    finally:
        if not preserve_backup:
            shutil.rmtree(backup)
