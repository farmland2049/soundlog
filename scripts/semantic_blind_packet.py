#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create a local generation packet without reference labels or holdout flags."""
import argparse
import json
from pathlib import Path

from soundlog_memory.evidence import read_json
from soundlog_memory.semantic_gate import _write_once, blind_cases, sha256


def build_packet(frozen_path, output_path):
    frozen_path, output_path = Path(frozen_path), Path(output_path)
    frozen = read_json(frozen_path)
    if frozen.get('state') != 'gold_frozen' or not frozen.get('frozenAt'):
        raise ValueError('必须使用已冻结的参考集')
    clean = blind_cases(frozen)
    packet = {'schemaVersion': 1, 'frozenSHA256': sha256(frozen_path),
              'cases': clean}
    _write_once(output_path, packet)
    return {'cases': len(clean), 'packetSHA256': sha256(output_path), 'output': str(output_path)}


def main():
    p = argparse.ArgumentParser(description='由冻结集生成不含标注的本机生成输入')
    p.add_argument('frozen', type=Path)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    try:
        private_root = (Path(__file__).resolve().parent.parent / '记忆库/运行/语义验收').resolve()
        if not args.frozen.resolve().is_relative_to(private_root) or not args.output.resolve().is_relative_to(private_root):
            raise ValueError('输入和输出必须位于本地语义验收目录')
        print(json.dumps(build_packet(args.frozen, args.output), ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        p.exit(2, '生成失败: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
