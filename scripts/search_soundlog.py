#!/usr/bin/env python3
"""Search transcript evidence and functional candidates in one snapshot."""
import argparse
import json
from pathlib import Path
import sys

from soundlog_memory.unified_search import search_soundlog


ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    parser = argparse.ArgumentParser(description='并列检索原文与功能候选，要求来源快照一致')
    parser.add_argument('query')
    parser.add_argument('--result', action='append', required=True)
    parser.add_argument('--scenes', type=Path, default=ROOT / '产出/大模型分析素材/每日场景-v2')
    parser.add_argument('--products', type=Path, default=ROOT / '产出/功能提炼')
    parser.add_argument('--date')
    parser.add_argument('--function', choices=['journal', 'minutes', 'actions', 'learning'])
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--offset', type=int, default=0)
    args = parser.parse_args(argv)
    try:
        result = search_soundlog(args.scenes, args.products, args.result, args.query,
                                 day=args.date, function=args.function,
                                 limit=args.limit, offset=args.offset)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('Soundlog统一检索失败: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
