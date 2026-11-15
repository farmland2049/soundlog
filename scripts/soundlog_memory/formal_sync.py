"""Prepare a create-only Basic Memory pilot; never call a model or an MCP writer.

``apply`` only creates local files and records a pending readback receipt. It
does not claim that Basic Memory has indexed the files. The user must authorize
the actual formal write separately from preparing a plan.
"""
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone

from .evidence import read_json
from .scenes import digest_bytes
from .store import write_json
from memory_v2_preview import _parse_target_note, verify_preview


def validate_mcp_preflight(proof, prepared, now=None):
    """Require a recent read-only MCP project and namespace audit."""
    now = now or datetime.now(timezone.utc)
    try:
        checked = datetime.fromisoformat(proof['checkedAt'].replace('Z', '+00:00'))
        if checked.tzinfo is None or now.tzinfo is None:
            raise ValueError('时区缺失')
        age = (now - checked).total_seconds()
        project, find, search = proof['project'], proof['namespaceFind'], proof['permalinkSearch']
        if (not 0 <= age <= 120 or proof.get('schemaVersion') != 1
                or project.get('external_id') != prepared['projectExternalId']
                or project.get('source') != 'local'
                or Path(project['local_path']).resolve() != Path(prepared['targetRoot']).resolve()
                or find.get('path') != 'soundlog' or find.get('total') != 0 or find.get('has_more') is not False
                or search.get('query') != 'soundlog/*' or search.get('total') != 0
                or search.get('total_is_exact') is not True or search.get('has_more') is not False):
            raise ValueError('MCP项目或空命名空间检查失败、分页不完整或结果过期')
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('MCP预检证据格式无效') from exc
    return True


def _path(rel):
    p = Path(rel)
    if (p.is_absolute() or '..' in p.parts or len(p.parts) < 3 or p.parts[0] != 'soundlog'
            or p.parts[1] not in {'sources', 'candidates', 'daily'} or p.suffix != '.md'):
        raise ValueError('计划含越界路径')
    return p


def _no_symlinks(root, relative):
    current = Path(root)
    if current.is_symlink():
        raise ValueError('目标根目录不能为符号链接')
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('目标路径不能穿过符号链接')


def without_embeddings(data):
    """Opt out of background local embeddings while preserving all note body bytes."""
    marker = b'\n---\n'
    if not data.startswith(b'---\n') or marker not in data[4:]:
        raise ValueError('预览笔记frontmatter格式无效')
    position = data.index(marker, 4)
    front = data[:position]
    if any(line.strip().split(b':', 1)[0] == b'embed' for line in front.splitlines()[1:]):
        raise ValueError('预览已有embed字段，拒绝覆盖')
    return front + b'\nembed: false' + data[position:]


def prepare(plan_path, preview_dir, target_root, *, permit_existing=False):
    plan_path, preview_dir, target_root = map(Path, (plan_path, preview_dir, target_root))
    plan = read_json(plan_path)
    audit = verify_preview(preview_dir)
    if (plan.get('mode') != 'read_only_proposed_two_day_pilot'
            or plan.get('previewId') != audit['previewId']
            or plan.get('previewManifestSHA256') != digest_bytes(preview_dir / 'manifest.json')
            or plan.get('targetRoot') != str(target_root.resolve())):
        raise ValueError('试点计划与预览或目标不一致')
    if not target_root.is_dir() or target_root.is_symlink():
        raise ValueError('目标根目录不存在或为符号链接')
    if not permit_existing and ((target_root / 'soundlog').exists() or (target_root / 'soundlog').is_symlink()):
        raise ValueError('正式soundlog命名空间已存在，先复核冲突')
    rows = plan.get('files')
    if (not isinstance(rows, list) or len(rows) != 224
            or plan.get('dates') != ['2026-11-13', '2026-11-14']):
        raise ValueError('试点必须包含224篇明确列出的文稿')
    seen, prepared, counts, daily_counts = set(), [], {}, {}
    for row in rows:
        rel = _path(row['destination'])
        if rel in seen:
            raise ValueError('目标路径重复')
        seen.add(rel)
        _no_symlinks(target_root, rel)
        source = preview_dir / rel.relative_to('soundlog')
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(preview_dir.resolve()):
            raise ValueError('来源文件缺失或越界')
        front, _ = _parse_target_note(source)
        if front['type'] != row['noteType'] or front['permalink'] != row['permalink']:
            raise ValueError('来源笔记与计划的类型或permalink不一致')
        folder = rel.parts[1]
        date = rel.parts[2] if folder == 'candidates' else rel.stem
        if date not in plan['dates']:
            raise ValueError('目标日期不在试点范围内')
        required_type = {'sources': 'soundlog_source_record', 'candidates': 'soundlog_candidate',
                         'daily': 'soundlog_daily_index'}[folder]
        if front['type'] != required_type:
            raise ValueError('目标类型和路径不一致')
        counts[required_type] = counts.get(required_type, 0) + 1
        daily_counts[(date, required_type)] = daily_counts.get((date, required_type), 0) + 1
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('预览文件与计划指纹不一致')
        target = target_root / rel
        if not permit_existing and (target.exists() or target.is_symlink()):
            raise ValueError('目标已存在，拒绝覆盖: ' + str(rel))
        prepared.append({'destination': str(rel), 'sourceSHA256': row['sha256'],
                         'writtenSHA256': hashlib.sha256(without_embeddings(data)).hexdigest(),
                         'permalink': row['permalink'], 'noteType': row['noteType']})
    if counts != {'soundlog_source_record': 2, 'soundlog_candidate': 220, 'soundlog_daily_index': 2}:
        raise ValueError('试点各类文稿数量与计划不符')
    if daily_counts != {('2026-11-13', 'soundlog_source_record'): 1,
                        ('2026-11-14', 'soundlog_source_record'): 1,
                        ('2026-11-13', 'soundlog_candidate'): 100,
                        ('2026-11-14', 'soundlog_candidate'): 120,
                        ('2026-11-13', 'soundlog_daily_index'): 1,
                        ('2026-11-14', 'soundlog_daily_index'): 1}:
        raise ValueError('试点逐日文稿数量与计划不符')
    return {'schemaVersion': 1, 'state': 'prepared_not_written',
            'previewId': plan['previewId'], 'planSHA256': digest_bytes(plan_path),
            'previewManifestSHA256': plan['previewManifestSHA256'],
            'targetRoot': str(target_root.resolve()), 'projectExternalId': plan['projectExternalId'],
            'files': prepared, 'embed': False,
            'boundary': '仅计划文件创建；禁止覆盖。显式关闭向量嵌入，不使用本地模型。正式MCP读回另行核验。'}


def apply(prepared, plan_path, preview_dir, target_root, receipt_path):
    """Create records only; report pending until separate MCP readback proves indexing."""
    preview_dir, target_root, receipt_path = map(Path, (preview_dir, target_root, receipt_path))
    if prepared.get('state') != 'prepared_not_written' or prepared.get('embed') is not False:
        raise ValueError('必须先准备禁用嵌入的计划')
    if prepare(plan_path, preview_dir, target_root) != prepared:
        raise ValueError('执行前预检与准备的清单不一致')
    if str(target_root.resolve()) != prepared.get('targetRoot') or not target_root.is_dir():
        raise ValueError('目标根目录与计划不一致')
    if receipt_path.exists() or receipt_path.is_symlink():
        raise ValueError('操作回执已存在')
    rows = prepared.get('files')
    if not isinstance(rows, list) or len(rows) != 224:
        raise ValueError('计划范围无效')
    audit = verify_preview(preview_dir)
    if audit['previewId'] != prepared['previewId'] or digest_bytes(preview_dir / 'manifest.json') != prepared['previewManifestSHA256']:
        raise ValueError('预览已变化')
    entries, seen = [], set()
    for row in rows:
        rel = _path(row['destination'])
        if rel in seen:
            raise ValueError('目标路径重复')
        seen.add(rel); _no_symlinks(target_root, rel)
        source = preview_dir / rel.relative_to('soundlog')
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(preview_dir.resolve()):
            raise ValueError('来源文件缺失或越界')
        data = source.read_bytes(); transformed = without_embeddings(data)
        if hashlib.sha256(data).hexdigest() != row['sourceSHA256'] or hashlib.sha256(transformed).hexdigest() != row['writtenSHA256']:
            raise ValueError('源文稿或目标文稿哈希不一致')
        if (target_root / rel).exists() or (target_root / rel).is_symlink():
            raise ValueError('目标存在冲突，未开始写入: ' + str(rel))
        entries.append((row, rel, transformed))
    receipt = {'schemaVersion': 1, 'state': 'writing', 'previewId': prepared['previewId'],
               'planSHA256': prepared['planSHA256'], 'previewManifestSHA256': prepared['previewManifestSHA256'],
               'targetRoot': prepared['targetRoot'], 'projectExternalId': prepared['projectExternalId'],
               'created': [], 'plannedCount': len(entries), 'embed': False}
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive receipt creation before the first file; a failed run stays visible.
    with receipt_path.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2); stream.flush(); os.fsync(stream.fileno())
    try:
        for row, rel, data in entries:
            _no_symlinks(target_root, rel)
            dest = target_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            _no_symlinks(target_root, rel)
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            if digest_bytes(dest) != row['writtenSHA256']:
                raise ValueError('写后文件哈希不一致: ' + str(rel))
            receipt['created'].append({'destination': str(rel), 'sha256': row['writtenSHA256'],
                                       'permalink': row['permalink']})
            write_json(receipt_path, receipt)
        receipt['state'] = 'needs_mcp_readback'
        write_json(receipt_path, receipt)
        return receipt
    except BaseException as exc:
        receipt['state'] = 'interrupted_needs_reconciliation'
        receipt['error'] = type(exc).__name__ + ': ' + str(exc)
        write_json(receipt_path, receipt)
        raise


def verify_readback(receipt, metadata_rows, target_root):
    """Compare every created file with separately obtained MCP metadata.

    The caller must obtain metadata from the configured project's live MCP
    read tool. This function cannot itself prove where supplied metadata came
    from; its result must be kept alongside the live MCP call evidence.
    """
    target_root = Path(target_root)
    if receipt.get('state') not in {'needs_mcp_readback', 'interrupted_needs_reconciliation'}:
        raise ValueError('操作未处于待读回状态')
    if str(target_root.resolve()) != receipt.get('targetRoot'):
        raise ValueError('读回目标不一致')
    if not isinstance(metadata_rows, list):
        raise ValueError('MCP读回记录必须为数组')
    expected = receipt.get('created')
    if not isinstance(expected, list) or not expected:
        raise ValueError('没有可读回的创建记录')
    entries = {row['destination']: row for row in expected}
    if len(entries) != len(expected):
        raise ValueError('创建记录路径重复')
    observed = {}
    for row in metadata_rows:
        path = row.get('file_path') if isinstance(row, dict) else None
        if not isinstance(path, str) or path not in entries or path in observed:
            raise ValueError('MCP读回路径未知或重复')
        observed[path] = row
    matched, missing, changed = [], [], []
    for name, entry in entries.items():
        rel = _path(name); _no_symlinks(target_root, rel)
        path = target_root / rel; row = observed.get(name)
        if not path.is_file() or row is None:
            missing.append(name); continue
        if (digest_bytes(path) != entry['sha256'] or row.get('checksum') != entry['sha256']
                or row.get('permalink') != entry['permalink']):
            changed.append(name); continue
        matched.append(name)
    complete = (len(entries) == receipt.get('plannedCount') and not missing and not changed
                and receipt['state'] == 'needs_mcp_readback')
    return {'state': 'verified' if complete else 'needs_confirmation',
            'expected': receipt.get('plannedCount'), 'created': len(entries), 'matched': len(matched),
            'missing': missing, 'changed': changed,
            'boundary': '每篇目标文件哈希与所提供MCP元数据核对；不证明语义准确或索引的全部检索功能。'}


def reconcile(prepared, receipt, target_root):
    """Report a partial write, including the create-before-journal crash window."""
    target_root = Path(target_root)
    if (prepared.get('state') != 'prepared_not_written'
            or receipt.get('state') != 'interrupted_needs_reconciliation'
            or str(target_root.resolve()) != prepared.get('targetRoot')
            or receipt.get('targetRoot') != prepared.get('targetRoot')
            or receipt.get('previewId') != prepared.get('previewId')):
        raise ValueError('计划、回执或目标不匹配')
    created = {r['destination']: r for r in receipt.get('created', [])}
    categories = {'recorded_match': [], 'unrecorded_match': [], 'missing': [], 'conflict': []}
    for row in prepared['files']:
        rel = _path(row['destination']); _no_symlinks(target_root, rel)
        dest = target_root / rel
        if not dest.exists():
            categories['missing'].append(str(rel)); continue
        if not dest.is_file() or digest_bytes(dest) != row['writtenSHA256']:
            categories['conflict'].append(str(rel)); continue
        registered = created.get(str(rel))
        if registered and registered.get('sha256') == row['writtenSHA256']:
            categories['recorded_match'].append(str(rel))
        else:
            categories['unrecorded_match'].append(str(rel))
    return {'state': 'needs_confirmation', **categories,
            'boundary': '未记录但内容匹配的文件来源不能自动认定；此检查不删除、不重写、不继续写入。'}


def resume(prepared, plan_path, preview_dir, target_root, receipt_path):
    """Resume only recorded matching files; uncertain or changed files block all writes."""
    preview_dir, target_root, receipt_path = map(Path, (preview_dir, target_root, receipt_path))
    receipt = read_json(receipt_path)
    if prepare(plan_path, preview_dir, target_root, permit_existing=True) != prepared:
        raise ValueError('恢复前预检与原计划不一致')
    if (receipt.get('planSHA256') != prepared['planSHA256']
            or receipt.get('previewManifestSHA256') != prepared['previewManifestSHA256']):
        raise ValueError('恢复回执与原计划指纹不一致')
    audit = reconcile(prepared, receipt, target_root)
    if audit['conflict'] or audit['unrecorded_match']:
        raise ValueError('目标冲突或存在未记录文件，拒绝自动恢复')
    recorded = {x['destination']: x for x in receipt['created']}
    if set(recorded) != set(audit['recorded_match']):
        raise ValueError('已记录文件缺失或发生变化，拒绝自动恢复')
    missing = set(audit['missing'])
    receipt['state'] = 'writing'
    receipt.pop('error', None)
    write_json(receipt_path, receipt)
    try:
        for row in prepared['files']:
            if row['destination'] not in missing:
                continue
            rel = _path(row['destination']); _no_symlinks(target_root, rel)
            dest = target_root / rel
            source = preview_dir / rel.relative_to('soundlog')
            data = without_embeddings(source.read_bytes())
            if hashlib.sha256(data).hexdigest() != row['writtenSHA256']:
                raise ValueError('来源文稿发生变化')
            dest.parent.mkdir(parents=True, exist_ok=True); _no_symlinks(target_root, rel)
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            if digest_bytes(dest) != row['writtenSHA256']:
                raise ValueError('写后文件哈希不一致')
            receipt['created'].append({'destination': str(rel), 'sha256': row['writtenSHA256'],
                                       'permalink': row['permalink']})
            write_json(receipt_path, receipt)
        receipt['state'] = 'needs_mcp_readback'; write_json(receipt_path, receipt)
        return receipt
    except BaseException as exc:
        receipt['state'] = 'interrupted_needs_reconciliation'
        receipt['error'] = type(exc).__name__ + ': ' + str(exc)
        write_json(receipt_path, receipt)
        raise
