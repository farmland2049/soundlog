#!/usr/bin/env python3
"""Prepare the sources for a date and locate evidence without changing notes."""
import argparse
import json
import re
from pathlib import Path

from soundlog_memory.evidence import day_bounds, read_json
from soundlog_memory.scenes import digest_bytes

BEGIN = '<!-- soundlog:combined:start -->'
END = '<!-- soundlog:combined:end -->'


def archive_for_day(root, day):
    day_bounds(day)
    index = root / '产出/每日录音归档'
    row = read_json(index / 'latest.json')['days'].get(day)
    if row is None:
        return None, None
    target = (index / row['path']).resolve()
    if target.parent != index.resolve() / day or digest_bytes(target) != row['sha256']:
        raise ValueError('录音归档路径或哈希与日期索引不符')
    archive = read_json(target)
    if archive['date'] != day:
        raise ValueError('录音归档日期不符')
    return target, archive


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


def prepare(root, notes, work_log, day):
    try:
        path, archive = archive_for_day(root, day)
        audio = {'state': 'available' if archive else 'no_entries'}
    except FileNotFoundError:
        path, archive = None, None
        audio = {'state': 'missing'}
    if archive:
        ranges = sorted((row['start'], row['end']) for row in archive['sources'].values())
        lines = [
            f'# {day} Soundlog 录音证据索引', '', '<!-- soundlog:audio-evidence-index -->', '',
            f'归档状态：已校验。原音 {len(ranges)} 份，逐句原文 {len(archive["utterances"])} 条，环境声事件 {len(archive["acoustics"])} 条。',
            f'归档版本：`{path.stem}`', f'SHA-256：`{digest_bytes(path)}`', '',
            f'[打开本机证据 JSON]({path.as_uri()})', '', '## 录音覆盖区间', '',
            *[f'- {start} 至 {end}' for start, end in ranges], '',
            '区间为录音源的时段，同一文件跨日时保留原始起止。逐句通过证据 ID 定位，原音回听使用对应文件与原偏移。',
            '文字和匿名标签为机器输出。',
        ]
        audio.update(path=str(path), note=f'soundlog/sources/{day}.md', indexMarkdown='\n'.join(lines)+'\n')
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
        if args.evidence:
            _, archive = archive_for_day(args.root, args.date)
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
            if args.notes is None or args.work_log is None:
                parser.error('准备材料需要 --notes 和 --work-log')
            result = prepare(args.root, args.notes, args.work_log, args.date)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f'取证失败：{error}\n')


if __name__ == '__main__':
    main()
