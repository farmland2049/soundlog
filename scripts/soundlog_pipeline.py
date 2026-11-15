#!/usr/bin/env python3
"""Run one durable step; scheduled agent turns handle semantic work."""
import argparse
import json
from pathlib import Path
from soundlog_memory.pipeline import Pipeline


def main():
    p = argparse.ArgumentParser(description='本地音频全流程管线')
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('tick', help='检测输入、处理音频并准备agent任务；已有任务优先续做')
    sub.add_parser('status')
    ingest = sub.add_parser('ingest'); ingest.add_argument('--file', type=Path, required=True)
    publish = sub.add_parser('publish'); publish.add_argument('--result', required=True); publish.add_argument('--screening', type=Path, required=True)
    publish.add_argument('--adopt', action='store_true', help='显式采用已完成的历史结果建立首个交付基线')
    finish = sub.add_parser('finish'); finish.add_argument('--spec', type=Path, required=True); finish.add_argument('--links', type=Path, required=True)
    a = p.parse_args()
    try:
        pipeline = Pipeline(a.root)
        if a.command == 'tick': result = pipeline.tick()
        elif a.command == 'status': result = pipeline.state()
        elif a.command == 'ingest': result = pipeline.ingest(json.loads(a.file.read_text()))
        elif a.command == 'finish': result = pipeline.finish_products(json.loads(a.spec.read_text()), json.loads(a.links.read_text()))
        else: result = pipeline.publish(a.result, json.loads(a.screening.read_text()), adopt=a.adopt)
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('管线失败: ' + str(exc)); return 2


if __name__ == '__main__':
    raise SystemExit(main())
