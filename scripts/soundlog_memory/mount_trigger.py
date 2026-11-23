"""Observe configured macOS volumes and trigger once per connection."""
import logging
from pathlib import Path
import time

from .audio_sources import settings


def mounted_sources(root):
    config = settings(root)
    if not config.get('autoProcessOnMount'):
        return {}
    sources = {}
    for directory in config['directories']:
        path = Path(directory)
        if len(path.parts) < 3 or path.parts[:2] != ('/', 'Volumes'):
            continue
        volume = Path(*path.parts[:3])
        try:
            if volume.is_symlink() or not volume.is_mount() or path.resolve(strict=True) != path:
                continue
            identity = volume.stat()
            if path.is_dir() and path.stat().st_dev == identity.st_dev:
                sources[directory] = (identity.st_dev, identity.st_ino)
        except OSError:
            continue
    return sources


def observe(root, start, stop):
    known = {}
    handled = set()
    while not stop.is_set():
        try:
            sources = mounted_sources(root)
            pending = {(path, identity) for path, identity in sources.items()}
            handled.intersection_update(pending)
            now = time.monotonic()
            known = {key: known.get(key, now) for key in pending}
            # Give newly mounted recorders time to expose their directory tree.
            ready = {path: identity for (path, identity), since in known.items()
                     if now - since >= 5 and (path, identity) not in handled}
            if ready and start(ready):
                handled.update(ready.items())
        except (OSError, ValueError, RuntimeError) as error:
            logging.warning('Soundlog 外部存储检测：%s', error)
        stop.wait(2)
