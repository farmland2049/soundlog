"""Prepare a daily archive draft and track verified Basic Memory receipts."""

import json
from pathlib import Path
import re

from . import workbench_view
from .scenes import digest_bytes
from .store import atomic, write_json


def _home(pipeline):
    return pipeline.root/'记忆库/运行/产品功能/日常归档'


def _draft_path(date, bundle):
    return f'daily-archive/{date}/{bundle}/draft.md'


def remember_verified(pipeline, receipt):
    if receipt.get('state') != 'verified':
        raise ValueError('归档必须先通过 Basic Memory 读回')
    index = _home(pipeline)/'confirmed.json'
    confirmed = json.loads(index.read_text()) if index.exists() else {}
    updated = False
    for row in receipt['operations']:
        match = re.fullmatch(r'soundlog/exchange/soundlog-(\d{4})(\d{2})(\d{2})-daily-review\.md', row['path'])
        if not match:
            continue
        date = '-'.join(match.groups())
        path = Path(receipt['targetRoot'])/row['path']
        if not path.is_file() or digest_bytes(path) != row['sha256']:
            raise ValueError(f'{date} 已确认的归档文件发生变化')
        source = re.search(r'/自动交付/(bundle-[a-f0-9]{24})/'+date+r'/daily-review\.md', path.read_text())
        if source:
            confirmed[date] = {'bundle': source[1], 'path': str(path), 'sha256': row['sha256']}
            updated = True
    if updated:
        write_json(index, confirmed)


def confirm_note(pipeline, day, bundle, path):
    index = _home(pipeline) / 'confirmed.json'
    confirmed = json.loads(index.read_text()) if index.exists() else {}
    entry = {'bundle': bundle, 'path': str(path), 'sha256': digest_bytes(path)}
    if confirmed.get(day) != entry:
        confirmed[day] = entry
        write_json(index, confirmed)


def prepare(pipeline, days):
    """Stage reviewable drafts after publication. Archive failures remain separate."""
    for date, bundle in days.items():
        state_path = _home(pipeline)/f'{date}.json'
        state = {'bundle': bundle}
        try:
            review = workbench_view.artifact(pipeline.delivery, f'{bundle}/{date}/daily-review.json')
            if review.get('mode') != 'agent_overview' or not (review.get('overview') or '').strip():
                raise ValueError('缺少已审阅的每日复盘')
            source = pipeline.delivery/bundle/date/'daily-review.md'
            workbench_view.artifact(pipeline.delivery, f'{bundle}/{date}/daily-review.md')
            draft = pipeline.delivery/_draft_path(date, bundle)
            if not draft.exists():
                published = workbench_view.artifact(pipeline.delivery, f'{bundle}/search.json')
                facts = {fact['id']: fact for fact in published['facts'] if fact['date'] == date}
                evidence_page = source.with_name('sources.md')
                lines = [f'# {date} 日常归档草稿', '',
                         '从已交付的每日复盘摘出概括和待筛选重点。正式归档前需保留适合长期保存的内容及其原话依据。',
                         '', review['overview'], '', '## 待筛选重点', '']
                for identifier in review['highlights']:
                    fact = facts[identifier]
                    e = fact['evidence'][0]
                    lines.append(f'- {fact["summary"]} [{e["start"][11:19]} 原话](<{evidence_page}#{e["id"]}>)')
                lines.extend(['', f'[Soundlog 当日完整复盘](<{source}>)', ''])
                atomic(draft, '\n'.join(lines))
            state.update(state='draft_ready', draft=_draft_path(date, bundle))
        except (OSError, ValueError, KeyError, TypeError):
            state.update(state='draft_error')
        write_json(state_path, state)


def statuses(pipeline, days):
    home = _home(pipeline)
    index = home/'confirmed.json'
    try:
        confirmed = json.loads(index.read_text()) if index.exists() else {}
    except (OSError, ValueError):
        return {date: {'state': 'verification_failed'} for date in days}
    result = {}
    for date, bundle in days.items():
        prior = confirmed.get(date)
        path = home/f'{date}.json'
        try:
            draft = json.loads(path.read_text()) if path.exists() else {}
        except (OSError, ValueError):
            draft = {'bundle': bundle, 'state': 'draft_error'}
        status = {'state': 'pending'}
        if draft.get('bundle') == bundle:
            status = {key: draft[key] for key in ('state', 'draft') if key in draft}
            if status.get('state') == 'draft_ready' and not (pipeline.delivery/_draft_path(date, bundle)).is_file():
                status = {'state': 'draft_error'}
        if prior:
            note = Path(prior['path'])
            try:
                valid = not note.is_symlink() and note.is_file() and digest_bytes(note) == prior['sha256']
            except OSError:
                valid = False
            if valid:
                status['state'] = 'archived' if prior['bundle'] == bundle else 'needs_update'
            else:
                status['state'] = 'verification_failed'
        result[date] = status
    return result
