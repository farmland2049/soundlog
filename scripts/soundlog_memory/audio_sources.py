"""Optional local recording collectors. Source audio and databases are read-only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from zoneinfo import ZoneInfo
from .store import write_json

AUDIO = {'.mp3', '.wav', '.m4a', '.aac', '.flac'}

def home(root): return Path(root)/'记忆库/运行/自动管线'

def settings(root):
    p=home(root)/'audio-sources.json'
    return json.loads(p.read_text()) if p.exists() else {'voiceMemos':True,'directories':[]}


def save_settings(root, data):
    if set(data)!={'voiceMemos','directories'} or type(data['voiceMemos']) is not bool or not isinstance(data['directories'],list) or len(data['directories'])>30:
        raise ValueError('来源设置格式无效，最多添加30个目录')
    directories=[];project=Path(root).resolve()
    for value in data['directories']:
        if not isinstance(value,str) or not value.strip() or len(value)>4096: raise ValueError('目录不能为空')
        p=Path(value.strip()).expanduser()
        if not p.is_absolute() or p==Path('/') or p.resolve()==Path.home() or p.resolve()==project or p.resolve().is_relative_to(project) or project.is_relative_to(p.resolve()):
            raise ValueError('请指定独立的录音来源目录，不使用根目录、主目录或Soundlog项目目录')
        value=str(p)
        if value not in directories: directories.append(value)
    result={'voiceMemos':data['voiceMemos'],'directories':directories}
    write_json(home(root)/'audio-sources.json',result);return result


def stamp(name):
    match=re.match(r'^(\d{8})[ _-]?(\d{6})(?=$|[ ._-])',name)
    if not match:raise ValueError('无法从名称确定录制开始时间')
    value=''.join(match.groups());datetime.strptime(value,'%Y%m%d%H%M%S');return value


def voice_memos(directory, today):
    directory=Path(directory)
    if not directory.is_dir():return [],[{'source':'voiceMemos','reason':'本机语音备忘录目录不可用'}]
    db=directory/'CloudRecordings.db'
    if not db.is_file():return [],[{'source':'voiceMemos','reason':'语音备忘录元数据不可用'}]
    rows=[];notes=[]
    # Core Data date is seconds since 2001-01-01 UTC, checked against actual local filenames.
    begin=datetime.combine(today,datetime.min.time(),tzinfo=ZoneInfo('Asia/Shanghai'))
    epoch=datetime(2001,1,1,tzinfo=timezone.utc)
    lower=(begin-epoch).total_seconds();upper=(begin+timedelta(days=1)-epoch).total_seconds()
    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=1) as conn:
        conn.execute('pragma query_only=ON')
        for date,path in conn.execute('SELECT ZDATE,ZPATH FROM ZCLOUDRECORDING WHERE ZDATE>=? AND ZDATE<?',(lower,upper)):
            p=Path(path or '')
            if p.is_absolute() or p.name!=str(p) or not p.name:
                notes.append({'source':'voiceMemos','reason':'元数据音频路径不安全'});continue
            source=directory/p
            if source.suffix.lower() not in AUDIO:continue
            local=(epoch+timedelta(seconds=date)).astimezone(ZoneInfo('Asia/Shanghai'))
            # Check metadata vs filename, never replace a conflicting recording clock.
            name=local.strftime('%Y%m%d%H%M%S')
            try:
                if stamp(source.stem)!=name:raise ValueError('录制时间元数据与文件名不一致')
            except ValueError as error:
                notes.append({'source':str(source),'reason':str(error)});continue
            rows.append({'source':str(source),'stamp':name,'collector':'voiceMemos'})
    return rows,notes


def directory_files(directory):
    folder=Path(directory);rows=[];notes=[]
    if not folder.is_dir() or folder.is_symlink():return rows,[{'source':str(folder),'reason':'目录未连接、不可访问或为符号链接'}]
    def onerror(error):notes.append({'source':str(folder),'reason':str(error)})
    for parent,dirs,files in os.walk(folder,followlinks=False,onerror=onerror):
        dirs[:]=[n for n in dirs if not n.startswith('.') and not (Path(parent)/n).is_symlink()]
        for n in sorted(files):
            p=Path(parent)/n
            if n.startswith('.') or p.suffix.lower() not in AUDIO:continue
            try:rows.append({'source':str(p),'stamp':stamp(p.stem),'collector':'directory'})
            except ValueError as e:notes.append({'source':str(p),'reason':str(e)})
    return rows,notes


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def copy_recording(root, item, seen):
    source=Path(item['source']);before=source.stat()
    if source.is_symlink() or not source.is_file():raise ValueError('源文件不是普通文件或为符号链接')
    if before.st_size==0 or time.time()-before.st_mtime<60:raise ValueError('文件为空或仍在写入，稍后再试')
    inbox=Path(root)/'录音/待处理';archive=Path(root)/'录音/已归档';inbox.mkdir(parents=True,exist_ok=True)
    name=item['stamp']+source.suffix.lower();dest=inbox/name
    # A hidden temporary file is never visible to the audio scanner.
    fd,temp=tempfile.mkstemp(prefix='.import-',dir=inbox);temp=Path(temp)
    try:
        digest=hashlib.sha256()
        with os.fdopen(fd,'wb') as out,source.open('rb') as inp:
            for block in iter(lambda:inp.read(1024*1024),b''):digest.update(block);out.write(block)
        after=source.stat()
        if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):raise ValueError('复制过程中源文件发生变化，稍后重试')
        digest=digest.hexdigest()
        prior=seen.get(digest)
        if prior and any((p/prior).is_file() and not (p/prior).is_symlink() and sha(p/prior)==digest for p in (inbox,archive)):
            return {'decision':'duplicate','name':prior,'sha256':digest}
        for folder in (inbox,archive):
            candidate=folder/name
            if candidate.exists() or candidate.is_symlink():
                if candidate.is_symlink() or not candidate.is_file() or sha(candidate)!=digest:raise ValueError('时间戳重名但内容不同，保留源文件且不覆盖')
                seen[digest]=name;return {'decision':'duplicate','name':name,'sha256':digest}
        os.utime(temp,ns=(before.st_atime_ns,before.st_mtime_ns))
        os.link(temp,dest) # Exclusive publish; never overwrite an existing inbox file.
        seen[digest]=name
        return {'decision':'copied','name':name,'sha256':digest}
    finally:temp.unlink(missing_ok=True)


def collect(root, *, memo_directory=None, today=None):
    root=Path(root);config=settings(root);today=today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    memo_directory=memo_directory or Path.home()/'Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings'
    jobs=[]
    if config['voiceMemos']:jobs.append(('voiceMemos',voice_memos,(memo_directory,today)))
    jobs.extend((p,directory_files,(p,)) for p in config['directories'])
    notes=[];candidates=[]
    # Independent read-only discovery runs in parallel; copying is serialized to arbitrate collisions.
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[(label,pool.submit(fn,*args)) for label,fn,args in jobs]
        for label,future in futures:
            try:
                rows,skips=future.result();candidates.extend(rows);notes.extend(skips)
            except (OSError,ValueError,sqlite3.Error) as error:notes.append({'source':label,'reason':str(error)})
    ledger=home(root)/'audio-import-ledger.json'
    seen=json.loads(ledger.read_text()) if ledger.exists() else {}
    outcomes=[]
    for item in candidates:
        try:outcomes.append({**item,**copy_recording(root,item,seen)})
        except (OSError,ValueError) as error:notes.append({'source':item['source'],'reason':str(error)})
    write_json(ledger,seen)
    receipt={'date':today.isoformat(),'copied':sum(x['decision']=='copied' for x in outcomes),'duplicates':sum(x['decision']=='duplicate' for x in outcomes),'skipped':len(notes),'outcomes':outcomes,'notes':notes}
    write_json(home(root)/'audio-import-receipt.json',receipt)
    return receipt
