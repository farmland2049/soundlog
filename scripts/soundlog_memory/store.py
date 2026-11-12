"""Markdown authority, rebuildable SQLite index, recoverable file transactions."""
import fcntl
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .evidence import canonical, digest, read_json


def now():
    return datetime.now(timezone.utc).isoformat()


def normalize(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.writing-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, obj):
    atomic(path, json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n')


def note_text(record):
    meta = {k: v for k, v in record.items() if k != 'content'}
    lines = ['---', 'title: ' + json.dumps(record['id']), 'type: memory',
             'permalink: soundlog/memories/' + record['id'], 'soundlog: ' + canonical(meta), '---', '',
             '# ' + record['id'], '', '机器候选；确认状态：' + record['status'] + '。', '', '## Observations', '',
             '- [' + record['type'] + '] ' + record['content'].replace('\n', ' '), '', '## Evidence', '']
    for ref in record['evidence']:
        lines.extend(['- ' + ref['id'] + ' · ' + ref['start'] + ' · ' + ref['sourceFile'],
                      '  > ' + ref['quote'].replace('\n', '\n  > ')])
    lines.extend(['', '## Relations', ''])
    for entity in record.get('entities', []):
        lines.append('- mentions [[soundlog/entities/' + digest(entity)[:24] + ']]')
    for relation in ('supersedes', 'supersededBy'):
        if record.get(relation):
            lines.append('- ' + relation + ' [[soundlog/memories/' + record[relation] + ']]')
    for target in record.get('possibleConflicts', []):
        lines.append('- possibly_conflicts_with [[soundlog/memories/' + target + ']]')
    return '\n'.join(lines) + '\n'


def parse_note(text):
    metadata = re.search(r'^soundlog: (.+)$', text, re.M)
    if not metadata:
        raise ValueError('记忆 Markdown 缺少 soundlog 元数据')
    record = json.loads(metadata.group(1))
    match = re.search(r'^- \[' + re.escape(record['type']) + r'\] (.*)$', text, re.M)
    if not match:
        raise ValueError('记忆 Markdown 缺少原子 Observation')
    record['content'] = match.group(1)
    return record


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def init(self):
        for name in ['证据', '笔记/原子记忆', '笔记/日记录', '笔记/实体', '审核', '运行/事务', '索引']:
            (self.root / name).mkdir(parents=True, exist_ok=True)

    @contextmanager
    def locked(self):
        self.init()
        with (self.root / '运行/.lock').open('a') as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('记忆库正在被另一个进程使用') from None
            self.recover()
            yield self

    def path(self, relative):
        p = (self.root / relative).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError('越界路径')
        return p

    def records(self):
        return [parse_note(p.read_text(encoding='utf-8')) for p in sorted((self.root / '笔记/原子记忆').glob('*.md'))]

    def record_path(self, mid):
        if not re.fullmatch(r'mem-[a-f0-9]{24}', mid):
            raise ValueError('无效记忆编号')
        return self.path('笔记/原子记忆/' + mid + '.md')

    def get(self, mid):
        return parse_note(self.record_path(mid).read_text(encoding='utf-8'))

    def recover(self):
        for path in sorted((self.root / '运行/事务').glob('*.json')):
            tx = read_json(path)
            if tx['state'] == 'pending':
                self._restore(tx['before'])
                tx['state'] = 'recovered_rollback'
                write_json(path, tx)

    def _restore(self, files):
        for relative, text in files.items():
            path = self.path(relative)
            if text is None:
                path.unlink(missing_ok=True)
            else:
                atomic(path, text)

    def transaction(self, files, action, extra=None):
        """Write-ahead before images; pending transactions roll back on next open."""
        op = 'op-' + uuid.uuid4().hex
        before = {p: self.path(p).read_text(encoding='utf-8') if self.path(p).exists() else None for p in files}
        tx = {'id': op, 'state': 'pending', 'action': action, 'at': now(),
              'before': before, 'after': files, 'extra': extra or {}}
        journal = self.root / '运行/事务' / (op + '.json')
        write_json(journal, tx)
        try:
            self._restore(files)
            tx['state'] = 'committed'
            write_json(journal, tx)
        except BaseException:
            self._restore(before)
            tx['state'] = 'rolled_back'
            write_json(journal, tx)
            raise
        return op

    def undo(self, operation):
        if not re.fullmatch(r'op-[a-f0-9]{32}', operation):
            raise ValueError('操作编号无效')
        tx = read_json(self.root / '运行/事务' / (operation + '.json'))
        if tx['state'] != 'committed' or tx['action'].startswith('undo'):
            raise ValueError('操作不能撤销')
        for rel, expected in tx['after'].items():
            actual = self.path(rel).read_text(encoding='utf-8') if self.path(rel).exists() else None
            if actual != expected:
                raise ValueError('后续修改或人工编辑已改变内容，请先撤销后续操作')
        restore = dict(tx['before'])
        for rel, text in tx['after'].items():
            if rel.startswith('运行/已处理/') and text is not None:
                receipt = json.loads(text)
                receipt['undone'] = True
                restore[rel] = canonical(receipt) + '\n'
        return self.transaction(restore, 'undo:' + operation)

    def reindex(self):
        self.init()
        records = self.records()
        target = self.root / '索引/memory.sqlite3'
        fd, temp = tempfile.mkstemp(dir=target.parent, suffix='.sqlite3')
        os.close(fd)
        try:
            with sqlite3.connect(temp) as conn:
                conn.execute('CREATE TABLE memories (id TEXT PRIMARY KEY, day TEXT, kind TEXT, status TEXT, lifecycle TEXT, content TEXT, entities TEXT, normalized TEXT)')
                conn.execute('CREATE TABLE relations (source TEXT, relation TEXT, target TEXT)')
                for r in records:
                    conn.execute('INSERT INTO memories VALUES (?,?,?,?,?,?,?,?)',
                                 (r['id'], r['date'], r['type'], r['status'], r['lifecycle'], r['content'],
                                  canonical(r.get('entities', [])), normalize(r['content'])))
                    for relation in ('supersedes', 'supersededBy'):
                        if r.get(relation):
                            conn.execute('INSERT INTO relations VALUES (?,?,?)', (r['id'], relation, r[relation]))
                    for entity in r.get('entities', []):
                        conn.execute('INSERT INTO relations VALUES (?,?,?)', (r['id'], 'mentions', entity))
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        self.render_views(records)
        return len(records)

    def render_views(self, records):
        days, entities = {}, {}
        for r in records:
            days.setdefault(r['date'], []).append(r)
            for e in r.get('entities', []):
                entities.setdefault(e, []).append(r)
        expected = set()
        for folder, groups in [('日记录', days), ('实体', entities)]:
            for label, items in groups.items():
                slug = label if folder == '日记录' else digest(label)[:24]
                path = self.root / '笔记' / folder / (slug + '.md')
                expected.add(path)
                permalink = 'soundlog/days/' + slug if folder == '日记录' else 'soundlog/entities/' + slug
                lines = ['---', 'title: ' + json.dumps(label, ensure_ascii=False), 'type: ' + ('DailyLog' if folder == '日记录' else 'entity'),
                         'permalink: ' + permalink, '---', '', '# ' + label, '',
                         '由原子记忆生成的索引；人物提及不代表声音身份确认。', '', '## Relations', '']
                lines += ['- contains [[soundlog/memories/' + r['id'] + ']] · ' + r['status'] + '/' + r['lifecycle'] for r in items]
                atomic(path, '\n'.join(lines) + '\n')
        for folder in ['日记录', '实体']:
            for path in (self.root / '笔记' / folder).glob('*.md'):
                if path not in expected:
                    path.unlink()

    def search(self, query='', day=None, kind=None, entity=None, status=None, include_inactive=False):
        # Always rebuild from Markdown so direct Observation edits are respected.
        self.reindex()
        with sqlite3.connect(self.root / '索引/memory.sqlite3') as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute('SELECT * FROM memories ORDER BY day,id')]
        tokens = normalize(query).split()
        matched = [r for r in rows if all(t in r['normalized'] for t in tokens)
                and (not day or r['day'] == day) and (not kind or r['kind'] == kind)
                and (not entity or entity in json.loads(r['entities']))
                and (not status or r['status'] == status)
                and (include_inactive or r['lifecycle'] == 'active')]
        for r in matched:
            r['entities'] = json.loads(r['entities'])
            r.pop('normalized')
            r['path'] = str(self.record_path(r['id']))
            r['evidence'] = self.get(r['id'])['evidence']
        return matched

    def similar(self, candidate, limit=5):
        text = normalize(candidate['content'])
        grams = {text[i:i+2] for i in range(max(1, len(text)-1))}
        ranked = []
        for r in self.records():
            if r['lifecycle'] != 'active':
                continue
            old = normalize(r['content'])
            other = {old[i:i+2] for i in range(max(1, len(old)-1))}
            score = len(grams & other) / max(1, len(grams | other))
            score += .25 * bool(set(candidate.get('entities', [])) & set(r.get('entities', [])))
            if score > .05:
                ranked.append((score, r))
        return [r for _, r in sorted(ranked, key=lambda v: (-v[0], v[1]['id']))[:limit]]
