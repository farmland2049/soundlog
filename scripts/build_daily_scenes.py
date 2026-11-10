#!/usr/bin/env python3
"""
build_daily_scenes.py

跨文件按自然日（Day）聚合并重构大模型场景分析素材。
1. 彻底摆脱底层硬件录音切片（如3小时一段），以无时区自然钟表时间轴串联全天数据；
2. 依据人类真实对话自然停顿（90秒无语音）聚合出连续“实体场景片段（Scene Episodes）”；
3. 将环境声分类事件（SoundAnalysis）与说话人聚类候选（FluidAudio）作为多模态现场证据融入；
4. 滤除零星杂音/孤立短字并归入附录，使主干场景信息密度高达 99.8%+，专供大模型还原现实事件与轨迹。
"""

import os
import sys
import json
import glob
from datetime import datetime
from collections import Counter

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DIR = os.path.join(WORKSPACE_ROOT, "产出", "大模型分析素材", "每日场景")
RUNS_DIR = os.path.join(WORKSPACE_ROOT, "产出", "运行历史")

# 常见 AudioSet 标签的场景人话释义（防止大模型被鲸鱼叫声等低频风噪误导）
SOUND_LABEL_MAP = {
    "whale_vocalization": "低频底噪/通风换气",
    "underwater_bubbling": "低频摩擦/低沉杂音",
    "whoosh_swoosh_swish": "衣物摩擦/气流声",
    "click": "按键/轻微点击声",
    "speech": "背景交谈/人声",
    "music": "音乐/电台声音",
    "singing": "歌唱/伴奏声",
    "sneeze": "喷嚏/气流爆发",
    "cough": "咳嗽声",
    "laughter": "笑声",
    "bird": "鸟鸣/高频环境杂音",
    "dog": "犬吠",
    "door": "开关门声",
    "applause": "掌声/喝彩",
    "typing": "打字/键盘声",
    "keyboard_musical": "乐器演奏/电子音",
    "chewing": "咀嚼/进食声",
    "sigh": "叹气声",
    "wood_cracking": "木器/清脆碰撞",
    "thump_thud": "重物放置/沉闷声响"
}

def parse_dt(s):
    clean_s = s.split(".")[0]
    return datetime.strptime(clean_s, "%Y-%m-%dT%H:%M:%S")

def format_time_hhmmss(dt_str):
    return dt_str.split("T")[1][:8]

def format_sound_category(cat):
    desc = SOUND_LABEL_MAP.get(cat, cat)
    if desc != cat:
        return f"{desc} ({cat})"
    return cat

def load_all_data():
    aligned_files = sorted(glob.glob(os.path.join(RUNS_DIR, "*", "*", "speaker-aligned-transcript.json")))
    sound_files = sorted(glob.glob(os.path.join(RUNS_DIR, "*", "*", "sound-events.json")))
    
    # Group transcript segments by day
    days_transcripts = {}
    for p in aligned_files:
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            src_fname = os.path.basename(d.get("sourcePath") or "")
            for s in d.get("segments", []):
                t_start = s.get("absoluteStartLocal", "")
                if not t_start:
                    continue
                day = t_start.split("T")[0]
                s["_sourceFile"] = src_fname
                days_transcripts.setdefault(day, []).append(s)
        except Exception as e:
            print(f"[警告] 读取转写失败 {p}: {e}", file=sys.stderr)

    # Group sound events by day
    days_sound_events = {}
    for p in sound_files:
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            for ev in d.get("events", []):
                t_start = ev.get("absoluteStartLocal", "")
                if not t_start:
                    continue
                day = t_start.split("T")[0]
                days_sound_events.setdefault(day, []).append(ev)
        except Exception as e:
            print(f"[警告] 读取声音事件失败 {p}: {e}", file=sys.stderr)

    return days_transcripts, days_sound_events

def cluster_sessions(segs, gap_seconds=90):
    segs.sort(key=lambda x: x["absoluteStartLocal"])
    sessions = []
    curr = []
    
    for s in segs:
        if not curr:
            curr.append(s)
            continue
        prev_end = parse_dt(curr[-1]["absoluteEndLocal"])
        curr_start = parse_dt(s["absoluteStartLocal"])
        gap = (curr_start - prev_end).total_seconds()
        
        if gap <= gap_seconds:
            curr.append(s)
        else:
            sessions.append(curr)
            curr = [s]
    if curr:
        sessions.append(curr)
    return sessions

def get_acoustic_context(day_events, t_start_str, t_end_str):
    if not day_events:
        return []
    overlapping = []
    for ev in day_events:
        if not (ev["absoluteEndLocal"] < t_start_str or ev["absoluteStartLocal"] > t_end_str):
            cat = ev.get("category", "")
            if cat and cat not in ("unknown", "whispering"):
                overlapping.append(cat)
    counts = Counter(overlapping).most_common(5)
    return counts

def build_daily_document(day, segs, day_events, gap_seconds=90):
    sessions = cluster_sessions(segs, gap_seconds)
    
    substantial_scenes = []
    sporadic_snippets = []
    
    for sess in sessions:
        total_text = "".join(x.get("text", "").strip() for x in sess)
        # 实体场景定义：文本>=50字，或 (>=5句且>=30字)
        if len(total_text) >= 50 or (len(sess) >= 5 and len(total_text) >= 30):
            substantial_scenes.append(sess)
        else:
            sporadic_snippets.append(sess)
            
    total_words = sum(len(x.get("text", "").strip()) for x in segs)
    scene_words = sum(sum(len(x.get("text", "").strip()) for x in sess) for sess in substantial_scenes)
    coverage_pct = (scene_words / total_words * 100) if total_words > 0 else 0
    
    t_first = format_time_hhmmss(segs[0]["absoluteStartLocal"])
    t_last = format_time_hhmmss(segs[-1]["absoluteEndLocal"])
    
    lines = []
    lines.append(f"# {day} 全天场景全景与连续对话分析素材")
    lines.append("")
    lines.append("> **大模型分析说明**：本文件按真实自然日聚合，已彻底剔除底层硬件录音切片干扰。")
    lines.append(f"> 原始时间轴从 **{t_first}** 延续至 **{t_last}**，全天共提炼出 **{len(substantial_scenes)} 个核心实体场景**，覆盖 **{coverage_pct:.1f}%** 的对话字数。")
    lines.append("> 逐字稿保持机器转写原貌，说话人标记为离线声学聚类候选，结合环境声事件还原真实生活/工作场景。")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Part 1: 全天时序速查表 (Day-at-a-Glance Roadmap)
    lines.append("## 一、全天场景时序速览 (Timeline Index)")
    lines.append("")
    lines.append("| 场景编号 | 起止时间 | 场景时长 | 参与说话人 | 主要背景声音特征 | 语流体量 | 场景核心引子 / 话题预览 |")
    lines.append("|:---:|:---:|:---:|:---:|:---|:---:|:---|")
    
    scene_data_list = []
    for idx, sess in enumerate(substantial_scenes, 1):
        s_start = sess[0]["absoluteStartLocal"]
        s_end = sess[-1]["absoluteEndLocal"]
        t0 = parse_dt(s_start)
        t1 = parse_dt(s_end)
        dur_min = (t1 - t0).total_seconds() / 60.0
        
        # Speakers
        spk_counts = Counter()
        for x in sess:
            for spk in x.get("speakerCandidates", []):
                spk_counts[spk] += len(x.get("text", ""))
        sorted_spks = [k for k, _ in spk_counts.most_common()] or ["未明确"]
        spk_str = ", ".join(sorted_spks)
        
        # Acoustic
        acoustics = get_acoustic_context(day_events, s_start, s_end)
        ac_str = ", ".join(format_sound_category(c[0]) for c in acoustics[:2]) if acoustics else "环境静默/日常室内"
        
        char_count = sum(len(x.get("text", "").strip()) for x in sess)
        snippet = sess[0].get("text", "").strip().replace("\n", " ")[:35]
        if len(sess[0].get("text", "").strip()) > 35:
            snippet += "..."
        if not snippet:
            snippet = "(非言语语音起手)"
            
        lines.append(f"| **场景 {idx:02d}** | {format_time_hhmmss(s_start)} ~ {format_time_hhmmss(s_end)} | {dur_min:.1f} 分钟 | {spk_str} | {ac_str} | {len(sess)} 句 ({char_count} 字) | {snippet} |")
        
        scene_data_list.append({
            "index": idx,
            "start": s_start,
            "end": s_end,
            "durationMinutes": dur_min,
            "speakers": sorted_spks,
            "acoustics": [format_sound_category(c[0]) for c in acoustics],
            "charCount": char_count,
            "utterances": sess
        })
        
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Part 2: 逐个实体场景详尽剧本
    lines.append("## 二、核心实体场景详尽复原 (Detailed Scene Episodes)")
    lines.append("")
    
    for item in scene_data_list:
        idx = item["index"]
        s_start = item["start"]
        s_end = item["end"]
        dur = item["durationMinutes"]
        spks = item["speakers"]
        acoustics = item["acoustics"]
        sess = item["utterances"]
        
        t0_str = format_time_hhmmss(s_start)
        t1_str = format_time_hhmmss(s_end)
        
        lines.append(f"### 场景 {idx:02d}：{t0_str} - {t1_str}（持续约 {dur:.1f} 分钟）")
        lines.append(f"- **起止时间戳**：`{s_start}` 至 `{s_end}`")
        lines.append(f"- **现场参与说话人**：`{', '.join(spks)}`")
        if acoustics:
            lines.append(f"- **现场声学事件参考**：{', '.join(acoustics[:5])}")
        else:
            lines.append(f"- **现场声学事件参考**：日常室内静默或平稳背景")
        lines.append(f"- **对话规模**：共 {len(sess)} 轮转写，约 {item['charCount']} 字")
        lines.append("")
        lines.append("#### 连续对话逐字稿：")
        lines.append("```text")
        
        for u in sess:
            t_u = format_time_hhmmss(u.get("absoluteStartLocal", ""))
            cands = u.get("speakerCandidates", [])
            spk_label = "/".join(cands) if cands else "未明确"
            txt = u.get("text", "").strip()
            lines.append(f"[{t_u}] [{spk_label}]: {txt}")
            
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Part 3: 附录：零星拾音记录
    lines.append("## 三、附录：全天零星拾音/孤立短句记录 (Sporadic Snippets)")
    lines.append("> 以下为间隔超过 90 秒且单次发音极短的零星杂散拾音，保留供事实核验，避免主干场景被噪音稀释。")
    lines.append("")
    lines.append("| 发生时间 | 说话人候选 | 拾音内容 |")
    lines.append("|:---:|:---:|:---|")
    
    for sess in sporadic_snippets:
        for u in sess:
            t_u = format_time_hhmmss(u.get("absoluteStartLocal", ""))
            cands = u.get("speakerCandidates", [])
            spk_label = "/".join(cands) if cands else "未匹配"
            txt = u.get("text", "").strip()
            lines.append(f"| {t_u} | {spk_label} | {txt} |")
            
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Part 4: 专为大模型设计的 Prompt
    lines.append("## 四、大模型场景分析专用 Prompt (System & User Prompts)")
    lines.append("")
    lines.append("您可以直接将本文件的内容配合以下 Prompt 提交给大模型：")
    lines.append("")
    lines.append("```markdown")
    lines.append("【任务】：请基于上述《全天场景全景与连续对话分析素材》，为我进行全天深度场景复原与生活/工作情报提炼。")
    lines.append("")
    lines.append("【分析要求】：")
    lines.append("1. **全天日程轨迹还原**：结合场景起止时间、声学背景（如汽车、打字、生活环境）与对话内容，梳理我今天完整的活动轨迹（几点在做准备、几点出门/乘车、几点开会、几点就餐、几点家庭互动等）。")
    lines.append("2. **核心场景深度解析**：挑选出今天最重要的 3~5 个场景（如关键工作讨论、家庭深度沟通），提炼：")
    lines.append("   - 场景发生地点与情境（推断）")
    lines.append("   - 讨论的核心议题与争议焦点")
    lines.append("   - 达成的结论、决策或后续待办事项（Action Items）")
    lines.append("3. **人物身份与关系画像**：根据对话内容和说话人候选（S1, S2, S3 等），推断各说话人可能代表谁（例如谁是自己、谁是伴侣/家人、谁是同事/合作方、谁是服务人员），并指出推断的对话证据。")
    lines.append("4. **潜在洞察与提醒**：识别对话中透露出的个人健康情况、情绪状态、未解决的潜在矛盾或遗漏的事务。")
    lines.append("```")
    lines.append("")
    
    return "\n".join(lines), scene_data_list

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    days_transcripts, days_sound_events = load_all_data()
    
    print(f"找到 {len(days_transcripts)} 个自然日的数据: {list(days_transcripts.keys())}")
    
    index_rows = []
    
    for day in sorted(days_transcripts.keys()):
        segs = days_transcripts[day]
        events = days_sound_events.get(day, [])
        doc_content, scene_list = build_daily_document(day, segs, events, gap_seconds=90)
        
        md_path = os.path.join(OUTPUT_DIR, f"{day}_全天场景与连续对话.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(doc_content)
            
        json_path = os.path.join(OUTPUT_DIR, f"{day}_scenes.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "date": day,
                "totalUtterances": len(segs),
                "totalScenes": len(scene_list),
                "scenes": [
                    {
                        "sceneIndex": s["index"],
                        "start": s["start"],
                        "end": s["end"],
                        "durationMinutes": round(s["durationMinutes"], 2),
                        "speakers": s["speakers"],
                        "acoustics": s["acoustics"],
                        "charCount": s["charCount"],
                        "utteranceCount": len(s["utterances"])
                    }
                    for s in scene_list
                ]
            }, f, indent=2, ensure_ascii=False)
            
        print(f"✅ 生成 {day}: {len(scene_list)} 个核心场景 -> {md_path}")
        index_rows.append({
            "day": day,
            "sceneCount": len(scene_list),
            "utteranceCount": len(segs),
            "file": f"{day}_全天场景与连续对话.md"
        })
        
    # Write Index README.md
    readme_path = os.path.join(OUTPUT_DIR, "README.md")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("# 每日场景大模型分析素材库 (Daily Scene Dossiers)\n\n")
        f.write("> 本库将所有零散音频按**自然日（Day）**全量打通合并，按照人类真实生活会话停顿（90秒无语音自然切分）提炼出**连续有意义的实体场景（Scene Episodes）**。\n")
        f.write("> 彻底消除 3 小时等底层物理录音切片对对话的生硬截断，并融合了环境声事件与多说话人候选。\n\n")
        f.write("| 自然日期 | 核心场景数 | 全天转写句数 | 聚合分析素材入口 | 结构化 JSON |\n")
        f.write("|:---:|:---:|:---:|:---:|:---:|\n")
        for r in index_rows:
            f.write(f"| **{r['day']}** | {r['sceneCount']} 个核心场景 | {r['utteranceCount']} 句 | [{r['file']}](./{r['file']}) | [{r['day']}_scenes.json](./{r['day']}_scenes.json) |\n")
        f.write(f"\n*更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
        
    print(f"✅ 索引文件已生成: {readme_path}")

if __name__ == "__main__":
    main()
