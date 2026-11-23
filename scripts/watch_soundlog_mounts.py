#!/usr/bin/env python3
"""Monitor mounted recording sources and open the Soundlog app on a match."""
import argparse
import fcntl
import os
from pathlib import Path
import plistlib
import secrets
import subprocess
from threading import Event

from soundlog_memory.audio_sources import home
from soundlog_memory.mount_trigger import observe
from soundlog_memory.store import write_json


LABEL = 'local.soundlog.mount-monitor'


def monitor(root):
    runtime = home(root)
    runtime.mkdir(parents=True, exist_ok=True)
    app = root/'界面/应用/Soundlog.app'

    def wake(mounted):
        name = secrets.token_hex(16)
        request = runtime/'mount-wakes'/f'{name}.json'
        write_json(request, {'sources': mounted})
        try:
            subprocess.run(['/usr/bin/open', '-a', str(app)], check=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as error:
            request.unlink(missing_ok=True)
            raise RuntimeError(f'无法打开 Soundlog 应用：{error}') from error
        return True

    with (runtime/'mount-monitor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Requests from a previous monitor session are superseded by fresh mount detection.
        for request in (runtime/'mount-wakes').glob('*.json'):
            request.unlink(missing_ok=True)
        observe(root, wake, Event())


def install(root):
    app = root/'界面/应用/Soundlog.app/Contents/MacOS/Soundlog'
    if not app.is_file():
        raise RuntimeError('请先构建 Soundlog.app')
    runtime = home(root)
    runtime.mkdir(parents=True, exist_ok=True)
    agents = Path.home()/'Library/LaunchAgents'
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents/f'{LABEL}.plist'
    domain = f'gui/{os.getuid()}'
    target = f'{domain}/{LABEL}'
    if subprocess.run(['/bin/launchctl', 'print', target], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode == 0:
        subprocess.run(['/bin/launchctl', 'bootout', target], check=True)
    payload = {
        'Label': LABEL,
        'ProgramArguments': ['/usr/bin/python3', str(Path(__file__).resolve()), '--root', str(root)],
        'WorkingDirectory': str(root),
        'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10,
        'StandardOutPath': str(runtime/'mount-monitor.log'),
        'StandardErrorPath': str(runtime/'mount-monitor.log'),
    }
    plist.write_bytes(plistlib.dumps(payload))
    subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(plist)], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    (install if args.install else monitor)(args.root.resolve())


if __name__ == '__main__':
    main()
