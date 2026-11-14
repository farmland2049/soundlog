"""Transactional file-level sync simulation, restricted to ignored test storage."""
import json
import os
from pathlib import Path
import re

from .evidence import read_json
from .scenes import digest_bytes
from .store import atomic, write_json
from memory_v2_preview import verify_preview


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SIMULATION_ROOT = PROJECT_ROOT / '记忆库/运行/V2隔离模拟'


def _safe_simulation_root(path):
    allowed_lexical = DEFAULT_SIMULATION_ROOT.absolute()
    lexical = Path(path).absolute()
    if '..' in lexical.parts:
        raise ValueError('隔离模拟路径不能包含父目录跳转')
    project_lexical = PROJECT_ROOT.absolute()
    try:
        allowed_relative = allowed_lexical.relative_to(project_lexical)
    except ValueError:
        raise ValueError('隔离模拟根目录必须位于项目忽略目录内') from None
    item = project_lexical
    for part in allowed_relative.parts:
        item = item / part
        if item.is_symlink():
            raise ValueError('隔离模拟路径不能穿过符号链接')
    try:
        relative = lexical.relative_to(allowed_lexical)
    except ValueError:
        raise ValueError('同步模拟只能写入项目忽略的记忆库/运行/V2隔离模拟/') from None
    item = allowed_lexical
    for part in relative.parts:
        item = item / part
        if item.is_symlink():
            raise ValueError('隔离模拟路径不能穿过符号链接')
    root = lexical.resolve()
    allowed = allowed_lexical.resolve()
    if root == allowed.parent or not root.is_relative_to(allowed):
        raise ValueError('同步模拟只能写入项目忽略的记忆库/运行/V2隔离模拟/')
    return root


def _managed_files(preview_dir):
    preview_dir = Path(preview_dir).resolve()
    files = {}
    for folder in ('sources', 'candidates', 'daily'):
        for source in sorted((preview_dir / folder).rglob('*.md')):
            rel = source.relative_to(preview_dir)
            if source.is_symlink():
                raise ValueError('预览笔记不能是符号链接')
            files[Path('soundlog') / rel] = source
    if not files:
        raise ValueError('预览中没有正式目标笔记')
    return files


def _operation_path(root, preview_id, sequence):
    return root / 'operations' / f'{preview_id}-{sequence:04d}.json'


def apply_preview(preview_dir, simulation_root=DEFAULT_SIMULATION_ROOT, fail_after=None):
    preview_dir = Path(preview_dir).resolve()
    audit = verify_preview(preview_dir)
    root = _safe_simulation_root(simulation_root)
    preview_id = audit['previewId']
    files = _managed_files(preview_dir)
    target = root / preview_id
    if target.is_symlink():
        raise ValueError('模拟目标不能是符号链接')
    conflicts, create, reused = [], [], []
    for rel, source in files.items():
        dest = target / rel
        if dest.is_symlink():
            conflicts.append(str(rel) + ':symbolic-link')
        elif dest.exists():
            if not dest.is_file() or digest_bytes(dest) != digest_bytes(source):
                conflicts.append(str(rel) + ':changed')
            else:
                reused.append(rel)
        else:
            create.append(rel)
    if conflicts:
        raise ValueError('目标存在冲突；未写入任何文件: ' + ', '.join(conflicts[:5]))
    if fail_after is not None and (type(fail_after) is not int or not 1 <= fail_after <= len(create)):
        raise ValueError('故障注入点必须位于本次待创建文件范围内')

    ops = root / 'operations'
    if ops.is_symlink():
        raise ValueError('操作回执目录不能是符号链接')
    ops.mkdir(parents=True, exist_ok=True)
    existing_ops = sorted(ops.glob(preview_id + '-*.json'))
    sequence = len(existing_ops) + 1
    journal_path = _operation_path(root, preview_id, sequence)
    if journal_path.exists():
        raise ValueError('操作回执已存在，拒绝覆盖')
    created, created_dirs = [], set()
    try:
        target.mkdir(parents=True, exist_ok=True)
        for index, rel in enumerate(create, 1):
            dest = target / rel
            if any(parent.is_symlink() for parent in (dest.parent, *dest.parent.parents) if parent != target.parent):
                raise ValueError('目标父目录不能是符号链接: ' + str(rel))
            for parent in [dest.parent, *dest.parent.parents]:
                if parent == target.parent:
                    break
                if not parent.exists():
                    created_dirs.add(parent)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() or dest.is_symlink():
                raise ValueError('写入前目标已变化，拒绝覆盖: ' + str(rel))
            atomic(dest, (preview_dir / rel.relative_to('soundlog')).read_text(encoding='utf-8'))
            created.append(rel)
            if fail_after == index:
                raise OSError('模拟写入中断')
        receipt = {
            'schemaVersion': 1, 'operationId': f'{preview_id}-{sequence:04d}',
            'previewId': preview_id, 'state': 'applied' if created else 'reused', 'target': str(target),
            'createdPaths': [str(p) for p in created], 'reusedPaths': [str(p) for p in reused],
            'fileHashes': {str(rel): digest_bytes(target / rel) for rel in created},
            'sourceManifestSHA256': digest_bytes(preview_dir / 'manifest.json'),
        }
        write_json(journal_path, receipt)
        return {'operationId': receipt['operationId'], 'state': receipt['state'],
                'created': len(created), 'reused': len(reused), 'target': str(target)}
    except BaseException as exc:
        for rel in reversed(created):
            dest = target / rel
            if dest.is_file() and digest_bytes(dest) == digest_bytes(preview_dir / rel.relative_to('soundlog')):
                dest.unlink()
        for folder in sorted(created_dirs, key=lambda p: len(p.parts), reverse=True):
            try:
                folder.rmdir()
            except OSError:
                pass
        failure = {
            'schemaVersion': 1, 'operationId': f'{preview_id}-{sequence:04d}',
            'previewId': preview_id, 'state': 'rolled_back', 'target': str(target),
            'createdPaths': [], 'reusedPaths': [str(p) for p in reused],
            'error': type(exc).__name__ + ': ' + str(exc),
            'rolledBackCount': len(created),
        }
        write_json(journal_path, failure)
        raise


def verify_applied(preview_dir, simulation_root=DEFAULT_SIMULATION_ROOT):
    preview_dir = Path(preview_dir).resolve()
    audit = verify_preview(preview_dir)
    root = _safe_simulation_root(simulation_root)
    target = root / audit['previewId']
    if target.is_symlink():
        raise ValueError('模拟目标不能是符号链接')
    files = _managed_files(preview_dir)
    missing, changed, matched = [], [], 0
    for rel, source in files.items():
        dest = target / rel
        if not dest.is_file() or dest.is_symlink():
            missing.append(str(rel))
        elif digest_bytes(dest) != digest_bytes(source):
            changed.append(str(rel))
        else:
            matched += 1
    return {'previewId': audit['previewId'], 'target': str(target), 'expected': len(files),
            'matched': matched, 'missing': missing, 'changed': changed,
            'readback': 'passed' if not missing and not changed else 'failed'}


def revoke(operation_id, simulation_root=DEFAULT_SIMULATION_ROOT):
    if not isinstance(operation_id, str) or '/' in operation_id or '..' in operation_id:
        raise ValueError('操作编号无效')
    root = _safe_simulation_root(simulation_root)
    operations_dir = root / 'operations'
    if operations_dir.is_symlink():
        raise ValueError('操作回执目录不能是符号链接')
    journal_path = operations_dir / (operation_id + '.json')
    if not journal_path.is_file() or journal_path.is_symlink():
        raise ValueError('操作回执不存在')
    journal = read_json(journal_path)
    if journal.get('operationId') != operation_id or journal.get('state') != 'applied':
        raise ValueError('仅能撤销已应用的操作')
    preview_id = journal.get('previewId')
    if not isinstance(preview_id, str) or not re.fullmatch(r'preview-[a-f0-9]{24}', preview_id):
        raise ValueError('操作回执中的预览编号无效')
    raw_target = Path(journal['target'])
    expected_target = root / preview_id
    if raw_target != expected_target or raw_target.is_symlink():
        raise ValueError('操作回执目标与预览编号不匹配')
    if not raw_target.resolve().is_relative_to(root):
        raise ValueError('操作目标越过模拟根目录')
    if any(parent.is_symlink() for parent in raw_target.parents if parent != root.parent):
        raise ValueError('操作目标路径不能穿过符号链接')
    target = raw_target.resolve()
    # All-or-nothing preflight: never delete files edited after the apply.
    created_paths = journal.get('createdPaths')
    file_hashes = journal.get('fileHashes')
    if (not isinstance(created_paths, list) or not created_paths
            or not all(isinstance(rel, str) for rel in created_paths)
            or len(created_paths) != len(set(created_paths))):
        raise ValueError('撤销回执路径缺失或重复')
    if not isinstance(file_hashes, dict) or set(file_hashes) != set(created_paths):
        raise ValueError('撤销回执文件哈希清单不匹配')
    files = [(target / rel, rel) for rel in created_paths]
    for path, rel in files:
        rel_path = Path(rel)
        if (rel_path.is_absolute() or '..' in rel_path.parts or len(rel_path.parts) < 3
                or rel_path.parts[0] != 'soundlog'
                or rel_path.parts[1] not in ('sources', 'candidates', 'daily')
                or rel_path.suffix != '.md'):
            raise ValueError('撤销记录包含越界文件路径')
        if any(parent.is_symlink() for parent in (path.parent, *path.parent.parents) if parent != target.parent):
            raise ValueError('撤销目标父目录是符号链接: ' + str(rel))
        if not path.is_file() or path.is_symlink():
            raise ValueError('撤销前发现文件缺失或变为符号链接: ' + str(rel))
        if digest_bytes(path) != file_hashes[str(rel)]:
            raise ValueError('撤销前文件内容已改变，拒绝删除: ' + str(rel))
    for path, _ in files:
        path.unlink()
    journal['state'] = 'revoked'
    journal['revokedPaths'] = [str(rel) for _, rel in files]
    write_json(journal_path, journal)
    return {'operationId': operation_id, 'state': 'revoked', 'removed': len(files)}
