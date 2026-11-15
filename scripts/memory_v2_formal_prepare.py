#!/usr/bin/env python3
"""Build a read-only formal pilot manifest; this command cannot write the target."""
import argparse
import json
from pathlib import Path
import sys

from soundlog_memory.formal_sync import prepare
from soundlog_memory.workbench import create_only
from soundlog_memory.evidence import digest, read_json
from soundlog_memory.store import Store
from soundlog_memory.scenes import digest_bytes

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = (ROOT / '记忆库/运行').resolve()
TARGET = ROOT.parent.parent / '05-日常工具/BasicMemory/笔记'


def validate_live_state(preview):
    selected = read_json(ROOT / '产出/2026-11-14-七天验收/current-results.json')
    manifest = read_json(preview / 'manifest.json')
    mapping = read_json(preview / 'mapping.json')
    if (len(selected.get('results', [])) != 1
            or selected['results'][0]['resultId'] != manifest['sourceArtifacts'][0]['resultId']
            or selected['sourceSnapshotId'] != manifest['sourceSnapshotId']):
        raise ValueError('当前选择与预览不一致')
    result_id = selected['results'][0]['resultId']
    if digest_bytes(ROOT / '产出/功能提炼/results' / result_id / 'receipt.json') != manifest['sourceArtifacts'][0]['receiptSHA256']:
        raise ValueError('当前结果回执已变化')
    if digest(Store(ROOT / '记忆库').records()) != mapping['legacyHandling']['snapshotSHA256']:
        raise ValueError('旧候选库已变化，需要重新生成预览')


def main():
    p = argparse.ArgumentParser(description='准备两日正式试点的只读哈希清单，不执行写入')
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--preview', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    try:
        # Plan may live in the project-private output tree; preview and output
        # remain under ignored runtime storage, away from the real target.
        if not args.plan.resolve().is_relative_to((ROOT / '产出').resolve()):
            raise ValueError('输入计划必须位于项目私有产出目录')
        if not args.preview.resolve().is_relative_to(PRIVATE) or not args.output.resolve().is_relative_to(PRIVATE):
            raise ValueError('预览和输出必须位于项目私有运行目录')
        validate_live_state(args.preview)
        result = prepare(args.plan, args.preview, TARGET)
        create_only(args.output, result)
        print(json.dumps({'state': result['state'], 'count': len(result['files']),
                          'embed': result['embed'], 'output': str(args.output)}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('准备失败: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
