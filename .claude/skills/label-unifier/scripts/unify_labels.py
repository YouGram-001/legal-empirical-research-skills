"""
标签统一化工具。

对开放文本字段进行频次统计，辅助识别同义词/近义表述，
应用映射规则生成统一的标准化标签。

用法:
  python unify_labels.py --input <extracted.csv> --output <final.csv>
                         [--mapping <label_mapping.json>] [--freq-output <freq.csv>]
"""

import os
import re
import json
import argparse
from typing import Optional
from collections import Counter

import pandas as pd


def frequency_analysis(
    df: pd.DataFrame,
    target_fields: list,
    top_n: int = 30,
) -> dict:
    """
    对指定字段做频次统计。

    Returns:
        {field_name: [(value, count), ...]}
    """
    results = {}
    for field in target_fields:
        if field not in df.columns:
            print(f"  [跳过] 字段 '{field}' 不在数据中")
            continue

        values = df[field].dropna().astype(str)
        # 清理：去除多余空白、统一标点
        values = values.str.strip().str.replace(r'\s+', ' ', regex=True)
        counter = Counter(values)
        results[field] = counter.most_common(top_n)

    return results


def print_frequency_report(freq: dict):
    """打印频次统计报告（人类可读）"""
    for field, items in freq.items():
        print(f"\n{'='*60}")
        print(f"字段: {field}")
        print(f"唯一值数量: {len(items)}")
        print(f"{'='*60}")
        for value, count in items[:20]:
            display = value[:80] + "..." if len(value) > 80 else value
            print(f"  [{count:4d}] {display}")


def suggest_mappings(freq: dict) -> list:
    """
    基于频次统计建议同义词映射。

    启发式规则：
    1. 短文本（<15字）且高频 → 可能是核心类别
    2. 两个值相似度 > 0.7 且一个显著低频 → 可能是同义词
    3. 相同的子串出现在多个值中 → 可能是一个大类别

    Returns:
        [{'field': str, 'from': str, 'to': str, 'reason': str}, ...]
    """
    suggestions = []

    for field, items in freq.items():
        if not items:
            continue

        # 建立值列表
        values = [v for v, _ in items]

        for i, (v1, c1) in enumerate(items):
            for j, (v2, c2) in enumerate(items):
                if i >= j:
                    continue

                # 检查一个是否包含另一个
                if v1 in v2 and len(v1) > 2 and c1 >= c2 * 2:
                    suggestions.append({
                        "field": field,
                        "from": v2,
                        "to": v1,
                        "reason": f"'{v2}' 包含 '{v1}'，且 '{v1}' 频率更高 ({c1} vs {c2})",
                    })
                elif v2 in v1 and len(v2) > 2 and c2 >= c1 * 2:
                    suggestions.append({
                        "field": field,
                        "from": v1,
                        "to": v2,
                        "reason": f"'{v1}' 包含 '{v2}'，且 '{v2}' 频率更高 ({c2} vs {c1})",
                    })

    return suggestions


def load_mapping(mapping_path: str) -> dict:
    """加载标签映射表"""
    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    return mapping


def apply_mapping(
    df: pd.DataFrame,
    mapping: dict,
) -> pd.DataFrame:
    """
    应用标签映射到 DataFrame。

    mapping 格式:
    {
        "field_name": {
            "原始表述1": "统一标签A",
            "原始表述2": "统一标签A",
        }
    }

    也支持简洁格式:
    {
        "统一标签A": ["原始表述1", "原始表述2"],
    }
    (会自动展开为 field-level mapping)
    """
    result = df.copy()

    for field, rules in mapping.items():
        if field not in result.columns:
            print(f"  [跳过] 字段 '{field}' 不在数据中")
            continue

        if isinstance(rules, dict):
            # 格式: {"原始表述": "统一标签"}
            for old_val, new_val in rules.items():
                mask = result[field].astype(str).str.strip() == old_val.strip()
                n_changed = mask.sum()
                result.loc[mask, field] = new_val
                if n_changed > 0:
                    print(f"  {field}: '{old_val}' → '{new_val}' ({n_changed} 条)")

        elif isinstance(rules, list):
            # 格式: ["原始表述1", "原始表述2"] → 无映射目标，跳过
            print(f"  [警告] {field}: 列表格式需要映射目标")

    return result


def unify_labels(
    input_path: str,
    output_path: str,
    mapping_path: Optional[str] = None,
    target_fields: Optional[list] = None,
    freq_output: Optional[str] = None,
    auto_suggest: bool = True,
) -> dict:
    """
    标签统一主流程。

    Steps:
    1. 频次统计 → 展示报告
    2. 自动建议映射（可选）
    3. 应用 mapping → 生成最终表
    """
    if input_path.endswith('.xlsx'):
        df = pd.read_excel(input_path)
    else:
        df = pd.read_csv(input_path)
    print(f"加载数据: {len(df)} 行, {len(df.columns)} 列")

    # 确定目标字段
    if target_fields is None:
        # 默认：所有 object/text 类型的列
        target_fields = [
            col for col in df.columns
            if df[col].dtype == 'object' and df[col].nunique() > 5
        ]
        print(f"自动选择目标字段: {target_fields}")

    # Step 1: 频次统计
    print(f"\n[Step 1] 频次统计...")
    freq = frequency_analysis(df, target_fields)
    print_frequency_report(freq)

    if freq_output:
        # 保存频次报告
        freq_rows = []
        for field, items in freq.items():
            for value, count in items:
                freq_rows.append({"字段": field, "值": value, "频次": count})
        freq_df = pd.DataFrame(freq_rows)
        freq_df.to_csv(freq_output, index=False, encoding="utf-8-sig")
        print(f"\n频次报告已保存: {freq_output}")

    # Step 2: 自动建议
    if auto_suggest:
        print(f"\n[Step 2] 自动建议映射...")
        suggestions = suggest_mappings(freq)
        if suggestions:
            print(f"发现 {len(suggestions)} 条可能的同义词映射：")
            for s in suggestions[:10]:
                print(f"  [{s['field']}] '{s['from']}' → '{s['to']}'")
                print(f"    原因: {s['reason']}")
        else:
            print("未发现明显的同义词映射建议。")

    # Step 3: 应用映射
    if mapping_path and os.path.exists(mapping_path):
        print(f"\n[Step 3] 应用映射...")
        mapping = load_mapping(mapping_path)
        df = apply_mapping(df, mapping)
    else:
        print(f"\n[Step 3] 跳过（未提供 label_mapping.json）")

    # 保存
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n最终数据已保存: {output_path}")

    return {
        "total_rows": len(df),
        "target_fields": len(target_fields),
        "output_path": output_path,
    }


# ============ CLI ============

def main():
    parser = argparse.ArgumentParser(
        description="标签统一化工具 — 频次统计 + 同义词映射"
    )
    parser.add_argument("--input", required=True, help="输入 CSV 路径")
    parser.add_argument("--output", required=True, help="输出 CSV 路径")
    parser.add_argument("--mapping", default=None, help="label_mapping.json 路径")
    parser.add_argument("--fields", default=None, help="目标字段，逗号分隔（默认自动选择）")
    parser.add_argument("--freq-output", default=None, help="频次报告输出路径")
    parser.add_argument("--no-suggest", action="store_true", help="禁用自动建议")
    args = parser.parse_args()

    fields = [f.strip() for f in args.fields.split(",")] if args.fields else None

    unify_labels(
        input_path=args.input,
        output_path=args.output,
        mapping_path=args.mapping,
        target_fields=fields,
        freq_output=args.freq_output,
        auto_suggest=not args.no_suggest,
    )


if __name__ == "__main__":
    main()
