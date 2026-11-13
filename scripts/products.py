#!/usr/bin/env python3
"""Export evidence and import reviewed four-function outputs, offline."""
import argparse
import json
from pathlib import Path
import sys

from soundlog_memory.evidence import read_json
from soundlog_memory.store import write_json
from soundlog_memory.reading import publish_reading, load_verified_result
from soundlog_memory.reconciliation import compare_candidates
from soundlog_memory.workbench import create_only
from soundlog_memory.store import Store
from soundlog_memory.products import export_request, import_result, combine_results, request_progress

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    p = argparse.ArgumentParser(description='日记/纪要/待办/学习笔记的证据导出与结果导入；不自动调用外部模型')
    p.add_argument('--root', type=Path, default=ROOT/'产出/功能提炼')
    sub = p.add_subparsers(dest='command', required=True)
    export = sub.add_parser('export')
    export.add_argument('--scenes', type=Path, default=ROOT/'产出/大模型分析素材/每日场景-v2')
    export.add_argument('--date', action='append')
    export.add_argument('--selection', type=Path, help='可选的局部试用选择文件，包含selections数组')
    export.add_argument('--ranges', type=Path, help='连续时段选择文件，包含timeRanges数组(from/until)')
    export.add_argument('--context-count', type=int, default=2)
    ingest = sub.add_parser('import')
    ingest.add_argument('--file', type=Path, required=True)
    combine = sub.add_parser('combine')
    combine.add_argument('--files', type=Path, nargs='+', required=True)
    combine.add_argument('--output', type=Path, required=True)
    reading=sub.add_parser('reading', help='从已审主题纲要生成可回查阅读版')
    reading.add_argument('--outline',type=Path,required=True)
    compare=sub.add_parser('compare', help='只读对照原子候选与功能事实的证据关联')
    compare.add_argument('--result',required=True)
    compare.add_argument('--memory-root',type=Path,default=ROOT/'记忆库')
    compare.add_argument('--reviews',type=Path)
    compare.add_argument('--output',type=Path,required=True)
    status=sub.add_parser('status')
    status.add_argument('--request',required=True)
    args = p.parse_args(argv)
    try:
        if args.command == 'export':
            result = export_request(args.scenes, args.root, days=args.date,
                selections=read_json(args.selection)['selections'] if args.selection else None,
                time_ranges=read_json(args.ranges)['timeRanges'] if args.ranges else None,
                context_count=args.context_count)
        elif args.command == 'import':
            result = import_result(args.root, read_json(args.file))
        elif args.command == 'compare':
            receipt,facts=load_verified_result(args.root,args.result)
            if not (args.memory_root/'笔记/原子记忆').is_dir():
                raise ValueError('原子记忆目录不存在，不能把路径错误当空库')
            records=[r for r in Store(args.memory_root).records() if r.get('lifecycle')=='active']
            result=compare_candidates(records,facts,read_json(args.reviews)['reviews'] if args.reviews else None)
            result.update(sourceResultId=args.result, sourceRequestId=receipt['requestId'], sourceState=receipt['state'])
            create_only(args.output,result)
            result={k:v for k,v in result.items() if k not in {'rows','functionalFactsWithoutOldEvidence'}}
            result['output']=str(args.output)
        elif args.command == 'reading':
            result = publish_reading(args.root,read_json(args.outline))
        elif args.command == 'status':
            result = request_progress(args.root,args.request)
        else:
            envelope, result = combine_results(args.root, [read_json(p) for p in args.files])
            if args.output.exists() and read_json(args.output) != envelope:
                raise ValueError('合并输出已存在且内容不同，拒绝覆盖')
            write_json(args.output, envelope)
            write_json(args.output.with_suffix('.merge-receipt.json'), result)
            result = {**result, 'output': str(args.output)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get('state') == 'partial' else 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print('功能提炼失败: '+str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
