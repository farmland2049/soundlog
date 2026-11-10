#!/usr/bin/env bash
set -uo pipefail

# 切换到项目根目录
cd "$(dirname "$0")/.."

INBOX_DIR="录音/待处理"
ARCHIVE_DIR="录音/已归档"
RAW_OUTPUT_DIR="产出/运行历史"
LLM_OUTPUT_DIR="产出/大模型分析素材"

is_mock=0
is_dry_run=0
extra_params=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mock)
            is_mock=1
            extra_params+=("--param" "engines=mock")
            shift
            ;;
        --dry-run)
            is_dry_run=1
            shift
            ;;
        --help|-h)
            echo "用法: $0 [--mock] [--dry-run] [--param key=value ...]"
            echo ""
            echo "说明:"
            echo "  检查 录音/待处理/ 目录，如果有待处理录音文件则逐一调用 SoundlogCLI 处理。"
            echo "  处理成功后自动将源文件移动到 录音/已归档/ 目录，并将产物汇总至 产出/大模型分析素材/。"
            echo ""
            echo "选项:"
            echo "  --mock      开启 Mock 假引擎模式（仅校验格式与时长，快速验证流程）"
            echo "  --dry-run   仅检查并列出待处理文件，不实际启动处理"
            echo "  --param ... 传递给 SoundlogCLI process 的附加参数"
            exit 0
            ;;
        *)
            extra_params+=("$1")
            shift
            ;;
    esac
done

mkdir -p "$INBOX_DIR" "$ARCHIVE_DIR" "$RAW_OUTPUT_DIR" "$LLM_OUTPUT_DIR"

# 扫描待处理音频文件
audio_files=()
while IFS= read -r -d '' f; do
    audio_files+=("$f")
done < <(find "$INBOX_DIR" -maxdepth 1 -type f \( -iname "*.mp3" -o -iname "*.wav" -o -iname "*.m4a" -o -iname "*.aac" -o -iname "*.flac" \) -print0 | sort -z)

total_count=${#audio_files[@]}

if [[ $total_count -eq 0 ]]; then
    echo "=================================================="
    echo "【Soundlog 录音消费流水线】"
    echo "状态：未发现待处理的录音文件。"
    echo "收件箱目录：$INBOX_DIR/"
    echo "提示：请将待分析录音（文件名为 14 位时间戳，如 20261110190000.mp3）放入上述目录后重新运行本脚本。"
    echo "=================================================="
    exit 0
fi

echo "=================================================="
echo "【Soundlog 录音消费流水线】"
echo "发现待处理录音文件共 $total_count 个："
for idx in "${!audio_files[@]}"; do
    echo "  $((idx+1)). $(basename "${audio_files[$idx]}")"
done
echo "=================================================="

if [[ $is_dry_run -eq 1 ]]; then
    echo "[dry-run] 模式已开启，不执行实际分析。退出。"
    exit 0
fi

success_count=0
failure_count=0
skipped_count=0

for idx in "${!audio_files[@]}"; do
    file="${audio_files[$idx]}"
    filename=$(basename "$file")
    base_name="${filename%.*}"
    current_num=$((idx+1))

    echo ""
    echo "--------------------------------------------------"
    echo "[$current_num/$total_count] 正在处理: $filename"
    echo "--------------------------------------------------"

    # 校验 14 位时间戳命名规范
    if ! [[ "$base_name" =~ ^[0-9]{14}$ ]]; then
        echo "[跳过] 文件名 \"$filename\" 不符合 14 位时间戳规范 (YYYYMMDDHHmmss.扩展名)。"
        echo "       项目按绝对时间轴映射，文件名代表起始录音时间。"
        echo "       请重命名后再次处理，原文件暂留于 $INBOX_DIR/。"
        skipped_count=$((skipped_count + 1))
        continue
    fi

    run_dir="$RAW_OUTPUT_DIR/$base_name"
    mkdir -p "$run_dir"

    cli_cmd=()
    if [[ -x ".build/release/SoundlogCLI" ]]; then
        cli_cmd=(".build/release/SoundlogCLI")
    elif [[ -x ".build/debug/SoundlogCLI" ]]; then
        cli_cmd=(".build/debug/SoundlogCLI")
    else
        cli_cmd=(swift run SoundlogCLI)
    fi

    cmd=("${cli_cmd[@]}" process --input "$file" --output-dir "$RAW_OUTPUT_DIR" --run-dir "$run_dir")
    if [[ ${#extra_params[@]} -gt 0 ]]; then
        cmd+=("${extra_params[@]}")
    fi

    echo "执行分析: ${cmd[*]}"
    if "${cmd[@]}"; then
        echo "[成功] $filename 核心三类分析与对齐完成。"

        # 查找该文件在 run_dir 下的产物目录 (hash-filename)
        file_out=$(find "$run_dir" -maxdepth 1 -mindepth 1 -type d -name "*-${filename}" | head -n 1)
        if [[ -n "$file_out" && -d "$file_out" ]]; then
            echo "生成大模型分析素材..."
            python3 scripts/prepare_llm_material.py "$file_out" "$LLM_OUTPUT_DIR" "$base_name"
        else
            echo "[警告] 未定位到产物子目录: $run_dir/*-$filename"
        fi

        # 移动源文件至归档文件夹
        mv "$file" "$ARCHIVE_DIR/"
        echo "[归档] 源录音已移动至: $ARCHIVE_DIR/${filename} (供后续决定是否删除)"
        success_count=$((success_count + 1))
    else
        echo "[失败] ${filename} 处理未完全成功（退出码 $?）。"
        echo "       源文件保留在 ${INBOX_DIR}/ 中供检查或重试。"
        failure_count=$((failure_count + 1))
    fi
done

if [[ $success_count -gt 0 ]]; then
    echo ""
    echo "=================================================="
    echo "更新跨文件按天聚合场景库 (scripts/build_daily_scenes.py)..."
    python3 scripts/build_daily_scenes.py
    echo "=================================================="
fi

echo ""
echo "=================================================="
echo "【处理总结】"
echo "  总待处理数: $total_count"
echo "  成功归档数: $success_count"
echo "  处理失败数: $failure_count"
echo "  跳过规范数: $skipped_count"
echo "  大模型素材目录: $LLM_OUTPUT_DIR/"
echo "  按天聚合场景库: $LLM_OUTPUT_DIR/每日场景/"
echo "  归档源文件目录: $ARCHIVE_DIR/"
echo "=================================================="
