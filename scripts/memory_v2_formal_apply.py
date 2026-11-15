#!/usr/bin/env python3
"""Create the approved two-day pilot; success still requires MCP readback.

This is a consequential command. It must only be run after the user explicitly
authorizes this exact prepared plan. It never invokes a local model.
"""
import argparse
import json
from pathlib import Path
import sys

from memory_v2_formal_prepare import PRIVATE, ROOT, TARGET, validate_live_state
from soundlog_memory.evidence import read_json
from soundlog_memory.formal_sync import apply, validate_mcp_preflight
from soundlog_memory.scenes import digest_bytes

def main():
    p = argparse.ArgumentParser(description='执行明确授权的两日试点；结果必须另做MCP读回')
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--prepared', type=Path, required=True)
    p.add_argument('--preview', type=Path, required=True)
    p.add_argument('--mcp-preflight', type=Path, required=True)
    p.add_argument('--receipt', type=Path, required=True)
    p.add_argument('--approved-prepared-sha256', required=True,
                   help='用户明确授权的准备清单SHA-256')
    args = p.parse_args()
    try:
        if not args.plan.resolve().is_relative_to((ROOT / '产出').resolve()):
            raise ValueError('计划必须位于项目私有产出目录')
        for path in (args.prepared, args.preview, args.mcp_preflight, args.receipt):
            if not path.resolve().is_relative_to(PRIVATE):
                raise ValueError('预览、预检、回执均须位于项目私有运行目录')
        if digest_bytes(args.prepared) != args.approved_prepared_sha256:
            raise ValueError('授权的清单哈希不匹配')
        prepared, proof = read_json(args.prepared), read_json(args.mcp_preflight)
        if not prepared.get('projectExternalId') or Path(prepared.get('targetRoot', '')).resolve() != TARGET.resolve():
            raise ValueError('项目或正式目标路径不匹配')
        validate_live_state(args.preview)
        validate_mcp_preflight(proof, prepared)
        receipt = apply(prepared, args.plan, args.preview, TARGET, args.receipt)
        print(json.dumps({'state': receipt['state'], 'created': len(receipt['created']),
                          'receipt': str(args.receipt),
                          'boundary': '文件已创建，须逐篇MCP读回；此状态不代表正式接入完成。'}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('正式试点未完成: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
