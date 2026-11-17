"""Durable local ingestion, agent handoff and evidence-linked delivery bundles."""
import fcntl
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from .products import export_request, import_result, load_request
from .reading import load_verified_result
from .scenes import resolve_snapshot, digest_bytes
from .store import write_json
from .daily_delivery import publish_daily

CATEGORIES = {'journal': '每日记录', 'minutes': '讨论纪要', 'actions': '录音中的事项',
              'child_learning': '儿童学习与陪伴', 'adult_learning': '成人学习与知识'}
AUDIO = {'.mp3', '.wav', '.m4a', '.aac', '.flac'}


class Pipeline:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.home = self.root / '记忆库/运行/自动管线'
        self.products = self.root / '产出/功能提炼'
        self.scenes = self.root / '产出/大模型分析素材/每日场景-v2'
        self.delivery = self.root / '产出/自动交付'
        self.home.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def lock(self):
        with (self.home / 'pipeline.lock').open('a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('另一个管线操作正在进行')
            yield

    def state(self):
        path = self.home / 'state.json'
        return json.loads(path.read_text()) if path.exists() else {'schemaVersion': 1, 'state': 'idle', 'dayHashes': {}}

    def save(self, state):
        write_json(self.home / 'state.json', state)
        return state

    def inventory(self):
        inbox = self.root / '录音/待处理'
        return sorted(p for p in inbox.iterdir() if p.is_file() and p.suffix.lower() in AUDIO) if inbox.exists() else []

    def start(self):
        """One entry for the calling agent; idle audio does not mean all work is done."""
        files = [p.name for p in self.inventory()]
        state = self.tick()
        questions = []
        for path in sorted((self.home/'questions').glob('question-*/request.json')):
            if (path.parent/'answer.json').exists(): continue
            request = json.loads(path.read_text())
            questions.append({'id': path.parent.name, 'question': request['question'], 'directory': str(path.parent)})
        remaining = [p.name for p in self.inventory()]
        complete = state['state'] == 'idle' and not remaining and not questions
        return {**state, 'checkedAudioFiles': files, 'remainingAudioFiles': remaining,
                'pendingQuestions': questions, 'complete': complete,
                'agentInstructions': str(self.root/'scripts/pipeline-agent.md'),
                'execution': 'current_agent',
                'boundary': '脚本处理本机确定性阶段；当前agent须继续提炼、筛选、派生交付及问题回答，不能把单步返回当全流程完成。'}

    def tick(self):
        with self.lock():
            state = self.state()
            # Resume semantic work before accepting more input into this job.
            if state['state'] in {'awaiting_agent', 'awaiting_screening', 'awaiting_enrichment'}:
                return state
            files = self.inventory()
            if any(p.is_symlink() or not re.fullmatch(r'\d{14}', p.stem) for p in files):
                raise ValueError('待处理文件含符号链接或非14位时间戳名称，请检查')
            if any(time.time() - p.stat().st_mtime < 60 for p in files):
                return {'state': 'waiting_for_stable_files', 'files': [p.name for p in files]}
            if files:
                if not any(os.access(self.root / path, os.X_OK) for path in ('.build/release/SoundlogCLI', '.build/debug/SoundlogCLI')):
                    raise ValueError('现有音频执行程序不可用；停止，不自动安装或构建依赖')
                self.save({**state, 'state': 'processing_audio', 'files': [p.name for p in files]})
                log = self.home / 'audio.log'
                with log.open('a') as out:
                    result = subprocess.run(['bash', 'scripts/process-inbox.sh'], cwd=self.root, stdout=out, stderr=out)
                if result.returncode:
                    self.save({**state, 'state': 'audio_failed', 'log': str(log)})
                    raise ValueError('音频处理失败，详见 audio.log；下次重试复用已有产物')
            elif state['state'] in {'processing_audio', 'audio_failed'}:
                # Originals may already be archived when aggregation was interrupted.
                with (self.home / 'audio.log').open('a') as out:
                    result = subprocess.run(['python3', 'scripts/build_daily_scenes.py'], cwd=self.root, stdout=out, stderr=out)
                if result.returncode:
                    raise ValueError('归档后的场景重建失败，见 audio.log')
            if not (self.scenes / 'latest.json').exists():
                return self.save({**state, 'state': 'idle'})
            snapshot = resolve_snapshot(self.scenes)
            sr = json.loads((snapshot / 'receipt.json').read_text())
            if sr['state'] != 'completed':
                raise ValueError('来源快照未完成')
            hashes = {n[:10]: sha for n, sha in sr['artifacts'].items() if n.endswith('_utterances.json')}
            days = sorted(d for d, sha in hashes.items() if state.get('dayHashes', {}).get(d) != sha)
            if not days:
                return self.save({**state, 'state': 'idle'})
            request = export_request(snapshot, self.products, days=days)
            state = {**state, 'state': 'awaiting_agent', 'requestId': request['requestId'],
                     'snapshotId': sr['snapshotId'], 'pendingDayHashes': hashes, 'days': days,
                     'requestDirectory': request['directory']}
            return self.save(state)

    def ingest(self, envelope):
        with self.lock():
            state = self.state()
            if state['state'] != 'awaiting_agent' or envelope.get('requestId') != state['requestId']:
                raise ValueError('结果不匹配当前待处理请求')
            request = load_request(self.products, state['requestId'])
            if {r['key'] for r in envelope['results']} != {r['key'] for r in request['items']}:
                raise ValueError('必须覆盖全部材料块，不能将部分输出标作完成')
            receipt = import_result(self.products, envelope)
            if receipt['state'] != 'completed':
                raise ValueError('导入结果未完成')
            return self.save({**state, 'state': 'awaiting_screening', 'resultId': receipt['resultId']})

    def publish(self, rid, screening, *, adopt=False):
        with self.lock():
            state = self.state()
            if adopt and state['state'] not in {'idle'}:
                raise ValueError('存在未完成管线任务，不能采用历史基线')
            if not adopt and (state['state'] != 'awaiting_screening' or state['resultId'] != rid):
                raise ValueError('结果不匹配当前筛选阶段')
            receipt, facts = load_verified_result(self.products, rid)
            if receipt['state'] != 'completed' or screening.get('resultId') != rid:
                raise ValueError('完整结果与筛选清单不一致')
            rows = screening.get('rows', [])
            if len(rows) != len(facts) or {r['id'] for r in rows} != {f['id'] for f in facts}:
                raise ValueError('筛选须逐项覆盖全部候选且无重复')
            if not isinstance(screening.get('reviewer'), str) or not screening['reviewer'].strip():
                raise ValueError('筛选必须说明实际处理者')
            known = {f['id']: f for f in facts}
            for r in rows:
                if 'notes' in r and not isinstance(r['notes'], str):
                    raise ValueError('补充说明须为文本')
                if r.get('decision') not in {'retain', 'defer'} or not isinstance(r.get('reason'), str) or not r['reason'].strip():
                    raise ValueError('每项须有保留/暂缓决策和理由')
                if r['decision'] == 'retain':
                    categories = r.get('categories')
                    if not isinstance(categories, list) or not categories or any(c not in CATEGORIES for c in categories) or len(set(categories)) != len(categories):
                        raise ValueError('保留项须有明确交付分类')
                    f = known[r['id']]
                    allowed = set(f['functionUses']) - {'learning'}
                    if 'learning' in f['functionUses']:
                        allowed |= {'child_learning', 'adult_learning'}
                    if not set(categories) <= allowed:
                        raise ValueError('交付分类不得超出原始功能用途')
            # Source metadata is immutable; check each cited quote against its snapshot.
            snapshot = resolve_snapshot(Path(receipt['sourceSnapshot']))
            sr = json.loads((snapshot / 'receipt.json').read_text())
            if sr['snapshotId'] != receipt['sourceSnapshotId']:
                raise ValueError('结果来源快照不一致')
            evidence = {}
            for name, sha in sr['artifacts'].items():
                if name.endswith('_utterances.json'):
                    path = snapshot / name
                    if digest_bytes(path) != sha:
                        raise ValueError('原文工件已改变')
                    evidence.update({e['id']: e for e in json.loads(path.read_text())['utterances']})
            for f in facts:
                for e in f['evidence']:
                    original = evidence.get(e['id'])
                    if not original or not e['quote'] or e['quote'] not in original['text'] or any(e[k] != original[k] for k in ('sourceFile', 'sourceSHA256', 'start', 'end', 'startOffsetSeconds', 'endOffsetSeconds')):
                        raise ValueError('候选引文与原始来源不符')
            identity = hashlib.sha256((json.dumps(screening, sort_keys=True, ensure_ascii=False) + digest_bytes(Path(__file__)) + digest_bytes(Path(__file__).with_name('daily_delivery.py'))).encode()).hexdigest()[:24]
            final = self.delivery / ('bundle-' + identity)
            self.delivery.mkdir(parents=True, exist_ok=True)
            dest = Path(tempfile.mkdtemp(prefix='.building-', dir=self.delivery))
            write_json(dest / 'screening.json', screening)
            retained = [{**known[r['id']], 'reviewNotes': r.get('notes', ''), 'selectedCategories':r['categories']}
                        for r in rows if r['decision'] == 'retain']
            write_json(dest / 'search.json', {'facts': retained, 'sourceResultId': rid})
            days = sorted({name[:10] for name in receipt['artifacts'] if re.fullmatch(r'\d{4}-\d{2}-\d{2}_journal\.md', name)})
            for day in days:
                folder = dest / day; folder.mkdir(exist_ok=True)
                sources = ['# 原文证据索引', '']
                day_evidence = {e['id']: e for f in retained if f['date'] == day for e in f['evidence']}
                for eid, e in sorted(day_evidence.items(), key=lambda pair: pair[1]['start']):
                    sources += [f'<a id="{eid}"></a>', f"## {e['start']} — {e['end']}",
                                f"`{e['sourceFile']}` · {e['startOffsetSeconds']}—{e['endOffsetSeconds']} 秒 · `{eid}`", '', '> ' + e['text'].replace('\n', '\n> '), '']
                (folder / 'sources.md').write_text('\n'.join(sources), encoding='utf-8')
                source_html = ['<!doctype html><meta charset="utf-8"><title>原文回查</title>']
                for eid, e in sorted(day_evidence.items(), key=lambda pair: pair[1]['start']):
                    source_html += [f'<section id="{eid}"><h2>{html.escape(e["start"])}</h2>',
                                    '<p>' + html.escape(e['sourceFile']) + ' · ' + str(e['startOffsetSeconds']) + ' 秒</p>',
                                    '<pre style="white-space:pre-wrap">' + html.escape(e['text']) + '</pre></section>']
                (folder / 'sources.html').write_text('\n'.join(source_html), encoding='utf-8')
                for category, title in CATEGORIES.items():
                    lines = ['# ' + day + ' ' + title, '', '基于机器转写的内容整理；观点按话语记录，身份与实际结果另行核实。', '']
                    if category == 'actions':
                        lines += ['这里记录的是录音当时的请求、意向或承诺；不等于当前仍未完成。', '']
                    for r in rows:
                        if r['decision'] != 'retain' or category not in r['categories']: continue
                        f = known[r['id']]
                        if f['date'] != day: continue
                        lines += [f"## {f['recordedStart']}", '', f['summary'], '']
                        if r.get('notes'):
                            lines += ['补充说明：' + r['notes'], '']
                        if category == 'actions': lines += [f"- 当时性质：{f.get('taskState')}；期限原话：{f.get('dueText') or '未提及'}。"]
                        for e in f['evidence']:
                            lines += [f"- [原文定位](sources.md#{e['id']}) · `{e['sourceFile']}` · {e['startOffsetSeconds']} 秒", '  > ' + e['quote'].replace('\n', '\n  > ')]
                        lines.append('')
                    (folder / (category + '.md')).write_text('\n'.join(lines), encoding='utf-8')
            for day in days:
                publish_daily(dest, day, retained, rows, screening.get('dailyReviews', {}).get(day))
            page = '''<!doctype html><meta charset="utf-8"><title>Soundlog 交付检索</title><h1>录音内容检索</h1><p>关键词检索；点击原文定位回查。历史事项不代表当前待办。</p><input id="q" aria-label="关键词"><button id="go">搜索</button><div id="out"></div><script>const data=DATA;function run(){let q=document.querySelector('#q').value.trim(),out=document.querySelector('#out');out.replaceChildren();if(!q)return;for(let f of data){if(![f.summary,...f.evidence.map(e=>e.quote)].some(t=>t.includes(q)))continue;let p=document.createElement('p');p.textContent=f.date+' '+f.summary+(f.reviewNotes?' '+f.reviewNotes:'');out.append(p);for(let e of f.evidence){let a=document.createElement('a');a.textContent=e.start+' 原文定位';a.href=f.date+'/sources.html#'+e.id;out.append(a,document.createElement('br'));}}if(!out.childNodes.length)out.textContent='未找到匹配内容。'}document.querySelector('#go').onclick=run;</script>'''
            # Escape script delimiters in untrusted transcript text; DOM uses textContent.
            page = page.replace('DATA', json.dumps(retained, ensure_ascii=False).replace('<', '\\u003c'))
            (dest / 'index.html').write_text(page, encoding='utf-8')
            index = ['# 本批录音交付', '', '[关键词检索](index.html)', '']
            for day in days:
                index += ['## ' + day, '', f'[每日首页]({day}/README.md) · [时间日记]({day}/timeline.md) · [每日复盘]({day}/daily-review.md)', ''] + [f'- [{title}]({day}/{key}.md)' for key, title in CATEGORIES.items()] + ['']
            (dest / 'README.md').write_text('\n'.join(index), encoding='utf-8')
            artifacts = {str(p.relative_to(dest)): digest_bytes(p) for p in dest.rglob('*') if p.is_file() and p.name != 'receipt.json'}
            result = {'state': 'completed', 'resultId': rid, 'bundle': final.name, 'retained': len(retained),
                      'deferred': len(facts)-len(retained), 'days': days, 'artifacts': artifacts,
                      'boundary': '仅本地交付；筛选由所标明agent完成，不代表独立验收或身份确认。'}
            write_json(dest / 'receipt.json', result)
            if final.exists():
                old = json.loads((final / 'receipt.json').read_text())
                if old != result or any(digest_bytes(final / name) != sha for name,sha in old['artifacts'].items()):
                    shutil.rmtree(dest)
                    raise ValueError('已有交付包发生变化，拒绝覆盖')
                shutil.rmtree(dest)
            else:
                os.rename(dest, final)
            dest = final
            catalog_path = self.delivery / 'catalog.json'
            catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else {'days': {}}
            for day in days: catalog['days'][day] = dest.name
            library = []
            for day, bundle in sorted(catalog['days'].items()):
                prior = self.delivery / bundle
                prior_receipt = json.loads((prior / 'receipt.json').read_text())
                if digest_bytes(prior / 'search.json') != prior_receipt['artifacts']['search.json']:
                    raise ValueError('历史交付检索工件已改变')
                library.extend({**f, 'deliveryBundle': bundle} for f in json.loads((prior / 'search.json').read_text())['facts'] if f['date'] == day)
            old_data = json.dumps(retained, ensure_ascii=False).replace('<', '\\u003c')
            new_data = json.dumps(library, ensure_ascii=False).replace('<', '\\u003c')
            library_page = page.replace(old_data, new_data).replace("a.href=f.date+", "a.href=f.deliveryBundle+'/'+f.date+")
            from .store import atomic
            atomic(self.delivery / 'index.html', library_page)
            write_json(catalog_path, catalog)
            write_json(self.delivery / 'latest.json', result)
            atomic(self.delivery / 'README.md', '# Soundlog 交付入口\n\n[全部已交付日期检索](index.html) · [跨天事项线索账本](actions.md)\n\n' + '\n'.join(f'- [{day}]({bundle}/{day}/README.md)' for day,bundle in sorted(catalog['days'].items())) + '\n')
            from .library_tools import task_ledger
            task_ledger(self.delivery)
            hashes = state.get('pendingDayHashes')
            if adopt:
                hashes = {n[:10]: sha for n,sha in sr['artifacts'].items() if n.endswith('_utterances.json')}
            self.save({'schemaVersion': 1, 'state': 'idle' if adopt else 'awaiting_enrichment',
                       'dayHashes': hashes or state.get('dayHashes', {}), 'lastBundle': dest.name,
                       'resultId':rid})
            return result

    def finish_products(self, spec, links):
        """A new batch is complete only after reviewed B/D/E derivatives are built."""
        from .derived_products import publish_derived
        from .task_graph import publish_task_graph
        with self.lock():
            state=self.state()
            if state['state']!='awaiting_enrichment':
                raise ValueError('当前任务不在产品扩展阶段')
            if spec.get('sourceResultId')!=state['resultId']:
                raise ValueError('派生方案未绑定当前结果')
            products=publish_derived(self.delivery,spec,self.scenes)
            features_home=self.root/'记忆库/运行/产品功能'
            graph=publish_task_graph(self.delivery,features_home,links)
            write_json(features_home/'derived-spec.json',spec)
            write_json(features_home/'task-links.json',links)
            self.save({**state,'state':'idle','lastProducts':products['id'],'lastTaskVersion':graph['version']})
            return {'state':'completed','products':products['id'],'taskVersion':graph['version']}
