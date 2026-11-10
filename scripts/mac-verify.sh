#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")/.."
if [[ -f /home/box/opt/swift-env.sh ]]; then . /home/box/opt/swift-env.sh; fi

report="${SOUNDLOG_VERIFY_REPORT:-/tmp/soundlog-mac-verify.md}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$(dirname "$report")" "$work/input"

swift build >"$work/build.log" 2>&1
build_code=$?
swift test >"$work/test.log" 2>&1
test_code=$?

python3 - "$work/input/20261110-120000-synthetic.wav" <<'PY'
import struct, sys, wave
with wave.open(sys.argv[1], "wb") as f:
    f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000)
    f.writeframes(b"\0\0" * 16000)
PY

process_code=0
swift run SoundlogCLI process --input "$work/input" --output-dir "$work/output" --run-dir "$work/output/run" >"$work/process.log" 2>&1 || process_code=$?
manifest="$work/output/run/$(python3 - "$work/input/20261110-120000-synthetic.wav" <<'PY'
import hashlib,sys
print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest()[:16] + "-20261110-120000-synthetic.wav")
PY
)/run-manifest.json"

python3 - "$report" "$work" "$manifest" "$build_code" "$test_code" "$process_code" <<'PY'
import json, os, platform, re, subprocess, sys
report, work, manifest_path, build_code, test_code, process_code = sys.argv[1:]
def read(name):
    try: return open(os.path.join(work, name), encoding="utf-8", errors="replace").read()
    except OSError: return ""
tests = read("test.log")
matches = re.findall(r"Executed (\d+) tests?", tests)
test_count = matches[-1] if matches else "未解析"
try:
    manifest = json.load(open(manifest_path))
    states = manifest.get("modules", {})
except Exception as e:
    states = {"report": {"state": "failed", "error": str(e)}}
swift = subprocess.run(["swift", "--version"], capture_output=True, text=True).stdout.strip().replace("\n", " ")
process_summary = f"退出码 {process_code}；模块状态见下表"
if process_code == '0': process_summary = "通过（退出码 0）"
elif process_code == '1': process_summary = "处理未完全成功（退出码 1）"
elif process_code == '2': process_summary = "命令或平台错误（退出码 2）"
lines = ["# Soundlog 合成验证报告", "", f"- 时间：{__import__('datetime').datetime.now().astimezone().isoformat(timespec='seconds')}", f"- 系统：{platform.platform()}", f"- Swift：{swift}", f"- swift build：{'通过' if build_code == '0' else '失败'}（退出码 {build_code}）", f"- swift test：{'通过' if test_code == '0' else '失败'}（{test_count} 项测试；退出码 {test_code}）", f"- 合成 WAV process：{process_summary}", "", "## 模块状态", "", "| 模块 | 状态 | 原因 |", "|---|---|---|"]
for name, entry in sorted(states.items()):
    error = (entry.get('error') or '').replace('|', r'\|')
    lines.append(f"| {name} | {entry.get('state','unknown')} | {error} |")
lines += ["", "合成输入为 1 秒静音 WAV；未使用真实录音、身份样本或模型。模型缺失时应在对应 Mac 模块状态中记录原因。", ""]
os.makedirs(os.path.dirname(report) or ".", exist_ok=True)
open(report, "w", encoding="utf-8").write("\n".join(lines))
PY

cat "$work/build.log"
cat "$work/test.log"
cat "$work/process.log"
echo "验证报告：$report"
[[ "$build_code" == 0 && "$test_code" == 0 && -f "$report" ]]
