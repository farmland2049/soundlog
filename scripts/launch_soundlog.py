#!/usr/bin/env python3
"""Start or reuse the local workbench without installing dependencies."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit


def root_key(root):
    return hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:24]


def healthy(config, root):
    try:
        url=config['url'];parts=urlsplit(url)
        if parts.scheme!='http' or parts.hostname!='127.0.0.1' or not parts.port or parts.query or parts.fragment:return False
        import re
        if not re.fullmatch(r'/[A-Za-z0-9_-]{24,}/',parts.path):return False
        with urllib.request.urlopen(url+'api/health',timeout=1) as response:data=json.load(response)
        return data.get('application')=='soundlog-workbench' and data.get('rootKey')==root_key(root)
    except (OSError,ValueError,KeyError):return False


def launch(root, open_browser=True):
    root=Path(root).resolve();home=root/'记忆库/运行/自动管线';home.mkdir(parents=True,exist_ok=True)
    with (home/'launcher.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path=home/'hub.json';config={}
        if path.exists():
            try:config=json.loads(path.read_text())
            except (OSError,ValueError):pass
        if not healthy(config,root):
            # Never terminate an unknown process just because a PID or port was recorded.
            with (home/'workbench.log').open('a') as log:
                process=subprocess.Popen([sys.executable,str(root/'scripts/soundlog_hub.py'),'--root',str(root)],cwd=root,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
            for _ in range(100):
                if process.poll() is not None:raise RuntimeError('工作台启动失败，请查看记忆库/运行/自动管线/workbench.log')
                try:config=json.loads(path.read_text())
                except (OSError,ValueError):config={}
                if healthy(config,root):break
                time.sleep(.1)
            else:raise RuntimeError('工作台未在10秒内就绪，请查看workbench.log；再次启动将核对已有服务')
        if open_browser:
            if sys.platform=='darwin':subprocess.run(['open',config['url']],check=True)
            else:
                import webbrowser
                webbrowser.open(config['url'])
        return config['url']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent);parser.add_argument('--no-open',action='store_true');args=parser.parse_args()
    try:print(launch(args.root,not args.no_open));return 0
    except (OSError,RuntimeError,subprocess.SubprocessError) as error:print(str(error),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
