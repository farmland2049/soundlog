#!/usr/bin/env python3
"""Generate immutable v2 daily dossiers from existing local artifacts."""
import argparse
import json
from pathlib import Path
import sys

from soundlog_memory.scenes import build_snapshot

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / '产出/大模型分析素材/每日场景-v2'
RUNS_DIR = ROOT / '产出/运行历史'


def main(argv=None):
    p = argparse.ArgumentParser(description='本地逐句证据与候选片段生成；保留旧版素材，不处理音频')
    p.add_argument('--runs', type=Path, default=RUNS_DIR)
    p.add_argument('--output-dir', type=Path, default=OUTPUT_DIR)
    p.add_argument('--date', action='append', help='可重复指定；默认全部有证据日期')
    p.add_argument('--gap-seconds', type=float, default=90)
    p.add_argument('--legacy-dir', type=Path, default=ROOT / '产出/大模型分析素材/每日场景')
    args = p.parse_args(argv)
    try:
        result = build_snapshot(args.runs, args.output_dir, days=args.date,
                                gap_seconds=args.gap_seconds, legacy_dir=args.legacy_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['state'] == 'completed' else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('场景素材生成失败: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
