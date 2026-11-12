"""Build immutable evidence snapshots from transcription artifacts, never audio."""
import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def timestamp(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        raise ValueError('来源钟表时间不得包含时区')
    return dt


def day_bounds(day):
    start = datetime.strptime(day, '%Y-%m-%d')
    if start.strftime('%Y-%m-%d') != day:
        raise ValueError('日期必须为 YYYY-MM-DD')
    return start, start + timedelta(days=1)


def overlaps(start, end, lo, hi):
    return start < hi and end >= lo and (end > lo or start == end)


def validate_doc(doc):
    source = doc['sourceSHA256']
    if not isinstance(doc.get('sourcePath'), str) or not doc['sourcePath']:
        raise ValueError('来源文件引用缺失')
    if len(source) != 64 or any(c not in '0123456789abcdef' for c in source):
        raise ValueError('源 SHA256 无效')
    origin = timestamp(doc['recordingStartLocal'])
    for seg in doc['segments']:
        a, b = seg['startOffsetSeconds'], seg['endOffsetSeconds']
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (a, b)) or not 0 <= a <= b:
            raise ValueError('片段偏移无效')
        speakers = seg.get('speakerCandidates', [])
        if not isinstance(speakers, list) or any(not isinstance(x, str) for x in speakers):
            raise ValueError('说话人候选必须为字符串列表')
        if not isinstance(seg['text'], str):
            raise ValueError('逐字稿必须为字符串')
        for name, offset in [('absoluteStartLocal', a), ('absoluteEndLocal', b)]:
            expected = origin + timedelta(seconds=offset)
            if name in seg and abs((timestamp(seg[name]) - expected).total_seconds()) > .002:
                raise ValueError('原始偏移与钟表时间不一致')
    return origin


def build_evidence(runs, day):
    lo, hi = day_bounds(day)
    runs = Path(runs)
    selected, warnings = {}, []
    # Prefer the newest valid raw transcript; aligned labels are optional enrichment.
    paths = sorted(runs.rglob('raw.json'))
    aligned_only = [p for p in runs.rglob('speaker-aligned-transcript.json') if not (p.parent / 'raw.json').exists()]
    for path in paths + sorted(aligned_only):
        try:
            doc = read_json(path)
            origin = validate_doc(doc)
            if path.name == 'raw.json' and doc.get('status') not in ('completed_with_text', 'completed_no_text', 'completed'):
                raise ValueError('转写未完成')
            rank = (path.stat().st_mtime_ns, str(path))
            key = doc['sourceSHA256']
            if key not in selected or rank > selected[key][0]:
                selected[key] = (rank, path, doc, origin)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            warnings.append({'artifact': str(path), 'error': str(exc)})
    utterances, sounds, sources = {}, {}, {}
    for sha, (_, path, doc, origin) in sorted(selected.items()):
        labels = {}
        aligned = path.parent / 'speaker-aligned-transcript.json'
        try:
            a = read_json(aligned)
            validate_doc(a)
            if a['sourceSHA256'] != sha or a['recordingStartLocal'] != doc['recordingStartLocal']:
                raise ValueError('候选对齐来源不一致')
            labels = {(s['startOffsetSeconds'], s['endOffsetSeconds'], s['text']): s.get('speakerCandidates', []) for s in a['segments']}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            warnings.append({'artifact': str(aligned), 'error': str(exc)})
        for seg in doc['segments']:
            start = origin + timedelta(seconds=seg['startOffsetSeconds'])
            end = origin + timedelta(seconds=seg['endOffsetSeconds'])
            if not overlaps(start, end, lo, hi):
                continue
            item = {'sourceSHA256': sha, 'sourceFile': Path(doc['sourcePath']).name,
                    'startOffsetSeconds': seg['startOffsetSeconds'], 'endOffsetSeconds': seg['endOffsetSeconds'],
                    'start': start.isoformat(timespec='milliseconds'), 'end': end.isoformat(timespec='milliseconds'),
                    'text': seg['text']}
            item['id'] = 'ev-' + digest(item)[:24]
            candidates = labels.get((seg['startOffsetSeconds'], seg['endOffsetSeconds'], seg['text']), [])
            item['speakers'] = [sha + ':' + s for s in sorted(set(candidates)) if isinstance(s, str)]
            utterances[item['id']] = item
            sources[sha] = {'sourceFile': item['sourceFile'], 'reportedPath': doc['sourcePath'],
                            'artifact': str(path.resolve()), 'artifactSHA256': hashlib.sha256(path.read_bytes()).hexdigest(),
                            'accuracyAssessment': doc.get('accuracyAssessment', 'not_evaluated')}
        sound_path = path.parent / 'sound-events.json'
        try:
            sd = read_json(sound_path)
            if sd['sourceSHA256'] != sha or sd['recordingStartLocal'] != doc['recordingStartLocal']:
                raise ValueError('声学来源不一致')
            for ev in sd['events']:
                start, end = timestamp(ev['absoluteStartLocal']), timestamp(ev['absoluteEndLocal'])
                if end < start:
                    raise ValueError('声学时间范围倒退')
                if overlaps(start, end, lo, hi):
                    item = {k: ev[k] for k in ('category', 'startOffsetSeconds', 'endOffsetSeconds')}
                    item.update(sourceSHA256=sha, start=ev['absoluteStartLocal'], end=ev['absoluteEndLocal'], interpretation=None)
                    for k in ('confidence', 'averageConfidence', 'maximumConfidence'):
                        if k in ev:
                            item[k] = ev[k]
                    item['id'] = 'ac-' + digest(item)[:24]
                    sounds[item['id']] = item
                    sources.setdefault(sha, {'sourceFile': Path(doc['sourcePath']).name, 'reportedPath': doc['sourcePath'],
                                             'artifact': str(path.resolve()), 'artifactSHA256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                             'accuracyAssessment': doc.get('accuracyAssessment', 'not_evaluated')})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            warnings.append({'artifact': str(sound_path), 'error': str(exc)})
    package = {'schemaVersion': 1, 'date': day, 'utterances': sorted(utterances.values(), key=lambda x: (x['start'], x['id'])),
               'acoustics': sorted(sounds.values(), key=lambda x: (x['start'], x['id']))}
    package['fingerprint'] = digest(package)
    return package, {'sources': sources, 'warnings': warnings, 'fingerprint': package['fingerprint']}


def chunks(package, max_chars=12000):
    """90s groups, bounded long scenes, one utterance overlap; never drop short text."""
    result, current, size, end = [], [], 0, None
    expanded = []
    for item in package['utterances']:
        # A single long transcription can exceed a model context; keep the original
        # evidence ID and offsets while exposing bounded verbatim text excerpts.
        overhead = len(canonical({**item, 'text': ''}))
        width = max(1, max_chars - overhead - 128)
        text = item['text']
        expanded.extend([{**item, 'text': text[i:i+width]} for i in range(0, len(text), width)] or [item])
    for item in expanded:
        cost = len(canonical(item))
        start = timestamp(item['start'])
        if current and ((start - end).total_seconds() > 90 or size + cost > max_chars):
            result.append(current)
            tail = current[-1:] if len(canonical(current[-1])) + cost <= max_chars else []
            current = tail if size + cost > max_chars and (start - end).total_seconds() <= 90 else []
            size = sum(len(canonical(x)) for x in current)
        current.append(item)
        size += cost
        end = max(end, timestamp(item['end'])) if end else timestamp(item['end'])
    if current:
        result.append(current)
    output = []
    for items in result:
        start, end = min(x['start'] for x in items), max(x['end'] for x in items)
        related = [x for x in package['acoustics'] if x['start'] < end and x['end'] > start]
        # Bound the acoustic context too; source snapshot retains every event.
        categories = {}
        for x in related:
            key = (x['sourceSHA256'], x['category'])
            if key not in categories:
                categories[key] = {'sourceSHA256': key[0], 'category': key[1], 'eventCount': 0, 'interpretation': None}
            categories[key]['eventCount'] += 1
        body = {'date': package['date'], 'utterances': items, 'acoustics': sorted(categories.values(), key=lambda x: (-x['eventCount'], x['sourceSHA256'], x['category']))[:20]}
        output.append({'id': 'chunk-' + digest(body)[:24], 'material': body})
    return output
