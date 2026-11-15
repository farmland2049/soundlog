#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge agent development labels and separate human holdout labels without printing them."""
import argparse
import json
import tempfile
from pathlib import Path

from soundlog_memory.evidence import read_json
from soundlog_memory.semantic_gate import prepare_pack, freeze_gold, sha256, _write_once

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_ROOT = (ROOT / '记忆库/运行/语义验收').resolve()
SCENES = ROOT / '产出/大模型分析素材/每日场景-v2'
PRODUCTS = ROOT / '产出/功能提炼'


def private(path):
    path = Path(path).resolve()
    if not path.is_relative_to(PRIVATE_ROOT):
        raise ValueError('输入和输出必须位于本地语义验收目录')
    return path


def merge_and_freeze(*, draft_path, holdout_path, human_path, dev_dir, selection_path,
                     merged_path, frozen_path, scenes_root=SCENES, products_root=PRODUCTS):
    draft_path, holdout_path, human_path, dev_dir, selection_path, merged_path, frozen_path = map(
        private, (draft_path, holdout_path, human_path, dev_dir, selection_path, merged_path, frozen_path))
    if merged_path == frozen_path or merged_path.exists() or frozen_path.exists():
        raise ValueError('输出已存在或路径冲突')
    draft = read_json(draft_path); holdout = read_json(holdout_path); human = read_json(human_path)
    if draft.get('state') != 'annotation_draft' or draft.get('generationStartedAt') is not None:
        raise ValueError('只能合并未开始生成的标注草稿')
    cases = draft['cases']; dev = [c for c in cases if c['holdout'] is False]; held = [c for c in cases if c['holdout'] is True]
    if len(dev) != 16 or len(held) != 8 or holdout.get('cases') != held:
        raise ValueError('留出材料与完整草稿不一致')
    if holdout.get('sourceSnapshotId') != draft['sourceSnapshotId'] or human.get('draftSHA256') != sha256(holdout_path) or human.get('reviewerType') != 'human':
        raise ValueError('人工标注与留出草稿不匹配')
    human_rows = human.get('cases')
    if not isinstance(human_rows, list) or len(human_rows) != 8 or {r['caseId'] for r in human_rows} != {c['caseId'] for c in held}:
        raise ValueError('人工标注未覆盖全部留出案例')
    by_human = {r['caseId']: r['gold'] for r in human_rows}
    expected_files = {c['caseId'] + '.json' for c in dev}
    if {p.name for p in dev_dir.glob('*.json')} != expected_files:
        raise ValueError('开发集标注文件缺失或多余')
    for case in cases:
        if case['holdout']:
            case['gold'] = by_human[case['caseId']]
            case['goldReviewer'] = 'human'
        else:
            label_path = dev_dir / (case['caseId'] + '.json')
            if label_path.is_symlink() or label_path.resolve().parent != dev_dir:
                raise ValueError('开发集标注路径无效')
            label = read_json(label_path)
            if label.get('caseId') != case['caseId'] or label.get('reviewer') != 'current-agent-before-generation':
                raise ValueError('开发集标注与案例或标注来源不一致')
            case['gold'] = label['gold']; case['goldReviewer'] = 'agent'
    PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
    scenes_root = Path(scenes_root).resolve()
    snapshot = Path(draft['sourceSnapshotPath']).resolve()
    if not (snapshot == scenes_root or (snapshot.parent == scenes_root and snapshot.name.startswith('snapshot-'))):
        raise ValueError('草稿来源快照不在场景库内')
    with tempfile.TemporaryDirectory(prefix='.recheck-', dir=PRIVATE_ROOT) as temp:
        check_path = Path(temp) / 'rechecked.json'
        prepare_pack(scenes_root=snapshot, results_root=products_root,
                     selection_file=selection_path, output_file=check_path)
        check = read_json(check_path)
        if (check['sourceSnapshotId'] != draft['sourceSnapshotId'] or
                check['sourceReceiptSHA256'] != draft['sourceReceiptSHA256'] or
                check['selectionSHA256'] != draft['selectionSHA256'] or
                [{k:v for k,v in c.items() if k not in {'gold','goldReviewer'}} for c in cases] !=
                [{k:v for k,v in c.items() if k != 'gold'} for c in check['cases']]):
            raise ValueError('重新校验后的案例与冻结前草稿不一致')
    draft['labelProvenance'] = {'development': 'agent', 'holdout': 'human', 'humanLabelsSHA256': sha256(human_path)}
    _write_once(merged_path, draft)
    result = freeze_gold(merged_path, frozen_path)
    return {'state':result['state'], 'cases':result['cases'], 'holdout':result['holdout'],
            'frozenSHA256':result['frozenSHA256'], 'output':str(frozen_path),
            'boundary':'人工标签来源来自本机表单；工具不能验证评审独立性或此前曝光。'}


def main():
    p=argparse.ArgumentParser(description='合并开发集与人工留出标注并冻结，不显示原文和标注')
    for option in ('draft','holdout','human','dev-dir','selection','merged','frozen'):
        p.add_argument('--'+option, required=True, type=Path)
    a=p.parse_args()
    try:
        result=merge_and_freeze(draft_path=a.draft,holdout_path=a.holdout,human_path=a.human,
             dev_dir=a.dev_dir,selection_path=a.selection,merged_path=a.merged,frozen_path=a.frozen)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,KeyError,TypeError) as e:
        print('合并冻结失败: '+str(e),file=__import__('sys').stderr);return 2

if __name__=='__main__':raise SystemExit(main())
