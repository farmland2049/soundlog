#!/usr/bin/env python3
"""Rank four-function material blocks by configurable value signals; offline, read-only for materials."""
import argparse
import json
import re
import sys
from pathlib import Path

from soundlog_memory.products import load_request

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = {
    'version': 'block-priority-v1',
    'patterns': {
        'todo': {'pattern': r'明天|下午|晚上|一会|等会|待会|下单|预约|买|充电|交费|拿回|给你买|帮你|安排|记得|别忘了|弄好|回去|送|取', 'weight': 2},
        'decision': {'pattern': r'决定|定了吧|就这个|就买|确认|确定|同意|选这个|那就|行吧|好了就|定了', 'weight': 2},
        'price': {'pattern': r'\d+元|多少钱|价格|贵|便宜|打折|优惠|抵扣|到账', 'weight': 2},
        'medical': {'pattern': r'手术|出院|住院|药|医院|医生|复诊|检查|疗|挂号|陪护|养老院', 'weight': 2},
        'time': {'pattern': r'2027|明年|五一|春节|早上|中午|傍晚|几点|号|\d+日|\d+月', 'weight': 1},
        'knowledge': {'pattern': r'原理|方法|问题在于|为什么|因为|所以|意思是|概念|逻辑|知识|学', 'weight': 1}
    },
    'thresholds': {'high': 25, 'medium': 12},
    'notes': '阈值与权重可在此文件修改；score只是待读优先级，不代表确认价值或身份。'
}


def load_config(path):
    if path is None or not path.exists():
        return dict(DEFAULT_CONFIG)
    raw = json.loads(path.read_text())
    config = dict(DEFAULT_CONFIG)
    config.update(raw)
    if not isinstance(config['patterns'], dict) or not isinstance(config['thresholds'], dict):
        raise ValueError('配置patterns/thresholds无效')
    for name, rule in config['patterns'].items():
        re.compile(rule['pattern'])
        if not isinstance(rule.get('weight', 1), (int, float)):
            raise ValueError('权重须为数字: ' + name)
    return config


def read_done_keys(path):
    if path is None:
        return set()
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return set(data)
    if isinstance(data, dict):
        if isinstance(data.get('processedChunks'), list):
            return set(data['processedChunks'])
        if isinstance(data.get('results'), list):
            return {row.get('key') for row in data['results'] if isinstance(row, dict) and isinstance(row.get('key'), str)}
    raise ValueError('done文件须为块编号数组、含processedChunks数组或combine结果文件')


def main(argv=None):
    p = argparse.ArgumentParser(description='按可配置信号词给功能提炼块排序；只读材料，不调用模型')
    p.add_argument('--root', type=Path, default=ROOT / '产出/功能提炼')
    p.add_argument('--request', required=True)
    p.add_argument('--config', type=Path, help='优先级配置JSON；缺省用内置规则')
    p.add_argument('--done-from', type=Path, help='已完成块清单；块编号数组或combine回执')
    p.add_argument('--output', type=Path, help='输出JSON；不指定时只打印摘要')
    args = p.parse_args(argv)

    request = load_request(str(args.root), args.request)
    config = load_config(args.config)
    done = read_done_keys(args.done_from)
    thresholds = config['thresholds']
    rows, done_rows = [], []
    for item in request['items']:
        text = ''.join(e['text'] for e in item['material']['utterances'])
        hits, score = {}, 0
        for name, rule in config['patterns'].items():
            count = len(re.findall(rule['pattern'], text))
            if count:
                hits[name] = count
                score += count * rule.get('weight', 1)
        row = {'key': item['key'], 'date': item['date'], 'score': score,
               'utteranceCount': len(item['material']['utterances']), 'charCount': len(text), 'hits': hits}
        (done_rows if item['key'] in done else rows).append(row)
    rows.sort(key=lambda r: (-r['score'], r['key']))
    buckets = {'high': [], 'medium': [], 'low': []}
    for row in rows:
        if row['score'] >= thresholds['high']:
            buckets['high'].append(row)
        elif row['score'] >= thresholds['medium']:
            buckets['medium'].append(row)
        else:
            buckets['low'].append(row)
    result = {
        'requestId': args.request, 'generatedAt': __import__('datetime').datetime.now().astimezone().isoformat(),
        'config': config, 'doneFrom': str(args.done_from) if args.done_from else None,
        'totalBlocks': len(request['items']), 'doneBlocks': len(done_rows), 'remainingBlocks': len(rows),
        'counts': {k: len(v) for k, v in buckets.items()},
        'buckets': buckets, 'doneKeys': sorted(done_rows, key=lambda r: r['key'])
    }
    if args.output:
        if args.output.exists():
            raise ValueError('输出已存在，拒绝覆盖: ' + str(args.output))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = {'totalBlocks': result['totalBlocks'], 'doneBlocks': result['doneBlocks'],
               'remainingBlocks': result['remainingBlocks'], 'counts': result['counts'],
               'top': [{'key': r['key'], 'score': r['score'], 'hits': r['hits']} for r in buckets['high'][:10]]}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('块优先级排序失败: ' + str(exc), file=sys.stderr)
        sys.exit(2)
