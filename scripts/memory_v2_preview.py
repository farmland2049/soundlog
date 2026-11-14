#!/usr/bin/env python3
"""Build a private, read-only Basic Memory V2 import preview from selected products."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from soundlog_memory.evidence import canonical, digest, read_json
from soundlog_memory.reading import load_verified_result
from soundlog_memory.scenes import digest_bytes, resolve_snapshot
from soundlog_memory.store import Store, write_json


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BM_ROOT = ROOT.parent.parent / '05-日常工具/BasicMemory/笔记'
FUNCTION_LABELS = {
    'journal': '每日记录', 'minutes': '讨论纪要',
    'actions': '待办与安排候选', 'learning': '学习与灵感笔记',
}


def _yaml_string(value):
    return json.dumps(value, ensure_ascii=False)


def _quote_block(value):
    return '\n'.join('> ' + line for line in value.splitlines())


def _target_note(title, note_type, permalink, metadata, body):
    return ('---\n'
            f'title: {_yaml_string(title)}\n'
            f'type: {note_type}\n'
            f'permalink: {permalink}\n'
            f'soundlog: {canonical(metadata)}\n'
            '---\n\n'
            f'# {title}\n\n{body.rstrip()}\n')


def _parse_target_note(path):
    text = Path(path).read_text(encoding='utf-8')
    lines = text.splitlines()
    if not lines or lines[0] != '---':
        raise ValueError('目标笔记缺少YAML frontmatter: ' + str(path))
    try:
        end = lines.index('---', 1)
    except ValueError:
        raise ValueError('目标笔记frontmatter未闭合: ' + str(path)) from None
    front = {}
    for line in lines[1:end]:
        if ':' not in line:
            raise ValueError('目标笔记frontmatter格式无效: ' + str(path))
        key, value = line.split(':', 1)
        key, value = key.strip(), value.strip()
        if key in front:
            raise ValueError('目标笔记frontmatter键重复: ' + str(path))
        if key == 'title':
            front[key] = json.loads(value)
        elif key == 'soundlog':
            front[key] = json.loads(value)
        else:
            front[key] = value
    if not {'title', 'type', 'permalink', 'soundlog'} <= set(front):
        raise ValueError('目标笔记frontmatter缺字段: ' + str(path))
    if f'# {front["title"]}' not in lines[end + 1:]:
        raise ValueError('目标笔记正文标题与frontmatter不一致: ' + str(path))
    return front, '\n'.join(lines[end + 1:])


def verify_preview(preview_dir):
    preview_dir = Path(preview_dir).resolve()
    if not preview_dir.is_dir() or preview_dir.is_symlink():
        raise ValueError('预览目录不存在或不是普通目录')
    manifest_path = preview_dir / 'manifest.json'
    manifest = read_json(manifest_path)
    artifacts = manifest.get('artifacts')
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError('manifest缺少工件清单')
    expected_paths = {'manifest.json'}
    for relative, expected_sha in artifacts.items():
        rel = Path(relative)
        path = preview_dir / rel
        if rel.is_absolute() or '..' in rel.parts or path.is_symlink() or not path.is_file():
            raise ValueError('工件路径越界、缺失或为符号链接: ' + relative)
        if not path.resolve().is_relative_to(preview_dir):
            raise ValueError('工件解析后越过预览目录: ' + relative)
        if digest_bytes(path) != expected_sha:
            raise ValueError('预览工件哈希不符: ' + relative)
        expected_paths.add(relative)
    actual_paths = {str(p.relative_to(preview_dir)) for p in preview_dir.rglob('*') if p.is_file()}
    actual_paths.update(str(p.relative_to(preview_dir)) for p in preview_dir.rglob('*') if p.is_symlink())
    if actual_paths != expected_paths:
        raise ValueError('预览文件集合与manifest不一致')
    if manifest.get('previewId') != preview_dir.name:
        raise ValueError('预览目录名与previewId不一致')
    summary = manifest.get('summary', {})
    source_notes = list((preview_dir / 'sources').glob('*.md'))
    candidate_notes = list((preview_dir / 'candidates').glob('*/*.md'))
    daily_notes = list((preview_dir / 'daily').glob('*.md'))
    counts = {'sourceNoteFiles': len(source_notes), 'candidateNoteFiles': len(candidate_notes),
              'dailyIndexFiles': len(daily_notes), 'verifiedArtifactFiles': len(artifacts)}
    if (len(candidate_notes) != summary.get('functionalCandidates')
            or sum(1 for p in source_notes if p.name != 'index.md') != len(summary.get('dates', []))
            or len(daily_notes) != len(summary.get('dates', []))):
        raise ValueError('预览笔记数量与manifest汇总不一致')
    source_anchors = {}
    for path in source_notes:
        front, body = _parse_target_note(path)
        if front['type'] != 'soundlog_source_record' and front['type'] != 'soundlog_source_index':
            raise ValueError('来源笔记类型无效')
        if path.name == 'index.md':
            continue
        day = path.stem
        source_anchors[day] = set(re.findall(r'<a id="e-([^"]+)"></a>', body))
    anchor_count = sum(len(ids) for ids in source_anchors.values())
    if anchor_count != summary.get('sourceUtterances'):
        raise ValueError('来源原文锚点数量与manifest汇总不一致')
    known_candidates, reference_count = set(), 0
    source_ref = re.compile(r'\[\[soundlog/sources/(\d{4}-\d{2}-\d{2})\]\] · 证据ID `([^`]+)`')
    for path in candidate_notes:
        front, body = _parse_target_note(path)
        meta = front['soundlog']
        if (front['type'] != 'soundlog_candidate' or meta.get('status') != 'candidate'
                or meta.get('lifecycle') != 'candidate' or meta.get('subject') is not None
                or meta.get('sourceMedium') != 'unknown' or meta.get('id') != path.stem):
            raise ValueError('候选笔记升级了状态/主体/媒介或ID不一致')
        if meta.get('date') != path.parent.name or not isinstance(meta.get('functionUses'), list):
            raise ValueError('候选笔记日期/用途与目标路径不一致')
        known_candidates.add((meta['date'], meta['id']))
        refs = source_ref.findall(body)
        if not refs:
            raise ValueError('候选笔记没有来源关系')
        for day, evidence_id in refs:
            if day not in source_anchors or evidence_id not in source_anchors[day]:
                raise ValueError('候选笔记引用了缺失的原文锚点')
        reference_count += len(refs)
    daily_ref_count = 0
    candidate_ref = re.compile(r'\[\[soundlog/candidates/(\d{4}-\d{2}-\d{2})/(fact-[a-f0-9]{24})\]\]')
    for path in daily_notes:
        front, body = _parse_target_note(path)
        if front['type'] != 'soundlog_daily_index' or front['soundlog'].get('date') != path.stem:
            raise ValueError('每日索引日期或类型无效')
        links = candidate_ref.findall(body)
        if any(link not in known_candidates for link in links):
            raise ValueError('每日索引指向不存在的候选')
        daily_ref_count += len(links)
    if reference_count != summary.get('evidenceReferences'):
        raise ValueError('候选引文关系数量与manifest汇总不一致')
    target = Path(summary['formalTargetNamespace'])
    return {'previewId': manifest['previewId'], 'integrity': 'passed',
            'semanticAssessment': summary.get('semanticAssessment'), **counts,
            'sourceUtterances': summary.get('sourceUtterances'),
            'validatedSourceAnchors': anchor_count,
            'evidenceReferences': summary.get('evidenceReferences'),
            'validatedEvidenceLinks': reference_count,
            'dailyCandidateLinks': daily_ref_count,
            'formalTargetNamespaceCurrentlyExists': target.exists()}


def build_preview(*, product_root, scenes_root, selection_file, legacy_root,
                  basic_memory_root, output_root, source_accounting_file):
    product_root = Path(product_root).resolve()
    scenes_root = Path(scenes_root).resolve()
    selection_file = Path(selection_file).resolve()
    source_accounting_file = Path(source_accounting_file).resolve()
    legacy_root = Path(legacy_root).resolve()
    basic_memory_root = Path(basic_memory_root).resolve()
    output_root = Path(output_root).resolve()

    if not basic_memory_root.is_dir() or basic_memory_root.is_symlink():
        raise ValueError('正式 Basic Memory 路径必须是已存在的本地实体目录')
    if not legacy_root.is_dir():
        raise ValueError('本地旧候选目录不存在，拒绝把路径错误当空库')
    if not output_root.is_relative_to((ROOT / '记忆库').resolve()):
        raise ValueError('预览只能写入项目忽略的记忆库目录')
    target_root = basic_memory_root / 'soundlog'
    if target_root.exists():
        raise ValueError('正式 Basic Memory 的 soundlog 命名空间已存在，先停止并审阅冲突')

    selected = read_json(selection_file)
    if selected.get('schemaVersion') != 1 or not isinstance(selected.get('results'), list):
        raise ValueError('current-results 选择清单无效')
    chosen = selected['results']
    if not chosen or len({row.get('resultId') for row in chosen}) != len(chosen):
        raise ValueError('当前结果为空或存在重复 resultId')

    facts_by_id, facts_by_day = {}, {}
    source_receipts, expected_dates = [], set()
    for row in chosen:
        receipt, facts = load_verified_result(product_root, row['resultId'])
        if receipt['state'] != 'completed':
            raise ValueError('只能预览完整结果')
        if sorted(row['dates']) != sorted({f['date'] for f in facts}):
            raise ValueError('current-results 日期与事实日期不一致')
        source_receipts.append({'resultId': receipt['resultId'], 'requestId': receipt['requestId'],
                                'sourceSnapshotId': receipt['sourceSnapshotId'],
                                'receiptSHA256': digest_bytes(product_root / 'results' / row['resultId'] / 'receipt.json')})
        for fact in facts:
            if fact['id'] in facts_by_id:
                raise ValueError('选中结果之间存在重复事实ID')
            facts_by_id[fact['id']] = fact
            facts_by_day.setdefault(fact['date'], []).append(fact)
            expected_dates.add(fact['date'])

    snapshot = resolve_snapshot(scenes_root)
    snapshot_receipt = read_json(snapshot / 'receipt.json')
    if any(item['sourceSnapshotId'] != snapshot_receipt['snapshotId'] for item in source_receipts):
        raise ValueError('候选结果与每日原文快照不是同一来源修订')
    source_accounting = read_json(source_accounting_file)
    audio_source_count = source_accounting.get('totalDeclaredSourceFiles')
    transcript_source_count = source_accounting.get('withTranscriptEvidence')
    no_text_count = source_accounting.get('withoutTranscriptEvidence')
    if any(type(n) is not int for n in (audio_source_count, transcript_source_count, no_text_count)):
        raise ValueError('音频来源覆盖统计无效')
    if audio_source_count != transcript_source_count + no_text_count:
        raise ValueError('音频来源覆盖统计不闭合')
    source_rows, source_rows_by_id, source_row_days = {}, {}, {}
    source_names = set()
    for day in sorted(expected_dates):
        name = day + '_utterances.json'
        expected_sha = snapshot_receipt['artifacts'].get(name)
        path = snapshot / name
        if not expected_sha or not path.is_file() or digest_bytes(path) != expected_sha:
            raise ValueError('每日原文工件缺失或哈希不符: ' + day)
        document = read_json(path)
        utterances = document.get('utterances')
        if not isinstance(utterances, list):
            raise ValueError('每日原文结构无效: ' + day)
        rows = []
        for utterance in utterances:
            required = {'id', 'start', 'end', 'startOffsetSeconds', 'endOffsetSeconds',
                        'sourceFile', 'sourceSHA256', 'speakers', 'text'}
            if not required.issubset(utterance) or utterance['id'] in source_rows_by_id:
                raise ValueError('原文行字段无效或ID重复')
            source_rows_by_id[utterance['id']] = utterance
            source_row_days[utterance['id']] = day
            source_names.add((utterance['sourceSHA256'], Path(utterance['sourceFile']).name))
            rows.append(utterance)
        source_rows[day] = rows
    if len(source_names) != transcript_source_count:
        raise ValueError('原文快照的转写来源数与验收统计不一致')

    evidence_ref_count = 0
    for fact in facts_by_id.values():
        if fact['status'] != 'candidate' or fact['sourceMedium'] != 'unknown' or fact['subject'] is not None:
            raise ValueError('候选状态、来源媒介或匿名主体字段越界')
        if not fact['evidence']:
            raise ValueError('功能候选缺少原文证据')
        for ref in fact['evidence']:
            original = source_rows_by_id.get(ref['id'])
            if (not original or ref['quote'] not in original['text']
                    or ref['sourceSHA256'] != original['sourceSHA256']
                    or ref['sourceFile'] != original['sourceFile']
                    or ref['start'] != original['start'] or ref['end'] != original['end']):
                raise ValueError('事实引文与已校验的原文快照不一致')
            evidence_ref_count += 1

    legacy_records = Store(legacy_root).records()
    active_legacy = [r for r in legacy_records if r.get('lifecycle') == 'active']
    merged_legacy = [r for r in legacy_records if r.get('lifecycle') == 'merged']
    legacy_by_evidence = {}
    for record in active_legacy:
        for ref in record.get('evidence', []):
            legacy_by_evidence.setdefault(ref['id'], set()).add(record['id'])
    legacy_to_facts = {record['id']: set() for record in active_legacy}
    for fact in facts_by_id.values():
        for ref in fact['evidence']:
            for old_id in legacy_by_evidence.get(ref['id'], set()):
                legacy_to_facts[old_id].add(fact['id'])
    crosswalk = [
        {'legacyCandidateId': old_id, 'functionalFactIds': sorted(fact_ids),
         'relationship': 'shared_evidence_only', 'semanticEquivalence': 'not_assessed',
         'action': 'manual_review'}
        for old_id, fact_ids in sorted(legacy_to_facts.items()) if fact_ids
    ]
    matched_legacy = sum(bool(ids) for ids in legacy_to_facts.values())

    dates = sorted(expected_dates)
    mapping = {
        'schemaVersion': 1,
        'targetProject': 'basic-memory-trial',
        'targetLocalRoot': str(basic_memory_root),
        'targetNamespace': 'soundlog/',
        'writeMode': 'preview_only',
        'sourceIndexLayer': 'sources/index.md',
        'sourceLayer': 'sources/YYYY-MM-DD.md',
        'candidateLayer': 'candidates/YYYY-MM-DD/<fact-id>.md',
        'dailyLayer': 'daily/YYYY-MM-DD.md',
        'confirmedLayer': 'confirmed/<memory-id>.md',
        'rules': [
            '所有候选状态保持 candidate；不因用途标签或回查成功升级为确认事实。',
            'subject 保持 null；文件内匿名说话人标签只放在证据字段，不建人物实体或声纹关系。',
            'sourceMedium 保持 unknown；录音时间、事件时间和期限分别保留。',
            '原子候选不自动合并；跨旧候选仅建立共享证据索引并要求人工审核。',
            'daily 页面只做索引与计数，不另造摘要或进度推断。',
            '仅处理转写文本；无转写录音按来源覆盖缺口保留，不生成虚构条目。',
        ],
        'dates': dates,
        'results': source_receipts,
        'sourceCoverage': {'audioSources': audio_source_count,
                           'withTranscript': transcript_source_count,
                           'withoutTranscript': no_text_count,
                           'accountingSHA256': digest_bytes(source_accounting_file)},
        'legacyHandling': {'totalRecords': len(legacy_records), 'activeCandidates': len(active_legacy),
                           'mergedRecords': len(merged_legacy), 'semanticMerge': False,
                           'crosswalkRows': len(crosswalk), 'matchedActiveCandidates': matched_legacy,
                           'unmatchedActiveCandidates': len(active_legacy) - matched_legacy,
                           'snapshotSHA256': digest(legacy_records)},
        'mappingVersion': 'v2-draft-2',
    }
    implementation_sha = digest_bytes(Path(__file__))
    preview_id = 'preview-' + digest({'mapping': mapping, 'snapshotId': snapshot_receipt['snapshotId'],
                                      'implementationSHA256': implementation_sha})[:24]
    dest = output_root / preview_id
    if dest.exists():
        prior = read_json(dest / 'manifest.json')
        if prior.get('previewId') != preview_id:
            raise ValueError('同名预览目录存在但来源指纹不同')
        verified = verify_preview(dest)
        return {**prior['summary'], **verified, 'output': str(dest), 'reused': True}

    output_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.v2-preview-', dir=output_root))
    try:
        (stage / 'sources').mkdir()
        (stage / 'candidates').mkdir()
        (stage / 'daily').mkdir()
        # Immutable source notes retain every core utterance, not only selected facts.
        for day, rows in source_rows.items():
            rows = sorted(rows, key=lambda r: (r['start'], r['id']))
            body = ['> 机器转写原文；未经听音校订。匿名标签不表示真实身份。',
                    '> 原始录音不复制到记忆库；本页逐句保存来源文字和可回查偏移。', '', '## 原文证据', '']
            for row in rows:
                tags = ', '.join(row['speakers']) if row['speakers'] else '未匹配'
                body.extend([f'<a id="e-{row["id"]}"></a>',
                             f'- `{row["start"]}`–`{row["end"]}` · `{Path(row["sourceFile"]).name}` · '
                             f'`{row["sourceSHA256"]}` · 偏移 {row["startOffsetSeconds"]}–{row["endOffsetSeconds"]} 秒 · `{tags}`',
                             '  ' + _quote_block(row['text']), ''])
            metadata = {'date': day, 'sourceSnapshotId': snapshot_receipt['snapshotId'],
                        'utterances': len(rows), 'transcriptSourceCount': len({r['sourceSHA256'] for r in rows}),
                        'reviewStatus': 'machine_transcript_unreviewed'}
            note = _target_note(day + ' 原文来源', 'soundlog_source_record',
                                'soundlog/sources/' + day, metadata, '\n'.join(body))
            path = stage / 'sources' / (day + '.md')
            path.write_text(note, encoding='utf-8')

        source_index_body = [
            '> 来源覆盖索引；不复制原始音频，也不把无转写来源补成文字。', '',
            f'- 本次审阅范围内音频源：{audio_source_count} 个。',
            f'- 有转写证据：{transcript_source_count} 个。',
            f'- 无转写证据：{no_text_count} 个；在本索引中保留覆盖缺口，不生成候选。',
            f'- 转写原文：{sum(map(len, source_rows.values()))} 条，保留在下列逐日来源页。', '', '## 逐日原文', '',
        ]
        source_index_body.extend(f'- [[soundlog/sources/{day}]]' for day in dates)
        source_index_metadata = {'audioSources': audio_source_count,
                                 'withTranscript': transcript_source_count,
                                 'withoutTranscript': no_text_count,
                                 'sourceSnapshotId': snapshot_receipt['snapshotId'],
                                 'reviewStatus': 'machine_transcript_unreviewed'}
        (stage / 'sources' / 'index.md').write_text(
            _target_note('soundlog 来源覆盖', 'soundlog_source_index', 'soundlog/sources',
                         source_index_metadata, '\n'.join(source_index_body)), encoding='utf-8')

        by_day_use = {day: {use: [] for use in FUNCTION_LABELS} for day in dates}
        for fact in sorted(facts_by_id.values(), key=lambda f: (f['date'], f['id'])):
            body = ['> 功能候选；未经用户确认，不代表真实身份、事件事实或当前待办。', '',
                    '## Observation', '', f'- [candidate] {fact["summary"]}', '', '## Metadata', '',
                    f'- 功能用途：{"、".join(FUNCTION_LABELS[u] for u in fact["functionUses"])}',
                    f'- 陈述性质：{fact["assertion"]}', f'- 主体：{fact["subject"] if fact["subject"] is not None else "未知"}',
                    f'- 来源媒介：{fact["sourceMedium"]}', f'- 录音日期：{fact["date"]}',
                    f'- 事件时间原话：{fact["eventTimeText"] or "未提及/未提炼"}',
                    f'- 期限原话：{fact["dueText"] or "未提及/未提炼"}',
                    f'- 待办状态线索：{fact["taskState"] or "不适用/未知"}', '', '## Evidence', '']
            for ref in fact['evidence']:
                tags = ', '.join(ref['speakers']) if ref['speakers'] else '未匹配'
                evidence_day = source_row_days[ref['id']]
                body.extend([f'- 来源：[[soundlog/sources/{evidence_day}]] · 证据ID `{ref["id"]}` · '
                             f'`{Path(ref["sourceFile"]).name}` · `{ref["sourceSHA256"]}` · '
                             f'{ref["start"]}–{ref["end"]} · 匿名标签 `{tags}`',
                             '  ' + _quote_block(ref['quote']), ''])
            metadata = {k: fact[k] for k in ('id', 'date', 'functionUses', 'assertion', 'subject',
                                              'sourceMedium', 'eventTimeText', 'dueText', 'taskState', 'status')}
            metadata['lifecycle'] = 'candidate'
            relative = Path('candidates') / fact['date'] / (fact['id'] + '.md')
            target = Path('soundlog') / relative
            note = _target_note(fact['id'], 'soundlog_candidate',
                                'soundlog/candidates/' + fact['date'] + '/' + fact['id'],
                                metadata, '\n'.join(body))
            dest_file = stage / relative
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            dest_file.write_text(note, encoding='utf-8')
            for use in fact['functionUses']:
                by_day_use[fact['date']][use].append(fact['id'])

        for day in dates:
            rows = source_rows[day]
            facts = facts_by_day.get(day, [])
            body = ['> 自动目录；此页只列来源、候选数量和回查链接，不自动生成新的事实摘要。', '',
                    f'- 原文来源：[[soundlog/sources/{day}]]（{len(rows)}条核心原文）',
                    f'- 原子候选：{len(facts)}条，全部保留为待确认候选。', '', '## 按产品用途', '']
            for use, label in FUNCTION_LABELS.items():
                ids = by_day_use[day][use]
                body.extend([f'### {label}（{len(ids)}）', ''])
                body.extend(f'- [[soundlog/candidates/{day}/{fid}]]' for fid in ids)
                body.append('')
            metadata = {'date': day, 'sourceSnapshotId': snapshot_receipt['snapshotId'],
                        'utterances': len(rows), 'candidateFacts': len(facts),
                        'byFunction': {use: len(ids) for use, ids in by_day_use[day].items()},
                        'status': 'preview_only'}
            note = _target_note(day + ' soundlog 索引', 'soundlog_daily_index',
                                'soundlog/daily/' + day, metadata, '\n'.join(body))
            (stage / 'daily' / (day + '.md')).write_text(note, encoding='utf-8')

        write_json(stage / 'mapping.json', mapping)
        write_json(stage / 'legacy-crosswalk.json', {
            'scope': 'shared evidence identifiers only; semantic equality is not inferred',
            'activeLegacyCandidates': len(active_legacy), 'mergedLegacyRecords': len(merged_legacy),
            'rows': crosswalk,
        })
        target_note_count = len(list(stage.rglob('*.md')))
        artifact_count = sum(1 for p in stage.rglob('*') if p.is_file()) + 1  # README is written below.
        summary = {
            'previewId': preview_id, 'mode': 'preview_only_no_formal_write',
            'formalTargetNamespace': str(target_root), 'targetNamespaceExists': False,
            'dates': dates, 'sourceUtterances': sum(map(len, source_rows.values())),
            'audioSources': audio_source_count, 'transcriptSources': len(source_names),
            'sourcesWithoutTranscript': no_text_count, 'functionalCandidates': len(facts_by_id),
            'evidenceReferences': evidence_ref_count, 'legacyActiveCandidates': len(active_legacy),
            'legacyMergedRecords': len(merged_legacy), 'legacyMatchedCandidates': matched_legacy,
            'legacyUnmatchedCandidates': len(active_legacy) - matched_legacy,
            'legacySharedEvidenceRows': len(crosswalk),
            'semanticAssessment': 'not_independently_verified',
            'noteFiles': target_note_count, 'artifactFiles': artifact_count,
        }
        manifest = {'schemaVersion': 1, 'previewId': preview_id,
                    'sourceSnapshotId': snapshot_receipt['snapshotId'],
                    'implementationSHA256': implementation_sha,
                    'sourceArtifacts': source_receipts, 'selectionSHA256': digest_bytes(selection_file),
                    'summary': summary,
                    'limitations': ['源文字仍是机器转写，未听音校订。',
                                    '共享原文证据不等同于语义等价或应当合并。',
                                    '正式 Basic Memory 尚未写入；哈希只证明预览文件完整。']}
        readme = ['# soundlog V2 正式记忆接入预览', '',
                  '本目录是私人、只读目标预览，不是正式记忆写入回执。', '',
                  f'- 预览编号：`{preview_id}`',
                  f'- 目标：`{target_root}`（生成时该命名空间不存在）',
                  f'- 日期：{", ".join(dates)}',
                  f'- 原文：{summary["sourceUtterances"]} 条；来自 {summary["transcriptSources"]} 个有文字来源。',
                  f'- 音频覆盖：{summary["audioSources"]} 个源，其中 {summary["sourcesWithoutTranscript"]} 个无转写；不补造文字或候选。',
                  f'- 功能候选：{summary["functionalCandidates"]} 条；引文 {evidence_ref_count} 处。',
                  f'- 旧候选：{len(active_legacy)} 条 active，{len(merged_legacy)} 条 merged；共享证据映射 {len(crosswalk)} 行。',
                  '- 所有候选仍为未确认状态；未判定语义等价、身份、真实活动或当前待办。',
                  '- 未拷贝原始录音；声学事件候选不进入本预览。',
                  '- `mapping.json` 描述正式目标结构；`sources/`、`candidates/`、`daily/` 是建议落盘文稿；`legacy-crosswalk.json` 仅按共享证据映射。',
                  '- 正式写入、读回、重复同步、失败重试、更正与撤销测试仍未执行。', '',
                  '完整性清单见 `manifest.json`。']
        (stage / 'README.md').write_text('\n'.join(readme) + '\n', encoding='utf-8')
        note_files = sorted(p for p in stage.rglob('*.md') if p.relative_to(stage) != Path('README.md'))
        artifact_files = sorted(p for p in stage.rglob('*') if p.is_file())
        manifest['artifacts'] = {str(p.relative_to(stage)): digest_bytes(p) for p in artifact_files}
        write_json(stage / 'manifest.json', manifest)
        if dest.exists():
            raise ValueError('预览目标已存在，拒绝覆盖')
        os.replace(stage, dest)
        verified = verify_preview(dest)
        return {**summary, **verified, 'output': str(dest), 'reused': False}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main(argv=None):
    parser = argparse.ArgumentParser(description='生成正式 Basic Memory 接入的私有预览，不写正式库')
    parser.add_argument('--verify', type=Path, help='只验收一个已生成预览目录，不创建输出')
    parser.add_argument('--products', type=Path, default=ROOT / '产出/功能提炼')
    parser.add_argument('--scenes', type=Path, default=ROOT / '产出/大模型分析素材/每日场景-v2')
    parser.add_argument('--selection', type=Path, default=ROOT / '产出/2026-11-13-六天验收/current-results.json')
    parser.add_argument('--source-accounting', type=Path,
                        default=ROOT / '产出/2026-11-13-六天验收/source-and-acoustic-integrity.json')
    parser.add_argument('--legacy-store', type=Path, default=ROOT / '记忆库')
    parser.add_argument('--basic-memory-root', type=Path, default=DEFAULT_BM_ROOT)
    parser.add_argument('--output', type=Path, default=ROOT / '记忆库/运行/V2接入预览')
    args = parser.parse_args(argv)
    try:
        if args.verify:
            print(json.dumps(verify_preview(args.verify), ensure_ascii=False, indent=2))
            return 0
        print(json.dumps(build_preview(product_root=args.products, scenes_root=args.scenes,
                                       selection_file=args.selection, legacy_root=args.legacy_store,
                                       basic_memory_root=args.basic_memory_root, output_root=args.output,
                                       source_accounting_file=args.source_accounting),
                         ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('V2预览失败: ' + str(exc), file=__import__('sys').stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
