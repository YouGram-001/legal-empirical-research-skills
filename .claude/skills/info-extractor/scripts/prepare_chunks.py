"""
信息抽取预处理工具：从裁判文书全文提取关键段落。

策略：只保留"本院查明""本院认为""裁判结果"三个关键段落，
大幅节约下游 Agent 处理的上下文（通常可缩减 60-75%）。

输出格式：JSONL（每行一个 JSON 对象），便于断点续传和并行处理。

用法:
  python prepare_chunks.py --index <cleaned_index.csv> --raw-dir <dir> --output <chunks.jsonl>
"""

import os
import re
import json
import argparse
from typing import Optional

import pandas as pd
import chardet


# 段落边界标记（按优先级排列）
SECTION_MARKERS = {
    "facts": [
        r"本院查明", r"经审理查明", r"再审查明", r"原审查明",
        r"一审认定", r"本院认定事实",
        # 行政案件特有
        r"经审理[，,]本院查明",
    ],
    "reasoning": [
        r"本院认为", r"本院审查认为", r"本院再审认为",
        r"本院经审查认为", r"本院综合审查认为",
        # 行政/民事裁定书
        r"本院经审查[，,]",
    ],
    "judgment": [
        r"判决如下", r"裁定如下",
        r"判决[：:]", r"裁定[：:]",
    ],
}


def read_text(filepath: str) -> Optional[str]:
    """读取文本（自动检测编码）"""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "rb") as f:
            raw = f.read()
        if not raw:
            return ""
        detected = chardet.detect(raw)
        encoding = detected.get("encoding", "utf-8") or "utf-8"
        return raw.decode(encoding, errors="replace")
    except Exception:
        return None


def find_section_boundaries(text: str) -> dict:
    """
    在文本中定位各关键段落的起止位置。

    Returns:
        {
            'facts': (start, end) or None,
            'reasoning': (start, end) or None,
            'judgment': (start, end) or None,
        }
    """
    boundaries = {}

    # 找每个 section 的起始位置（取第一个匹配）
    section_starts = {}
    for section_name, markers in SECTION_MARKERS.items():
        best_pos = None
        for marker in markers:
            m = re.search(marker, text)
            if m:
                if best_pos is None or m.start() < best_pos:
                    best_pos = m.start()
        section_starts[section_name] = best_pos

    # 按顺序排列
    ordered = sorted(
        [(name, pos) for name, pos in section_starts.items() if pos is not None],
        key=lambda x: x[1],
    )

    # 为每个 section 确定 end position
    for i, (name, start) in enumerate(ordered):
        if i + 1 < len(ordered):
            end = ordered[i + 1][1]  # 下一个 section 的开始
        else:
            end = len(text)  # 文本末尾

        # 从 start 到 end，多取一点上下文
        effective_start = max(0, start - 100)  # 往前取 100 字符
        effective_end = min(len(text), end)

        boundaries[name] = (effective_start, effective_end)

    return boundaries


def extract_chunk(text: str, boundaries: dict) -> dict:
    """
    根据边界提取各段文本。

    Returns:
        {
            'facts': str,       # 本院查明段落
            'reasoning': str,   # 本院认为段落
            'judgment': str,    # 裁判结果段落
            'header': str,      # 首部（基本信息）
            'full_length': int, # 原文总长度
            'extracted_length': int,  # 提取文本总长度
        }
    """
    result = {
        "facts": "",
        "reasoning": "",
        "judgment": "",
        "header": "",
        "full_length": len(text),
        "extracted_length": 0,
    }

    # 首部：从开头到第一个 section
    first_section_pos = min(
        [v[0] for v in boundaries.values() if v],
        default=min(2000, len(text)),
    )
    result["header"] = text[:first_section_pos].strip()

    for section, (start, end) in boundaries.items():
        extracted = text[start:end].strip()
        result[section] = extracted
        result["extracted_length"] += len(extracted)

    return result


def prepare_chunks(
    index_path: str,
    raw_text_dir: str,
    output_path: str,
    include_full_text: bool = False,
    max_chars_per_section: int = 3000,
) -> dict:
    """
    主流程：读取 cleaned_index.csv，为每个保留的案件提取关键段落。

    Args:
        index_path: cleaned_index.csv 路径
        raw_text_dir: 纯文本目录
        output_path: 输出 JSONL 文件路径
        include_full_text: 是否包含全文（默认否，用于调试）
        max_chars_per_section: 每段最大字符数（截断过长段落）

    Returns:
        统计信息
    """
    df = pd.read_csv(index_path)

    # 只处理保留的案件
    retained = df[df["保留"] == True].copy()
    print(f"加载索引: {len(df)} 条, 保留 {len(retained)} 条")

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    chunks = []
    failed = 0
    skipped = 0

    for i, (_, row) in enumerate(retained.iterrows(), 1):
        case_id = row.get("案件ID", f"C{i:04d}")
        txt_path = row.get("转化后路径", "")

        if pd.isna(txt_path) or not txt_path:
            skipped += 1
            continue

        # 尝试读取文本文件
        text = read_text(txt_path)
        if text is None:
            failed += 1
            chunks.append({
                "case_id": case_id,
                "error": "file_not_found",
                "txt_path": txt_path,
            })
            continue

        # 找段落边界
        boundaries = find_section_boundaries(text)

        # 提取关键段落
        chunk = extract_chunk(text, boundaries)
        chunk["case_id"] = case_id
        chunk["txt_path"] = txt_path

        # 附加元数据
        for meta_field in ["案号", "审理法院", "审结日期", "确认审级", "案由",
                          "事件归总ID", "区/县", "裁判年份", "核心纠纷类型",
                          "当事人"]:
            if meta_field in row.index and pd.notna(row[meta_field]):
                chunk[f"meta_{meta_field}"] = str(row[meta_field])

        # 截断过长段落
        for section in ["facts", "reasoning", "judgment"]:
            if len(chunk.get(section, "")) > max_chars_per_section:
                chunk[section] = chunk[section][:max_chars_per_section] + "\n[...已截断...]"

        # 可选：包含全文
        if include_full_text:
            chunk["full_text"] = text

        # 构建精简版（给 Agent 的输入）
        agent_input = _build_agent_input(chunk)
        chunk["agent_input"] = agent_input
        chunk["agent_input_length"] = len(agent_input)

        chunks.append(chunk)

        if i % 50 == 0:
            print(f"  已处理: {i}/{len(retained)}")

    # 写入 JSONL
    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    # 统计
    if chunks:
        avg_full = sum(c.get("full_length", 0) for c in chunks) / len(chunks)
        avg_extracted = sum(c.get("agent_input_length", 0) for c in chunks) / len(chunks)
        reduction = (1 - avg_extracted / avg_full) * 100 if avg_full > 0 else 0
    else:
        avg_full = avg_extracted = reduction = 0

    stats = {
        "total": len(retained),
        "processed": len(chunks) - failed,
        "failed": failed,
        "skipped": skipped,
        "avg_full_length": int(avg_full),
        "avg_agent_input_length": int(avg_extracted),
        "context_reduction_pct": f"{reduction:.1f}%",
        "output_path": output_path,
    }

    print(f"\n准备完成:")
    print(f"  处理: {stats['processed']}, 失败: {stats['failed']}, 跳过: {stats['skipped']}")
    print(f"  平均原文长度: {stats['avg_full_length']} 字符")
    print(f"  平均 Agent 输入长度: {stats['avg_agent_input_length']} 字符")
    print(f"  上下文缩减: {stats['context_reduction_pct']}")
    print(f"  输出: {output_path}")

    return stats


def _build_agent_input(chunk: dict) -> str:
    """
    构建给 Agent 的精简输入文本。

    格式：
    ========== 案件基本信息 ==========
    案号: XXX
    审理法院: XXX
    ...

    ========== 本院查明 ==========
    ...

    ========== 本院认为 ==========
    ...

    ========== 裁判结果 ==========
    ...
    """
    parts = []

    # 基本信息
    info_lines = ["========== 案件基本信息 =========="]
    for key, label in [
        ("meta_案号", "案号"),
        ("meta_审理法院", "审理法院"),
        ("meta_审结日期", "审结日期"),
        ("meta_确认审级", "审级"),
        ("meta_案由", "案由"),
        ("meta_当事人", "当事人"),
        ("meta_事件归总ID", "事件归总ID"),
    ]:
        if key in chunk and chunk[key]:
            info_lines.append(f"{label}: {chunk[key]}")
    parts.append("\n".join(info_lines))

    # 关键段落
    for section, label in [
        ("facts", "本院查明"),
        ("reasoning", "本院认为"),
        ("judgment", "裁判结果"),
    ]:
        if chunk.get(section):
            parts.append(f"\n========== {label} ==========\n{chunk[section]}")

    return "\n".join(parts)


# ============ CLI ============

def main():
    parser = argparse.ArgumentParser(
        description="从裁判文书全文中提取关键段落，生成 Agent 输入 chunks"
    )
    parser.add_argument("--index", required=True, help="cleaned_index.csv 路径")
    parser.add_argument("--raw-dir", required=True, help="纯文本目录")
    parser.add_argument("--output", required=True, help="输出 JSONL 文件路径")
    parser.add_argument("--include-full-text", action="store_true",
                        help="包含全文（调试用）")
    parser.add_argument("--max-chars", type=int, default=3000,
                        help="每段最大字符数 (默认: 3000)")
    args = parser.parse_args()

    prepare_chunks(
        index_path=args.index,
        raw_text_dir=args.raw_dir,
        output_path=args.output,
        include_full_text=args.include_full_text,
        max_chars_per_section=args.max_chars,
    )


if __name__ == "__main__":
    main()
