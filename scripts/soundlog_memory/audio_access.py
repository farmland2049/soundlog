"""Evidence-scoped local audio access and HTTP byte ranges; no audio rewriting."""
import json
import math
import os
from pathlib import Path
import re
from .scenes import resolve_snapshot,digest_bytes

_VERIFIED = set()


def evidence(root, identifier):
    if not re.fullmatch(r'ev-[a-f0-9]{24}',identifier):raise ValueError('原文编号无效')
    snapshot=resolve_snapshot(Path(root)/'产出/大模型分析素材/每日场景-v2')
    receipt=json.loads((snapshot/'receipt.json').read_text())
    for name,sha in receipt['artifacts'].items():
        if not name.endswith('_utterances.json'):continue
        path=snapshot/name
        if digest_bytes(path)!=sha:raise ValueError('原文来源已变化')
        for row in json.loads(path.read_text())['utterances']:
            if row['id']==identifier:return row
    raise ValueError('找不到对应原文')


def open_verified(root, identifier):
    row=evidence(root,identifier);name=row['sourceFile'];archive=Path(root)/'录音/已归档'
    if Path(name).name!=name or not name or '\\' in name:raise ValueError('录音文件名无效')
    # Only the archive is addressable; never accept a browser-supplied filesystem path.
    if archive.is_symlink() or archive.parent.is_symlink() or not archive.resolve().is_relative_to(Path(root).resolve()):raise ValueError('归档目录不能越界或穿过符号链接')
    paths=list(archive.rglob(name)) if archive.is_dir() else []
    for path in paths:
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(archive.resolve()):continue
        # Reject symlinked directories anywhere below the archive.
        parent=path.parent
        while parent!=archive and not parent.is_symlink():parent=parent.parent
        if parent.is_symlink():continue
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0));handle=os.fdopen(fd,'rb')
        stat=os.fstat(handle.fileno());key=(str(path),stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns,row['sourceSHA256'])
        if key not in _VERIFIED:
            import hashlib
            sha=hashlib.sha256()
            for chunk in iter(lambda:handle.read(1024*1024),b''):sha.update(chunk)
            if sha.hexdigest()!=row['sourceSHA256']:handle.close();continue
            _VERIFIED.add(key)
        handle.seek(0);return handle,row,stat.st_size
    raise ValueError('原录音不在已归档目录，或文件与原文来源哈希不符')


def interval(row):
    start=float(row['startOffsetSeconds']);end=float(row['endOffsetSeconds'])
    if not math.isfinite(start) or not math.isfinite(end) or start<0 or end<=start:raise ValueError('原始音频偏移无效')
    return {'start':start,'end':end,'sourceFile':row['sourceFile'],'recordedStart':row['start'],'recordedEnd':row['end']}


def byte_range(header,size):
    if size<=0:raise ValueError('录音文件为空')
    if not header:return 0,size-1,200
    match=re.fullmatch(r'bytes=(\d*)-(\d*)',header)
    if not match or not any(match.groups()):raise ValueError('字节范围无效')
    left,right=match.groups()
    if not left:
        suffix=int(right)
        if suffix<=0:raise ValueError('字节范围无效')
        return max(0,size-suffix),size-1,206
    start=int(left);end=min(int(right),size-1) if right else size-1
    if start>=size or end<start:raise ValueError('字节范围越界')
    return start,end,206
