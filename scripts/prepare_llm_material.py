#!/usr/bin/env python3
"""
将 Soundlog process 的产物整合成供大模型直接消费的结构化原材料。
包含：
1. 复制核心逐字稿与事件时间线
2. 生成统一的 LLM 提示词与分析素材包 (LLM分析素材.md)
3. 维护大模型分析素材总索引 (产出/大模型分析素材/README.md)
"""

import json
import os
import shutil
import sys
from datetime import datetime

def format_seconds(seconds):
    if seconds is None:
        return "未知"
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:05.2f} ({int(seconds)} 秒)"
    return f"{mins:02d}:{secs:05.2f} ({int(seconds)} 秒)"

def parse_filename_time(base_name):
    if len(base_name) == 14 and base_name.isdigit():
        return f"{base_name[:4]}-{base_name[4:6]}-{base_name[6:8]} {base_name[8:10]}:{base_name[10:12]}:{base_name[12:14]}"
    return base_name

def main():
    if len(sys.argv) < 4:
        print("用法: prepare_llm_material.py <运行产物目录> <大模型素材根目录> <录音基准名>")
        sys.exit(1)

    run_output_dir = sys.argv[1]
    llm_root_dir = sys.argv[2]
    base_name = sys.argv[3]

    target_dir = os.path.join(llm_root_dir, base_name)
    os.makedirs(target_dir, exist_ok=True)

    manifest_path = os.path.join(run_output_dir, "run-manifest.json")
    sound_events_path = os.path.join(run_output_dir, "sound-events.json")
    speaker_timeline_path = os.path.join(run_output_dir, "speaker-timeline.json")
    transcript_md_path = os.path.join(run_output_dir, "transcript-with-speaker-candidates.md")
    transcript_txt_path = os.path.join(run_output_dir, "transcript-with-speaker-candidates.txt")

    manifest = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            shutil.copy2(manifest_path, os.path.join(target_dir, "处理清单.json"))
        except Exception as e:
            print(f"[警告] 读取 manifest 失败: {e}")

    sound_events_data = {}
    if os.path.exists(sound_events_path):
        try:
            with open(sound_events_path, "r", encoding="utf-8") as f:
                sound_events_data = json.load(f)
            shutil.copy2(sound_events_path, os.path.join(target_dir, "环境声事件.json"))
        except Exception as e:
            print(f"[警告] 读取 sound_events 失败: {e}")

    speaker_timeline_data = {}
    if os.path.exists(speaker_timeline_path):
        try:
            with open(speaker_timeline_path, "r", encoding="utf-8") as f:
                speaker_timeline_data = json.load(f)
            shutil.copy2(speaker_timeline_path, os.path.join(target_dir, "说话人时间线.json"))
        except Exception as e:
            print(f"[警告] 读取 speaker_timeline 失败: {e}")

    transcript_content = ""
    if os.path.exists(transcript_md_path):
        try:
            with open(transcript_md_path, "r", encoding="utf-8") as f:
                transcript_content = f.read()
            shutil.copy2(transcript_md_path, os.path.join(target_dir, "对话逐字稿_带说话人候选.md"))
        except Exception as e:
            print(f"[警告] 读取 transcript_md 失败: {e}")

    if os.path.exists(transcript_txt_path):
        try:
            shutil.copy2(transcript_txt_path, os.path.join(target_dir, "对话逐字稿_带说话人候选.txt"))
        except Exception as e:
            pass

    # 统计声音事件
    events = sound_events_data.get("events", [])
    event_counts = {}
    event_durations = {}
    for ev in events:
        cat = ev.get("category", "unknown")
        dur = ev.get("endOffsetSeconds", 0) - ev.get("startOffsetSeconds", 0)
        event_counts[cat] = event_counts.get(cat, 0) + 1
        event_durations[cat] = event_durations.get(cat, 0.0) + dur

    top_events = sorted(event_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # 统计说话人
    segments = speaker_timeline_data.get("segments", [])
    speaker_stats = {}
    for seg in segments:
        spk = seg.get("speakerID", "UNKNOWN")
        dur = seg.get("endOffsetSeconds", 0) - seg.get("startOffsetSeconds", 0)
        if spk not in speaker_stats:
            speaker_stats[spk] = {"count": 0, "duration": 0.0}
        speaker_stats[spk]["count"] += 1
        speaker_stats[spk]["duration"] += dur

    duration = manifest.get("audioDurationSeconds") or manifest.get("duration")
    duration_str = format_seconds(duration)
    formatted_start_time = parse_filename_time(base_name)
    source_sha256 = manifest.get("sourceSHA256", "未知")

    # 生成供 LLM 消费的完整材料包
    llm_doc_path = os.path.join(target_dir, "LLM分析素材.md")
    with open(llm_doc_path, "w", encoding="utf-8") as f:
        f.write(f"# 录音大模型分析原材料：{base_name}\n\n")
        f.write("> **说明**：本文档由 Soundlog 本机流水线自动生成，包含绝对钟表时间轴、说话人候选标签、环境声分类事件及完整逐字稿。可用作下游大模型（如 Gemini、Claude、GPT）进行日常总结、主题提炼、角色画像与场景还原的核心素材。\n\n")

        f.write("## 1. 基础元数据\n\n")
        f.write(f"- **录音标识 / 文件名**：`{base_name}`\n")
        f.write(f"- **录音起始时间**：`{formatted_start_time}`\n")
        f.write(f"- **音频总时长**：{duration_str}\n")
        f.write(f"- **音频源哈希 (SHA-256)**：`{source_sha256}`\n")
        f.write(f"- **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        f.write("## 2. 说话人聚类统计\n\n")
        if speaker_stats:
            f.write("| 说话人编号 | 发言片段数 | 累计发言时长 | 占比 |\n")
            f.write("|---|---|---|---|\n")
            total_speech = sum(s["duration"] for s in speaker_stats.values()) or 1.0
            for spk, s in sorted(speaker_stats.items()):
                ratio = (s["duration"] / total_speech) * 100
                f.write(f"| {spk} | {s['count']} 段 | {format_seconds(s['duration'])} | {ratio:.1f}% |\n")
            f.write("\n> *注：说话人编号为单文件内聚类结果，尚未人工绑定真实身份。*\n\n")
        else:
            f.write("未检测到有效说话人片段或该模块已跳过。\n\n")

        f.write("## 3. 声学背景与环境声摘要\n\n")
        if top_events:
            f.write(f"共识别到 **{len(events)}** 次环境声事件，高频类别如下：\n\n")
            f.write("| 环境声音类别 | 出现频次 | 累计时长 |\n")
            f.write("|---|---|---|\n")
            for cat, count in top_events:
                dur = event_durations.get(cat, 0.0)
                f.write(f"| `{cat}` | {count} 次 | {format_seconds(dur)} |\n")
            f.write("\n> *注：环境声音来自 Apple SoundAnalysis 本机声学分类初稿，未作人工核验。完整窗口候选见同目录 `环境声事件.json`。*\n\n")
        else:
            f.write("未记录环境声事件或该模块已跳过。\n\n")

        f.write("## 4. 带说话人候选的完整对话逐字稿\n\n")
        if transcript_content.strip():
            f.write(transcript_content.strip())
            f.write("\n\n")
        else:
            f.write("*(逐字稿为空或转写模块无文本输出)*\n\n")

        f.write("## 5. 建议大模型分析提示词 (Prompt Templates)\n\n")
        f.write("您可以将本文档直接提供给大模型，并附带以下任一 Prompt 进行深度分析：\n\n")
        f.write("### 模板 A：日常事件与纪要梳理\n")
        f.write("```markdown\n")
        f.write("你是一位专业的私人助理与生活记录分析专家。请根据上方录音素材完成以下任务：\n")
        f.write("1. 【核心事件梳理】：按时间顺序概述本次录音中发生的主要互动与关键事件。\n")
        f.write("2. 【要点提炼】：提炼出双方讨论的焦点话题、达成的共识或分歧。\n")
        f.write("3. 【待办与行动项】：列出对话中提到的承诺、约定或需要后续执行的事项。\n")
        f.write("```\n\n")
        f.write("### 模板 B：人物角色与情绪场景洞察\n")
        f.write("```markdown\n")
        f.write("请结合对话逐字稿与环境声事件，对本次录音进行深度场景还原：\n")
        f.write("1. 【角色画像推断】：根据说话人（如 SPEAKER_00 与 SPEAKER_01）的语气、用词和互动方式，推断彼此的角色关系（如家长与孩子、同事、朋友等）。\n")
        f.write("2. 【场景物理环境】：结合检测到的环境音（如笑声、餐具声、脚步声、静音区间），还原对话发生时的物理场景与氛围变化。\n")
        f.write("3. 【情绪脉络】：分析对话过程中各方的心理状态变化（如从争执到讲道理、放松、专注等）。\n")
        f.write("```\n")

    print(f"[完成] 大模型分析素材已汇总至: {target_dir}")
    print(f"       主文档: {llm_doc_path}")

    # 更新总索引 README.md
    index_path = os.path.join(llm_root_dir, "README.md")
    update_index(llm_root_dir, index_path)

def update_index(llm_root_dir, index_path):
    entries = []
    for item in sorted(os.listdir(llm_root_dir)):
        item_dir = os.path.join(llm_root_dir, item)
        if not os.path.isdir(item_dir) or item.startswith("."):
            continue
        doc_path = os.path.join(item_dir, "LLM分析素材.md")
        manifest_path = os.path.join(item_dir, "处理清单.json")
        duration = "未知"
        start_time = parse_filename_time(item)
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    m = json.load(f)
                    duration = format_seconds(m.get("audioDurationSeconds") or m.get("duration"))
            except Exception:
                pass
        has_doc = os.path.exists(doc_path)
        entries.append({
            "name": item,
            "start_time": start_time,
            "duration": duration,
            "has_doc": has_doc,
            "path": f"./{item}/LLM分析素材.md"
        })

    with open(index_path, "w", encoding="utf-8") as f:
        f.write("# 大模型分析素材库 (LLM Materials Index)\n\n")
        f.write("> 本目录收纳所有经 Soundlog 处理完成、可直接喂入大模型（LLM）的结构化素材文件。\n")
        f.write("> 每个子目录包含经过格式归一化的 `LLM分析素材.md`、带说话人候选的完整逐字稿、声学事件与时间线。\n\n")
        f.write("| 录音标识 | 录制开始时间 | 音频时长 | 分析素材入口 |\n")
        f.write("|---|---|---|---|\n")
        for e in entries:
            link = f"[{e['name']}]({e['path']})" if e["has_doc"] else e['name']
            f.write(f"| {link} | {e['start_time']} | {e['duration']} | [查看分析包]({e['path']}) |\n")
        f.write(f"\n*更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")

if __name__ == "__main__":
    main()
