#!/usr/bin/env python3
"""Prepare next review packet or compile explicitly reviewed row decisions."""
import argparse
import json
import sys
from pathlib import Path
from soundlog_memory.evidence import read_json
from soundlog_memory.workbench import prepare, compile_review, create_only
ROOT=Path(__file__).resolve().parent.parent

def main():
    p=argparse.ArgumentParser(description='逐句审阅工作包；不调用模型、不自动标记完成')
    p.add_argument('--root',type=Path,default=ROOT/'产出/功能提炼')
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('prepare');a.add_argument('--request',required=True);a.add_argument('--count',type=int,default=10)
    a.add_argument('--completed',type=Path);a.add_argument('--order-from',type=Path)
    a.add_argument('--output',required=True,type=Path)
    b=sub.add_parser('compile');b.add_argument('--decisions',required=True,type=Path);b.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    try:
        if args.command=='prepare':
            out=prepare(args.root,args.request,args.output,count=args.count,
                        completed=read_json(args.completed) if args.completed else None,
                        order_from=read_json(args.order_from) if args.order_from else None)
        else:
            envelope=compile_review(args.root,read_json(args.decisions));create_only(args.output,envelope)
            out={'output':str(args.output),'reviewedBlocks':len(envelope['results']),'imported':False}
        print(json.dumps(out,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,TypeError,KeyError) as exc:
        print('审阅工作包失败: '+str(exc),file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
