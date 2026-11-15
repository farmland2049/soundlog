#!/usr/bin/env python3
"""Local entry point for the selected recording results."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from soundlog_memory.reading import load_verified_result
from soundlog_memory.scenes import digest_bytes

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS = ROOT / '产出/功能提炼'
SCENES = ROOT / '产出/大模型分析素材/每日场景-v2'
SELECTION = ROOT / '产出/2026-11-14-七天验收/current-results.json'
FUNCTIONS = ('journal', 'minutes', 'actions', 'learning')


def selected():
    data = json.loads(SELECTION.read_text(encoding='utf-8'))
    rows = data.get('results', [])
    if len(rows) != 1:
        raise ValueError('当前入口需要恰好一个已选择的完整结果')
    row = rows[0]
    receipt, facts = load_verified_result(PRODUCTS, row['resultId'])
    if receipt['state'] != 'completed' or receipt['sourceSnapshotId'] != data['sourceSnapshotId']:
        raise ValueError('结果未完成或与选择清单的快照不一致')
    return row, receipt, facts


def selected_snapshot(receipt):
    """Use the chosen result's snapshot, even after a newer one becomes latest."""
    name = Path(receipt['sourceSnapshot']).name
    if not name.startswith('snapshot-'):
        raise ValueError('结果来源快照路径无效')
    snapshot = (SCENES / name).resolve()
    if snapshot.parent != SCENES.resolve():
        raise ValueError('结果来源快照路径越界')
    source = json.loads((snapshot / 'receipt.json').read_text(encoding='utf-8'))
    if source.get('snapshotId') != receipt['sourceSnapshotId'] or source.get('state') != 'completed':
        raise ValueError('结果来源快照不匹配或未完成')
    return snapshot


def main():
    p = argparse.ArgumentParser(description='查看本机录音处理与已选择的功能结果')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('status', help='查看待处理文件和当前结果进度')
    view = sub.add_parser('view', help='显示某天某类阅读版路径')
    view.add_argument('date'); view.add_argument('function', choices=FUNCTIONS)
    search = sub.add_parser('search', help='并列检索原文和功能候选')
    search.add_argument('query'); search.add_argument('--date'); search.add_argument('--function', choices=FUNCTIONS)
    sub.add_parser('inbox', help='检查待处理音频，不执行处理')
    sub.add_parser('process', help='处理待处理录音；成功后原文件会移入已归档目录')
    args = p.parse_args()
    try:
        if args.command in ('inbox', 'process'):
            cmd = ['bash', str(ROOT / 'scripts/process-inbox.sh')]
            if args.command == 'inbox': cmd.append('--dry-run')
            return subprocess.call(cmd, cwd=ROOT)
        row, receipt, facts = selected()
        if args.command == 'status':
            inbox = ROOT / '录音/待处理'
            audio = sorted(p.name for p in inbox.iterdir() if p.is_file() and p.suffix.lower() in {'.mp3','.wav','.m4a','.aac','.flac'}) if inbox.exists() else []
            print(json.dumps({'待处理音频数':len(audio), '待处理文件':audio, '结果':row['resultId'], '阅读版':row['readingId'], '日期':row['dates'], '已处理块':receipt['processedChunks'], '总块数':receipt['totalChunks'], '候选数':len(facts), '语义状态':receipt.get('semanticAssessment'), '边界':'候选未确认；机器稿未听音校订'}, ensure_ascii=False, indent=2))
        elif args.command == 'view':
            if args.date not in row['dates']:
                raise ValueError('日期不在当前选择中')
            path = PRODUCTS / 'reading' / row['readingId'] / (args.date + '_' + args.function + '.md')
            reading_receipt = json.loads((path.parent / 'receipt.json').read_text(encoding='utf-8'))
            if (reading_receipt.get('readingId') != row['readingId'] or
                    reading_receipt.get('sourceResultId') != row['resultId'] or
                    not path.is_file() or digest_bytes(path) != reading_receipt.get('artifacts', {}).get(path.name)):
                raise ValueError('阅读版与当前结果不一致或文件已改变')
            print(path)
        else:
            cmd = [sys.executable, str(ROOT / 'scripts/search_soundlog.py'), args.query, '--result', row['resultId'], '--scenes', str(selected_snapshot(receipt))]
            if args.date: cmd += ['--date', args.date]
            if args.function: cmd += ['--function', args.function]
            return subprocess.call(cmd, cwd=ROOT)
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print('soundlog: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
