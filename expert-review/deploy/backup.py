"""Consistent SQLite snapshot with key, private permissions and bounded retention."""
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def backup(source, destination, retain=14):
    os.umask(0o077)
    source, destination = Path(source), Path(destination)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    with tempfile.TemporaryDirectory(dir=destination, prefix='.pending-') as folder:
        folder = Path(folder)
        with closing(sqlite3.connect(f'file:{source / "review.sqlite3"}?mode=ro', uri=True)) as live:
            with closing(sqlite3.connect(folder / 'review.sqlite3')) as snap:
                live.backup(snap)
                if snap.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Backup integrity check failed')
        shutil.copyfile(source / 'admin-access.txt', folder / 'admin-access.txt')
        for p in folder.iterdir():
            p.chmod(0o600)
        archive = shutil.make_archive(str(destination / ('.pending-' + stamp)), 'gztar', folder)
        final = destination / ('review-' + stamp + '.tar.gz')
        os.replace(archive, final)
        final.chmod(0o600)
    # Delete only our complete archives, and only after the new snapshot succeeded.
    for old in sorted(destination.glob('review-*.tar.gz'), reverse=True)[retain:]:
        old.unlink()
    print('Created verified backup:', final.name)
    return final


if __name__ == '__main__':
    backup(os.environ.get('REVIEW_DATA_DIR', '/var/lib/competence-review'),
           os.environ.get('REVIEW_BACKUP_DIR', '/var/backups/competence-review'))
