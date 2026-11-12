#!/usr/bin/env python3
"""Soundlog local memory CLI; run --help for the offline-first workflow."""
import argparse
import json
import sys
from pathlib import Path
from soundlog_memory.engine import MemoryEngine
from soundlog_memory.evidence import read_json
from soundlog_memory.protocol import ChatAPI
from soundlog_memory.store import Store
from soundlog_memory.workflow import Workflow

ROOT = Path(__file__).resolve().parent.parent


def parser():
    p = argparse.ArgumentParser(description='本地录音记忆：证据、导入导出、API、审核及检索（无额外依赖）')
    p.add_argument('--store', type=Path, default=ROOT / '记忆库', help='本地记忆库目录')
    p.add_argument('--runs', type=Path, default=ROOT / '产出/运行历史', help='现有运行产物根目录')
    sub = p.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'export', 'extract'):
        s = sub.add_parser(name)
        s.add_argument('--date', required=True)
        if name == 'export':
            s.add_argument('--resolve', action='store_true', help='导出已存候选与旧记忆，进行第二阶段语义比对')
        if name == 'extract':
            s.add_argument('--base-url')
            s.add_argument('--model')
            s.add_argument('--key-env')
            s.add_argument('--timeout', type=float, default=60)
    s = sub.add_parser('import')
    s.add_argument('--file', required=True, type=Path)
    s = sub.add_parser('search')
    s.add_argument('query', nargs='?', default='')
    s.add_argument('--date')
    s.add_argument('--type', dest='kind')
    s.add_argument('--entity')
    s.add_argument('--status', choices=['candidate', 'confirmed'])
    s.add_argument('--include-inactive', action='store_true')
    s = sub.add_parser('review')
    r = s.add_subparsers(dest='review_action', required=True)
    r.add_parser('list')
    for action in ('approve', 'reject'):
        r.add_parser(action).add_argument('id')
    s = sub.add_parser('confirm', help='人工确认一条候选（不代表声纹身份确认）')
    s.add_argument('id')
    s = sub.add_parser('undo')
    s.add_argument('id')
    sub.add_parser('reindex')
    return p


def run(args):
    store = Store(args.store)
    with store.locked():
        flow = Workflow(store, args.runs)
        cmd = args.command
        if cmd == 'prepare':
            package, location = flow.prepare(args.date)
            return {'date': args.date, 'utterances': len(package['utterances']), 'acoustics': len(package['acoustics']),
                    'fingerprint': package['fingerprint'], 'directory': str(location)}
        if cmd == 'export':
            req, location = flow.request(args.date, args.resolve)
            return {'requestId': req['requestId'], 'phase': req['phase'], 'chunks': len(req['items']),
                    'directory': str(location), 'shareOnly': ['materials.json', 'instructions.md', 'result-template.json']}
        if cmd == 'extract':
            adapter = ChatAPI(args.base_url, args.model, args.key_env, args.timeout)
            return flow.extract(args.date, adapter)
        if cmd == 'import':
            return flow.import_result(read_json(args.file))
        if cmd == 'search':
            return store.search(args.query, args.date, args.kind, args.entity, args.status, args.include_inactive)
        if cmd == 'review':
            if args.review_action == 'list':
                return [read_json(p) for p in sorted((store.root / '审核').glob('*.json')) if read_json(p)['state'] == 'pending']
            op = MemoryEngine(store).review(args.id, args.review_action == 'approve')
            store.reindex()
            return {'operationId': op}
        if cmd == 'confirm':
            op = MemoryEngine(store).confirm(args.id)
            store.reindex()
            return {'operationId': op}
        if cmd == 'undo':
            op = store.undo(args.id)
            store.reindex()
            return {'operationId': op}
        return {'indexed': store.reindex()}


def main():
    args = parser().parse_args()
    try:
        result = run(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if isinstance(result, dict) and result.get('state') == 'partial':
            return 1
        return 0
    except (ValueError, OSError, KeyError, TypeError, NotImplementedError) as exc:
        print('soundlog memory: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
