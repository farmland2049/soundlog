#!/usr/bin/env python3
"""Search all transcript evidence, including unextracted short utterances."""
import argparse
import json
from pathlib import Path
import sys

from soundlog_memory.scenes import search_evidence

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    p = argparse.ArgumentParser(description='本地录音原文关键词检索，不限于已提炼记忆')
    p.add_argument('query')
    p.add_argument('--scenes', type=Path, default=ROOT / '产出/大模型分析素材/每日场景-v2')
    p.add_argument('--date')
    p.add_argument('--limit', type=int, default=20)
    p.add_argument('--offset', type=int, default=0)
    args = p.parse_args(argv)
    try:
        print(json.dumps(search_evidence(args.scenes, args.query, day=args.date,
                                         limit=args.limit, offset=args.offset), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('录音原文检索失败: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
