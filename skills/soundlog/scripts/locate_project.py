#!/usr/bin/env python3
"""Locate the Soundlog checkout without processing audio or reading private data."""
import argparse
import os
from pathlib import Path
import sys

REQUIRED = ('README.md', '需求说明.md', 'PROJECT_STATUS.md',
            'scripts/pipeline-agent.md', 'scripts/soundlog_pipeline.py',
            'scripts/soundlog_memory/pipeline.py')


def locate(root=None):
    explicit = root if root is not None else os.environ.get('SOUNDLOG_ROOT')
    if explicit is not None:
        if not str(explicit).strip(): raise ValueError('Soundlog项目路径为空')
        candidate = Path(explicit).expanduser().resolve()
    else:
        # resolve follows the installed skill symlink back to the maintained package.
        candidate = Path(__file__).resolve().parents[3]
    missing = [name for name in REQUIRED if not (candidate/name).is_file()]
    if missing:
        raise ValueError('未定位到有效Soundlog仓库；请用--root或SOUNDLOG_ROOT指定项目目录。缺少：' + ', '.join(missing))
    return candidate


def main():
    parser = argparse.ArgumentParser(description='输出Soundlog项目路径；不处理音频')
    parser.add_argument('--root')
    args = parser.parse_args()
    try:
        print(locate(args.root)); return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr); return 2


if __name__ == '__main__':
    raise SystemExit(main())
