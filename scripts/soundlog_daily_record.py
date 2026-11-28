#!/usr/bin/env python3
"""Prepare the sources for a date and locate evidence without changing notes."""
import argparse
import json
import re
from pathlib import Path

from soundlog_memory.basic_memory_daily import read_sources, notes_root
from soundlog_memory.evidence import day_bounds

BEGIN = '<!-- soundlog:combined:start -->'
END = '<!-- soundlog:combined:end -->'


def work_section(text, day):
    short = day[5:].replace('-', '')
    matches = list(re.finditer(r'^[ \t]*(?:#{1,6}[ \t]+)?(\d{4}-\d{2}-\d{2}|\d{4})[ \t]*$', text, re.M))
    pieces = []
    for index, match in enumerate(matches):
        if match[1] not in (day, short):
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        pieces.append(text[match.end():end].strip())
    return '\n\n'.join(pieces)


def source(path, transform=None):
    try:
        content = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return {'path': str(path), 'state': 'missing'}
    except (OSError, UnicodeError):
        return {'path': str(path), 'state': 'unreadable'}
    if transform:
        content = transform(content)
    return {'path': str(path), 'state': 'available' if content.strip() else 'no_entries',
            'content': content}


def prepare(notes, work_log, day):
    try:
        path, archive = read_sources(notes, day)
        audio = {'state': 'available', 'path': str(path), 'fingerprint': archive['fingerprint'],
                 'utterances': len(archive['utterances']), 'acoustics': len(archive['acoustics'])}
    except FileNotFoundError:
        audio = {'state': 'no_entries'}

    def strip_generated(body):
        pattern = r'^## 综合记录[ \t]*\r?\n(?:[ \t]*\r?\n)*' + re.escape(BEGIN)
        return re.sub(pattern + '.*?' + re.escape(END), '', body, flags=re.M | re.S).rstrip() + '\n'
    month = work_log / (day[:7].replace('-', '') + '.md')
    events = notes / '长期记忆/事件'
    return {'date': day, 'audio': audio,
            'dailySummary': source(notes / '日常摘要' / (day + '.md'), strip_generated),
            'workLedger': source(notes / '工作日结' / (day + '.md')),
            'events': [source(event) for event in sorted(events.glob(f'{day}*.md'))],
            'workLog': source(month, lambda body: work_section(body, day))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--date', required=True)
    parser.add_argument('--notes', type=Path)
    parser.add_argument('--work-log', type=Path)
    parser.add_argument('--evidence', help='定位逐句证据 ID、原音与偏移')
    args = parser.parse_args()
    try:
        day_bounds(args.date)
        notes = notes_root(args.root.resolve(), args.notes)
        if notes is None:
            parser.error('请指定 Basic Memory 笔记目录')
        if args.evidence:
            _, archive = read_sources(notes, args.date)
            if not archive:
                raise ValueError('日期没有录音归档')
            row = next((item for item in archive['utterances'] if item['id'] == args.evidence), None)
            if row is None:
                raise ValueError('该日期没有此逐句证据')
            original = archive['sources'][row['sourceSHA256']]['audio']
            if not Path(original).is_file():
                raise ValueError('归档音频无法读取')
            result = {**row, 'audio': original}
        else:
            if args.work_log is None:
                parser.error('准备材料需要 --work-log')
            result = prepare(notes, args.work_log, args.date)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f'取证失败：{error}\n')


if __name__ == '__main__':
    main()
