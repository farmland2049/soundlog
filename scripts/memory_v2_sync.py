#!/usr/bin/env python3
"""Exercise the V2 file-level apply/readback/revoke flow in an ignored sandbox."""
import argparse
import json
import sys
from pathlib import Path

from soundlog_memory.basic_memory_sync import (
    DEFAULT_SIMULATION_ROOT, apply_preview, revoke, verify_applied,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description='仅在项目忽略的 V2 隔离模拟目录运行同步流程')
    sub = parser.add_subparsers(dest='command', required=True)
    apply = sub.add_parser('apply-preview')
    apply.add_argument('--preview', type=Path, required=True)
    apply.add_argument('--simulation-root', type=Path, default=DEFAULT_SIMULATION_ROOT)
    apply.add_argument('--fail-after', type=int, help='仅用于模拟写入中断')
    readback = sub.add_parser('verify-readback')
    readback.add_argument('--preview', type=Path, required=True)
    readback.add_argument('--simulation-root', type=Path, default=DEFAULT_SIMULATION_ROOT)
    undo = sub.add_parser('revoke')
    undo.add_argument('--operation-id', required=True)
    undo.add_argument('--simulation-root', type=Path, default=DEFAULT_SIMULATION_ROOT)
    args = parser.parse_args(argv)
    try:
        if args.command == 'apply-preview':
            result = apply_preview(args.preview, args.simulation_root, args.fail_after)
        elif args.command == 'verify-readback':
            result = verify_applied(args.preview, args.simulation_root)
            if result['readback'] != 'passed':
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 1
        else:
            result = revoke(args.operation_id, args.simulation_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('V2同步模拟失败: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
