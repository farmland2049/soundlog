"""Publish date-indexed local audio evidence from completed runs."""
import math
from datetime import timedelta
from pathlib import Path

from .evidence import build_evidence, digest, overlaps, read_json, scan_artifacts
from .scenes import digest_bytes
from .store import write_json

ARTIFACTS = ('raw.json', 'sound-events.json', 'speaker-timeline.json',
             'speaker-aligned-transcript.json', 'run-manifest.json')
MODULES = ('transcription', 'soundEvents', 'speakerDiarization', 'speakerAlignment')


def publish(runs, originals, output):
    directories, by_day = [], {}
    for path in sorted(runs.rglob('run-manifest.json')):
        manifest = read_json(path)
        original = originals / Path(manifest['inputPath']).name
        if not original.is_file() or original.is_symlink():
            continue
        if any(manifest['modules'].get(name, {}).get('state') != 'completed' for name in MODULES):
            continue
        directories.append(path.parent)

    catalog = scan_artifacts(runs, directories=directories)
    transcripts, _, warnings = catalog
    if warnings or len(transcripts) != len(directories):
        raise ValueError('录音归档源有损坏、缺失或重复的转写，无法更新每日索引')

    for sha, (_, path, document, start) in transcripts.items():
        manifest = read_json(path.parent / 'run-manifest.json')
        if manifest['sourceSHA256'] != sha:
            raise ValueError('运行清单与转写来源不一致')
        duration = manifest['audioDurationSeconds']
        if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            raise ValueError('录音时长无效')
        end = start + timedelta(seconds=duration)
        files = list(ARTIFACTS)
        window_file = read_json(path.parent / 'sound-events.json').get('windowCandidatesFile')
        if window_file:
            files.append(window_file)
        origin = originals / Path(document['sourcePath']).name
        if origin.name != Path(manifest['inputPath']).name:
            raise ValueError('转写和运行清单的音频文件名不一致')
        source = {
            'sourceSHA256': sha, 'audio': str(origin), 'start': start.isoformat(), 'end': end.isoformat(),
            'artifacts': {name: {'path': str(path.parent / name), 'sha256': digest_bytes(path.parent / name)}
                          for name in files},
        }
        day = start.replace(hour=0, minute=0, second=0, microsecond=0)
        while day < end:
            next_day = day + timedelta(days=1)
            if overlaps(start, end, day, next_day):
                by_day.setdefault(day.date().isoformat(), {})[sha] = source
            day = next_day

    latest = output / 'latest.json'
    previous = read_json(latest)['days'] if latest.exists() else {}
    if not by_day:
        if previous:
            raise ValueError('找不到既有每日归档的运行产物')
        return {'days': {}, 'updatedDates': []}
    current = {}
    for day, sources in sorted(by_day.items()):
        package, manifest = build_evidence(runs, day, catalog=catalog, include_references=True)
        if manifest['warnings']:
            raise ValueError('每日录音对齐证据不完整')
        for key in ('utterances', 'acoustics'):
            package[key] = [row for row in package[key] if row['sourceSHA256'] in sources]
        package.pop('fingerprint')
        payload = {'schemaVersion': 1, 'date': day, 'sources': sources, **package}
        fingerprint = digest(payload)
        path = output / day / (fingerprint + '.json')
        if path.exists():
            if read_json(path) != payload:
                raise ValueError('已有按天归档内容改变，拒绝覆盖')
        else:
            write_json(path, payload)
        current[day] = {'path': str(path.relative_to(output)), 'sha256': digest_bytes(path)}

    if not previous.keys() <= current.keys():
        raise ValueError('部分已归档日期的运行产物缺失，保留现有索引')
    if current != previous:
        write_json(latest, {'schemaVersion': 1, 'days': current})
    return {'days': current, 'updatedDates': [day for day in current if current[day] != previous.get(day)]}
