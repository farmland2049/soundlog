#!/usr/bin/env python3
"""Search functional candidates without changing evidence or memories."""
import argparse
import json
from pathlib import Path
import sys

from soundlog_memory.product_search import search_products


def main(argv=None):
    parser = argparse.ArgumentParser(description='功能候选及原话关键词检索')
    parser.add_argument('query')
    parser.add_argument('--result', action='append', required=True)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent /
                        '产出/功能提炼')
    parser.add_argument('--date')
    parser.add_argument('--function', choices=['journal', 'minutes', 'actions', 'learning'])
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--offset', type=int, default=0)
    args = parser.parse_args(argv)
    try:
        result = search_products(args.root, args.result, args.query, day=args.date,
                                 function=args.function, limit=args.limit, offset=args.offset)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('功能候选检索失败: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
