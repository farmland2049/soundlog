#!/usr/bin/env python3
"""Process local audio or manage an existing semantic job."""
import argparse
import json
from pathlib import Path
from soundlog_memory.pipeline import Pipeline


def main():
    p = argparse.ArgumentParser(description='本地音频全流程管线')
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    p.add_argument('--notes', type=Path, help='Basic Memory 正式笔记目录')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('start', help='执行本机音频处理并按天归档')
    sub.add_parser('tick', help='与 start 相同')
    sub.add_parser('status', help='查看音频归档状态和旧语义任务状态')
    sub.add_parser('archive', help='从现有运行产物重建每日录音归档')
    analysis = sub.add_parser('prepare-analysis', help='从 Basic Memory 当日素材发起语义分析')
    analysis.add_argument('--date', required=True)
    analysis.add_argument('--work-log', type=Path, help='工作管理的工作日志目录')
    analysis.add_argument('--refresh', action='store_true', help='文字来源更新时重新分析')
    archive_delivery = sub.add_parser('archive-delivery', help='归档已发布的每日正文')
    archive_delivery.add_argument('--date', required=True)
    ingest = sub.add_parser('ingest'); ingest.add_argument('--file', type=Path, required=True)
    publish = sub.add_parser('publish'); publish.add_argument('--result', required=True); publish.add_argument('--screening', type=Path, required=True)
    publish.add_argument('--adopt', action='store_true', help='显式采用已完成的历史结果建立首个交付基线')
    finish = sub.add_parser('finish'); finish.add_argument('--spec', type=Path, required=True); finish.add_argument('--links', type=Path, required=True)
    a = p.parse_args()
    try:
        pipeline = Pipeline(a.root, notes=a.notes)
        if a.command in ('start', 'tick'): result = pipeline.start()
        elif a.command == 'status': result = {'audio': pipeline.audio_state(), 'legacySemantic': pipeline.state()}
        elif a.command == 'archive':
            with pipeline.lock():
                result = pipeline.archive_audio()
        elif a.command == 'prepare-analysis':
            from soundlog_daily_record import prepare
            work_log = a.work_log
            if work_log is None:
                matches = list(Path.home().glob('Library/CloudStorage/坚果云-*/工作管理/工作日志'))
                if len(matches) != 1:
                    p.error('请用 --work-log 指定工作日志目录')
                work_log = matches[0]
            if pipeline.notes is None:
                p.error('请指定 Basic Memory 笔记目录')
            sources = prepare(pipeline.notes, work_log.resolve(), a.date)
            result = pipeline.prepare_analysis(a.date, sources, refresh=a.refresh)
        elif a.command == 'archive-delivery':
            with pipeline.lock():
                result = {'path': pipeline.archive_delivery(a.date)}
        elif a.command == 'ingest': result = pipeline.ingest(json.loads(a.file.read_text()))
        elif a.command == 'finish': result = pipeline.finish_products(json.loads(a.spec.read_text()), json.loads(a.links.read_text()))
        else: result = pipeline.publish(a.result, json.loads(a.screening.read_text()), adopt=a.adopt)
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('管线失败: ' + str(exc)); return 2


if __name__ == '__main__':
    raise SystemExit(main())
