#!/usr/bin/env python3
"""Prepare/freeze/score prospective semantic evaluations; never calls a model."""
import argparse
import json
import sys
from pathlib import Path

from soundlog_memory.semantic_gate import freeze_gold, prepare_pack, score_run


ROOT = Path(__file__).resolve().parent.parent
PRIVATE_ROOT = (ROOT / '记忆库/运行/语义验收').resolve()


def private_output(path):
    target = Path(path).resolve()
    if not target.is_relative_to(PRIVATE_ROOT):
        raise ValueError('语义验收内容只能写入Git忽略的记忆库/运行/语义验收/')
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description='录音功能提炼的生成前语义验收工具；不调用模型')
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--scenes', type=Path, default=ROOT / '产出/大模型分析素材/每日场景-v2')
    prepare.add_argument('--prior-results', type=Path, default=ROOT / '产出/功能提炼')
    prepare.add_argument('--selection', type=Path, required=True)
    prepare.add_argument('--output', type=Path, required=True)
    freeze = sub.add_parser('freeze-gold')
    freeze.add_argument('--draft', type=Path, required=True)
    freeze.add_argument('--output', type=Path, required=True)
    score = sub.add_parser('score')
    score.add_argument('--frozen', type=Path, required=True)
    score.add_argument('--review', type=Path, required=True)
    score.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            result = prepare_pack(scenes_root=args.scenes, results_root=args.prior_results,
                                  selection_file=args.selection, output_file=private_output(args.output))
        elif args.command == 'freeze-gold':
            result = freeze_gold(args.draft, private_output(args.output))
        else:
            result = score_run(args.frozen, args.review, private_output(args.output))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('passed', True) else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('语义验收失败: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
