"""Evidence-linked daily navigation, recorded timeline and scene cards."""
from collections import Counter
from pathlib import Path
import re
from .store import write_json

LABELS = {'journal': '生活记录', 'minutes': '讨论纪要', 'actions': '当时事项',
          'child_learning': '儿童学习', 'adult_learning': '成人学习'}


def publish_daily(dest, day, facts, decisions, review=None):
    """Render grounded records; a scene card is one excerpt, not inferred continuity."""
    folder = Path(dest)/day
    scenes = folder/'scenes'; scenes.mkdir(exist_ok=True)
    selected = sorted([f for f in facts if f['date'] == day], key=lambda f: (f['recordedStart'], f['id']))
    by_id = {f['id']: f for f in selected}
    choices = {r['id']: r for r in decisions}
    review = review or {}
    if review:
        if not isinstance(review.get('overview'), str) or not review['overview'].strip():
            raise ValueError('日复盘必须有实际概括')
        highlights = review.get('highlights')
        if not isinstance(highlights, list) or len(set(highlights)) != len(highlights) or any(k not in by_id for k in highlights):
            raise ValueError('日复盘重点须引用当日保留项')
    else:
        highlights = []
    reviewed_scenes=[]
    used_scene_ids=set()
    for scene in review.get('scenes',[]):
        sid=scene.get('id')
        if not isinstance(sid,str) or not re.fullmatch(r'scene-[a-z0-9-]{1,60}',sid) or sid in used_scene_ids:
            raise ValueError('场景编号无效或重复')
        used_scene_ids.add(sid)
        if scene.get('type') not in {'work','life','child_learning','adult_learning'} or not scene.get('title') or not scene.get('summary'):
            raise ValueError('场景模板、标题或摘要缺失')
        ids=scene.get('factIds',[])
        if not ids or len(set(ids))!=len(ids) or any(fid not in by_id for fid in ids):
            raise ValueError('场景必须引用当日保留项')
        if scene['type'] in {'child_learning','adult_learning'} and any(
            scene['type'] not in choices[fid]['categories'] for fid in ids
        ):
            raise ValueError('学习场景不能混用儿童和成人材料')
        for section in scene.get('sections',[]):
            if not section.get('title') or not section.get('text') or not section.get('factIds') or not set(section['factIds'])<=set(ids):
                raise ValueError('场景段落引用越界或缺失')
        card=['# '+scene['title'],'','模板：'+scene['type'],'',scene['summary'],'']
        for section in scene.get('sections',[]):
            card+=['## '+section['title'],'',section['text'],'']
            for fid in section['factIds']:card+=[f'- [对应内容与完整依据]({fid}.md)']
        card+=['','## 关联原文','']
        for fid in ids:
            for e in by_id[fid]['evidence']:
                card += [f"- [原文](../sources.md#{e['id']}) · {e['start']} · `{e['sourceFile']}`"]
        (scenes/(sid+'.md')).write_text('\n'.join(card)+'\n',encoding='utf-8')
        reviewed_scenes.append(scene)
    timeline = []
    lines = ['# '+day+' 录音时间日记', '', '按录音时间排列；不是完整行程。条目可能重叠，条目之间的间隔不代表静默，也不能据此推断活动。', '']
    for f in selected:
        categories = choices[f['id']]['categories']
        item = {'id':f['id'], 'recordedStart':f['recordedStart'], 'recordedEnd':f['recordedEnd'],
                'summary':f['summary'], 'categories':categories,
                'eventTimeText':f.get('eventTimeText'), 'dueText':f.get('dueText'),
                'scene':'scenes/'+f['id']+'.md', 'evidenceIds':[e['id'] for e in f['evidence']]}
        timeline.append(item)
        lines += [f"## {f['recordedStart'][11:]}—{f['recordedEnd'][11:]}", '',
                  f"[{f['summary']}](scenes/{f['id']}.md)", '', '用途：'+'、'.join(LABELS[c] for c in categories), '']
        if f.get('eventTimeText'): lines += ['事件时间原话：'+f['eventTimeText'], '']
        card = ['# 录音内容卡片', '', f['summary'], '', '## 内容与依据', '',
                '本卡对应一条保留内容，不认定为独立会议或连续的完整场景。', '',
                '录音时间：'+f['recordedStart']+'—'+f['recordedEnd'], '',
                '来源类型：'+f.get('sourceMedium','unknown')+'；说话人归属：以匿名原文为准。', '']
        if choices[f['id']].get('notes'):card+=['用户补充：'+choices[f['id']]['notes'], '']
        if 'minutes' in categories: card += ['## 讨论要点', '', f['summary'], '', '结论、分歧和未决事项以原文及明确提炼内容为准，未提到的不补写。', '']
        if 'actions' in categories:card += ['## 当时事项', '', '性质：'+str(f.get('taskState')), '期限原话：'+str(f.get('dueText') or '未提及'), '当前执行状态：未知；不能从缺少后续录音判断尚未完成。', '']
        if any(c.endswith('learning') for c in categories):card += ['## 学习内容', '', '主题与方法按上述摘要记录；教材拼写、专业观点及学习效果尚未独立核实。', '']
        card += ['## 原文', '']
        for e in f['evidence']:
            card += [f"- [定位原文](../sources.md#{e['id']}) · `{e['sourceFile']}` · {e['startOffsetSeconds']}—{e['endOffsetSeconds']}秒", '  > '+e['quote'].replace('\n','\n  > ')]
        (scenes/(f['id']+'.md')).write_text('\n'.join(card)+'\n', encoding='utf-8')
    (folder/'timeline.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    write_json(folder/'timeline.json', {'date':day,'rows':timeline,'boundary':'录音时间不是事件时间；不补充没有证据的活动。'})
    write_json(folder/'scenes.json', {'date':day,'reviewedScenes':reviewed_scenes,'contentCards':timeline,
                                    'boundary':'reviewedScenes为agent整理；单条contentCard不自动视作完整连续场景。'})
    counts = Counter(c for f in selected for c in choices[f['id']]['categories'])
    digest = ['# '+day+' 每日复盘', '', review.get('overview', '本日内容已按时间和用途整理；尚未形成单独的agent日复盘。'), '', '## 本日重点', '']
    if not highlights:digest += ['未单独指定重点，可查看时间日记和分类记录。', '']
    for fid in highlights:digest += [f"- [{by_id[fid]['summary']}](scenes/{fid}.md)"]
    digest += ['', '## 事项与未决信息', '', '[查看录音中的事项](actions.md)。其中的计划与承诺均为录音当时的状态；当前是否完成须查看后续证据。', '',
               '## 来源边界', '', '录音内容依据机器转写和保留项整理。概括采用的其他记录以文中出处为准。媒体观点不自动归于本人，未确定身份和结果保持未知。', '']
    (folder/'daily-review.md').write_text('\n'.join(digest)+'\n', encoding='utf-8')
    write_json(folder/'daily-review.json', {'date':day,'overview':review.get('overview'), 'highlights':highlights,'mode':'agent_overview' if review else 'index_only'})
    overview = ['# '+day+' 每日首页', '', review.get('overview','本日录音内容索引。'), '', '[时间日记](timeline.md) · [每日复盘](daily-review.md) · [原文索引](sources.md)', '', '## 按用途阅读', '']
    overview += [f'- [{label}]({key}.md)：{counts[key]} 条' for key,label in LABELS.items()]
    overview += ['', '## 场景纪要', '']+[f"- [{scene['title']}](scenes/{scene['id']}.md)" for scene in reviewed_scenes]
    overview += ['', f'共 {len(selected)} 条保留内容；多用途条目可出现在多个栏目。', '']
    (folder/'README.md').write_text('\n'.join(overview), encoding='utf-8')
