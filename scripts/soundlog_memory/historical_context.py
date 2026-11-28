"""Retrieve dated evidence for an agent's review of a specific daily topic."""
import re
from pathlib import Path

from .basic_memory_daily import read_sources
from .evidence import day_bounds, digest, read_json
from .store import write_json

DATE = re.compile(r'^(\d{4}-\d{2}-\d{2})(?:$|[-_])')
WORK_DAY = re.compile(r'^[ \t]*(?:#{1,6}[ \t]+)?(\d{4}-\d{2}-\d{2}|\d{4})[ \t]*$', re.M)


def search(notes, work_log, day, terms, *, limit=24):
    day_bounds(day)
    terms = sorted({term.strip().casefold() for term in terms if term.strip()})
    if not terms or not 1 <= limit <= 100:
        raise ValueError('历史核对需要检索词，返回条数须在 1 到 100 之间')
    hits = []
    unavailable = []

    def add(kind, when, path, text, locator):
        matched = [term for term in terms if term in text.casefold()]
        if matched:
            item = {'kind': kind, 'date': when, 'path': str(path), 'locator': locator,
                    'text': text, 'matchedTerms': matched}
            hits.append({'id': 'hist-' + digest(item)[:24], **item})

    for path in sorted((notes / 'soundlog/sources').glob('????-??-??.json')):
        when = path.stem
        if when >= day:
            continue
        try:
            _, archive = read_sources(notes, when)
        except (OSError, KeyError, TypeError, ValueError):
            unavailable.append(str(path))
            continue
        for row in archive['utterances']:
            add('recording', when, path, row['text'],
                {'evidenceId': row['id'], 'recordedStart': row['start']})

    for folder in ('长期记忆/事件', '日常摘要', '工作日结'):
        for path in sorted((notes / folder).glob('*.md')):
            match = DATE.match(path.stem)
            if not match or match[1] >= day:
                continue
            try:
                lines = path.read_text(encoding='utf-8').splitlines()
            except (OSError, UnicodeError):
                unavailable.append(str(path))
                continue
            # Generated summaries would cite earlier analysis back as new source material.
            generated = False
            frontmatter = bool(lines and lines[0] == '---')
            for number, line in enumerate(lines, 1):
                if frontmatter:
                    if number > 1 and line == '---':
                        frontmatter = False
                    continue
                if '<!-- soundlog:combined:start -->' in line:
                    generated = True
                if not generated:
                    add('note', match[1], path, line, {'line': number})
                if '<!-- soundlog:combined:end -->' in line:
                    generated = False

    if not work_log.is_dir():
        unavailable.append(str(work_log))
    for path in sorted(work_log.glob('[0-9][0-9][0-9][0-9][0-9][0-9].md')):
        month = path.stem
        if month > day[:7].replace('-', ''):
            continue
        try:
            body = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            unavailable.append(str(path))
            continue
        sections = list(WORK_DAY.finditer(body))
        for i, heading in enumerate(sections):
            label = heading[1]
            when = f'{month[:4]}-{label[:2]}-{label[2:]}' if len(label) == 4 else label
            if when >= day:
                continue
            end = sections[i + 1].start() if i + 1 < len(sections) else len(body)
            for number, line in enumerate(body[heading.end():end].splitlines(),
                                          body.count('\n', 0, heading.end()) + 1):
                add('workLog', when, path, line, {'section': label, 'line': number})

    # Keep written event anchors visible alongside matches from long recordings.
    hits.sort(key=lambda item: (len(item['matchedTerms']), item['date'], item['id']), reverse=True)
    selected = {item['id']: item for kind in ('note', 'workLog', 'recording')
                for item in [hit for hit in hits if hit['kind'] == kind][:max(1, limit // 3)]}
    for item in hits:
        if len(selected) >= limit:
            break
        selected.setdefault(item['id'], item)
    return {'date': day, 'terms': terms, 'matches': list(selected.values())[:limit],
            'totalMatches': len(hits), 'unavailable': unavailable}


def save_search(home, result):
    identifier = 'history-' + digest(result)[:24]
    path = home / 'historical-context' / (identifier + '.json')
    if not path.exists():
        write_json(path, result)
    return {'id': identifier, 'path': str(path), 'totalMatches': result['totalMatches'],
            'unavailable': result['unavailable']}


def validate_checks(home, checks, facts, days):
    if not isinstance(checks, list):
        raise ValueError('历史核对记录必须是列表')
    for check in checks:
        identifier = check.get('searchId', '')
        if not re.fullmatch(r'history-[a-f0-9]{24}', identifier):
            raise ValueError('历史核对的检索编号无效')
        result = read_json(home / 'historical-context' / (identifier + '.json'))
        if 'history-' + digest(result)[:24] != identifier or result['date'] not in days:
            raise ValueError('历史检索回执已改变或日期与交付不符')
        fact_ids = check.get('factIds')
        if not isinstance(fact_ids, list) or not fact_ids or any(
            identifier not in facts or facts[identifier]['date'] != result['date'] for identifier in fact_ids
        ):
            raise ValueError('历史核对必须绑定当日事实')
        matches = check.get('historicalIds')
        if not isinstance(matches, list) or not set(matches) <= {hit['id'] for hit in result['matches']}:
            raise ValueError('历史核对引用超出检索回执')
        outcome = check.get('outcome')
        if (outcome not in {'same_event', 'different_event', 'insufficient'} or
                outcome != 'insufficient' and not matches or
                not isinstance(check.get('reason'), str) or not check['reason'].strip()):
            raise ValueError('历史核对须说明关联判断及依据')
