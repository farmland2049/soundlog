"""Canonical daily evidence and published reading notes in Basic Memory."""
import hashlib
import os
import re
from pathlib import Path

from .evidence import day_bounds, digest, read_json
from .scenes import digest_bytes
from .store import atomic, write_json

NOTES_PATH = Path('05-日常工具/BasicMemory/笔记')


def notes_root(root, configured=None):
    configured = configured or os.environ.get('SOUNDLOG_BASIC_MEMORY_NOTES')
    if configured:
        notes = Path(configured).expanduser().resolve()
        if not notes.is_dir():
            raise ValueError('Basic Memory 笔记目录不存在')
        return notes
    return next((parent / NOTES_PATH for parent in Path(root).parents
                 if (parent / NOTES_PATH).is_dir()), None)


def note_path(notes, section, day, suffix):
    day_bounds(day)
    path = notes.resolve() / 'soundlog' / section / (day + suffix)
    if path.resolve() != path:
        raise ValueError('Basic Memory 日归档路径包含符号链接')
    return path


def sync_sources(notes, local, days):
    updated = []
    for day, row in days.items():
        path = local / row['path']
        if path.resolve().parent != local.resolve() / day or digest_bytes(path) != row['sha256']:
            raise ValueError(f'{day} 本机录音归档校验失败')
        package = read_json(path)
        if package['date'] != day:
            raise ValueError('录音归档日期不符')
        targets = {sha: {k: source[k] for k in ('sourceSHA256', 'audio', 'start', 'end')}
                   for sha, source in package['sources'].items()}
        payload = {'schemaVersion': 1, 'date': day, 'sources': targets,
                   'utterances': package['utterances'], 'acoustics': package['acoustics']}
        fingerprint = digest(payload)
        dest = note_path(notes, 'sources', day, '.json')
        record = {'fingerprint': fingerprint, **payload}
        if not dest.exists() or read_sources(notes, day)[1] != record:
            write_json(dest, record)
            if read_sources(notes, day)[1] != record:
                raise ValueError(f'{day} Basic Memory 录音素材读回失败')
            updated.append(day)
        index = note_path(notes, 'sources', day, '.md')
        if not index.exists():
            with index.open('x', encoding='utf-8') as handle:
                handle.write(f'# {day} Soundlog 录音素材\n\n'
                             f'[逐句转写与声音证据]({day}.json)\n')
    return updated


def read_sources(notes, day):
    path = note_path(notes, 'sources', day, '.json')
    record = read_json(path)
    payload = {k: v for k, v in record.items() if k != 'fingerprint'}
    if record['date'] != day or record['schemaVersion'] != 1 or digest(payload) != record['fingerprint']:
        raise ValueError(f'{day} Basic Memory 录音素材哈希或日期不符')
    return path, record


def publish_note(notes, delivery, bundle, day, categories):
    from .workbench_view import artifact

    review = artifact(delivery, f'{bundle}/{day}/daily-review.json')
    if review.get('mode') != 'agent_overview':
        return None
    folder = delivery / bundle / day
    lines = [f'# {day} 每日经历', '', '## 每日复盘', '', review['overview'].strip(), '',
             '## 经历时间线', '']
    timeline = artifact(delivery, f'{bundle}/{day}/timeline.json')
    for item in timeline['rows']:
        evidence = '、'.join(f'`{value}`' for value in item['evidenceIds'])
        lines.append(f"- {item['recordedStart'][11:16]} · {item['summary']}（{evidence}）")
    for key, title in categories.items():
        body = artifact(delivery, f'{bundle}/{day}/{key}.md').split('\n', 2)[2]
        if key == 'journal' and '## 录音记录\n' in body:
            body = body.split('## 录音记录\n', 1)[1]
        body = re.sub(r'^## (\d{4}-)', r'### \1', body, flags=re.M)
        body = re.sub(r'\[原文定位\]\(sources\.md#([^)]*)\)',
                      lambda match: f'[录音来源](../sources/{day}.json) · `{match[1]}`',
                      body)
        lines.extend(['', '## ' + title, '', body.strip()])
    lines.extend(['', f"[Soundlog 原文与交付索引]({(folder / 'README.md').as_uri()})", ''])
    content = '\n'.join(lines)
    signature = hashlib.sha256(content.encode()).hexdigest()
    rendered = (f'---\ntitle: "{day} 每日经历"\ntype: soundlog_daily_record\n'
                f'permalink: soundlog/daily/{day}\n---\n\n'
                f'<!-- soundlog:daily:{signature} -->\n' + content)
    path = note_path(notes, 'daily', day, '.md')
    if path.exists():
        old = path.read_text(encoding='utf-8')
        if old == rendered:
            return path
        if old.startswith('---\n'):
            _, boundary, old = old[4:].partition('\n---\n')
            if not boundary:
                raise ValueError(f'{day} 每日正文元数据不完整')
            old = old.lstrip('\n')
        header, _, body = old.partition('\n')
        normalized = body.rstrip('\n') + '\n'
        if header != f'<!-- soundlog:daily:{hashlib.sha256(normalized.encode()).hexdigest()} -->':
            raise ValueError(f'{day} 每日正文已有人工维护内容')
    atomic(path, rendered)
    if path.read_text(encoding='utf-8') != rendered:
        raise ValueError(f'{day} Basic Memory 每日正文读回失败')
    return path
