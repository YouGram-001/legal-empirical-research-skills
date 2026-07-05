"""
数据质量检验工具。

生成质量报告，包含：
1. 各字段缺失率统计
2. 高缺失率字段预警（>60%）
3. 字段分布概览
4. 抽样准确率（如有 ground truth）

用法:
  python quality_report.py --input <final_labeled_data.csv> --output <quality_report.txt>
                           [--ground-truth <ground_truth.csv>] [--sample-size 20]
"""

import os
import re
import argparse
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np


def missing_rate_analysis(df: pd.DataFrame, threshold: float = 0.60) -> pd.DataFrame:
    """
    计算各字段缺失率。

    Returns:
        DataFrame with columns: 字段名, 缺失数, 缺失率, 需关注
    """
    results = []
    for col in df.columns:
        n_missing = df[col].isna().sum() + (df[col].astype(str).str.strip() == "").sum()
        n_total = len(df)
        rate = n_missing / n_total if n_total > 0 else 0

        results.append({
            "字段名": col,
            "总记录数": n_total,
            "缺失数": n_missing,
            "填充数": n_total - n_missing,
            "缺失率": f"{rate:.1%}",
            "缺失率_raw": rate,
            "需关注": "是" if rate > threshold else "否",
        })

    result_df = pd.DataFrame(results)
    result_df = result_df.sort_values("缺失率_raw", ascending=False)
    return result_df


def distribution_summary(df: pd.DataFrame) -> dict:
    """生成字段分布概览"""
    summary = {}
    for col in df.columns:
        if df[col].dtype in ('int64', 'float64'):
            # 数值字段
            summary[col] = {
                "类型": "数值",
                "均值": f"{df[col].mean():.2f}" if df[col].notna().any() else "N/A",
                "中位数": f"{df[col].median():.2f}" if df[col].notna().any() else "N/A",
                "最小值": str(df[col].min()) if df[col].notna().any() else "N/A",
                "最大值": str(df[col].max()) if df[col].notna().any() else "N/A",
            }
        elif df[col].dtype == 'object':
            n_unique = df[col].nunique()
            n_notna = df[col].notna().sum()
            top_values = df[col].value_counts().head(5).to_dict() if n_notna > 0 else {}

            summary[col] = {
                "类型": "文本/分类",
                "唯一值数": n_unique,
                "有效记录": n_notna,
            }
            if n_unique <= 20:
                # 低基数列，展示全部分布
                summary[col]["值分布"] = {
                    str(k): v for k, v in top_values.items()
                }
            elif top_values:
                summary[col]["TOP-5"] = {
                    str(k)[:50]: v for k, v in top_values.items()
                }

    return summary


def sample_validation(
    df: pd.DataFrame,
    ground_truth_path: str,
    sample_size: int = 20,
) -> dict:
    """
    随机抽样对比 Agent 抽取结果与人工标注。

    Args:
        df: Agent 抽取的结果
        ground_truth_path: 人工标注的 ground truth CSV
        sample_size: 抽样数量

    Returns:
        {
            'field_accuracy': {field: accuracy},
            'overall_accuracy': float,
            'differences': [...],
        }
    """
    gt = pd.read_csv(ground_truth_path)

    # 找交集（按案号匹配）
    if "案号" in df.columns and "案号" in gt.columns:
        merged = df.merge(gt, on="案号", suffixes=("_pred", "_true"), how="inner")
    elif "案件ID" in df.columns and "案件ID" in gt.columns:
        merged = df.merge(gt, on="案件ID", suffixes=("_pred", "_true"), how="inner")
    else:
        # 按行序匹配
        n = min(len(df), len(gt))
        merged = pd.concat([df.iloc[:n].reset_index(drop=True),
                           gt.iloc[:n].reset_index(drop=True)], axis=1)
        merged.columns = [f"{c}_pred" for c in df.columns] + [f"{c}_true" for c in gt.columns]

    if len(merged) == 0:
        return {"error": "无法匹配 ground truth — 案号/案件ID 不匹配"}

    # 随机抽样
    if len(merged) > sample_size:
        sample = merged.sample(n=sample_size, random_state=42)
    else:
        sample = merged

    # 逐字段比对
    field_accuracy = {}
    all_differences = []

    # 找出共同的字段（去掉 _pred/_true 后缀）
    pred_cols = [c for c in sample.columns if c.endswith("_pred")]
    for pcol in pred_cols:
        base_name = pcol[:-5]  # 去掉 "_pred"
        tcol = f"{base_name}_true"

        if tcol not in sample.columns:
            continue

        # 比对（宽松匹配：忽略空白差异）
        pred_vals = sample[pcol].fillna("").astype(str).str.strip()
        true_vals = sample[tcol].fillna("").astype(str).str.strip()
        matches = (pred_vals == true_vals)
        accuracy = matches.sum() / len(matches) if len(matches) > 0 else 0

        field_accuracy[base_name] = {
            "准确率": f"{accuracy:.1%}",
            "准确率_raw": accuracy,
            "比对样本数": len(matches),
            "正确数": int(matches.sum()),
        }

        # 记录差异
        diff_indices = sample.index[~matches]
        for idx in diff_indices:
            all_differences.append({
                "行号": idx,
                "字段": base_name,
                "预测值": pred_vals.loc[idx][:100],
                "真实值": true_vals.loc[idx][:100],
            })

    overall = (
        sum(f["准确率_raw"] for f in field_accuracy.values()) / len(field_accuracy)
        if field_accuracy else 0
    )

    return {
        "field_accuracy": field_accuracy,
        "overall_accuracy": f"{overall:.1%}",
        "sample_size": len(sample),
        "total_differences": len(all_differences),
        "differences": all_differences[:20],  # 只保留前 20 条差异
    }


def generate_report(
    missing_df: pd.DataFrame,
    distribution: dict,
    validation: Optional[dict] = None,
    threshold: float = 0.60,
    accuracy_threshold: float = 0.85,
) -> str:
    """生成质量报告（纯文本）"""

    lines = []
    lines.append("=" * 60)
    lines.append("裁判文书实证研究 — 数据质量检验报告")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 60)

    # 1. 缺失率
    lines.append("\n\n## 一、字段缺失率统计\n")
    lines.append(f"{'字段名':<25} {'缺失数':>6} {'缺失率':>8} {'需关注':>6}")
    lines.append("-" * 50)
    for _, row in missing_df.iterrows():
        lines.append(
            f"{row['字段名']:<25} {row['缺失数']:>6} {row['缺失率']:>8} {row['需关注']:>6}"
        )

    high_missing_fields = missing_df[missing_df["需关注"] == "是"]
    if len(high_missing_fields) > 0:
        lines.append(f"\n⚠ 以下字段缺失率超过 {threshold:.0%}，建议评估是否保留或回溯补充：")
        for _, row in high_missing_fields.iterrows():
            lines.append(f"  - {row['字段名']}: {row['缺失率']}")

    # 2. 分布概览
    lines.append("\n\n## 二、字段分布概览\n")
    for field, info in distribution.items():
        lines.append(f"\n### {field} ({info.get('类型', 'unknown')})")
        for k, v in info.items():
            if k == "类型":
                continue
            if k in ("值分布", "TOP-5"):
                lines.append(f"  {k}:")
                for val, cnt in v.items():
                    lines.append(f"    {val}: {cnt}")
            else:
                lines.append(f"  {k}: {v}")

    # 3. 抽样验证
    if validation and "error" not in validation:
        lines.append("\n\n## 三、抽样准确率验证\n")
        lines.append(f"抽样数量: {validation.get('sample_size', 'N/A')}")
        lines.append(f"总体准确率: {validation.get('overall_accuracy', 'N/A')}")
        lines.append("")

        for field, acc in validation.get("field_accuracy", {}).items():
            marker = " ⚠ 建议调整" if acc.get("准确率_raw", 1) < accuracy_threshold else ""
            lines.append(f"  {field}: {acc.get('准确率', 'N/A')}{marker}")

        lines.append(f"\n共发现 {validation.get('total_differences', 0)} 处差异")

        if validation.get("differences"):
            lines.append("\n差异详情 (前 20 条):")
            for i, diff in enumerate(validation.get("differences", []), 1):
                lines.append(f"\n  [{i}] 字段: {diff['字段']}")
                lines.append(f"      预测: {diff['预测值']}")
                lines.append(f"      真实: {diff['真实值']}")

    # 4. 建议
    lines.append("\n\n## 四、改进建议\n")

    # 高缺失率建议
    if len(high_missing_fields) > 0:
        for _, row in high_missing_fields.iterrows():
            lines.append(
                f"- 字段 '{row['字段名']}' 缺失率 {row['缺失率']}，"
                f"建议：(1) 回溯补充抽取规则 (2) 评估是否为核心变量后决定保留/删除"
            )

    # 低准确率建议
    if validation and "error" not in validation:
        low_acc_fields = [
            (f, a) for f, a in validation.get("field_accuracy", {}).items()
            if a.get("准确率_raw", 0) < accuracy_threshold
        ]
        for field, acc in low_acc_fields:
            lines.append(
                f"- 字段 '{field}' 准确率仅 {acc.get('准确率', 'N/A')}，"
                f"建议调整该字段的抽取 prompt 或规则后重新执行"
            )

    if len(high_missing_fields) == 0 and not (validation and "error" not in validation and low_acc_fields):
        lines.append("- 当前数据质量良好，无需特别处理。")

    lines.append(f"\n\n{'='*60}")
    lines.append("报告结束")
    lines.append("=" * 60)

    return "\n".join(lines)


def run_quality_check(
    input_path: str,
    output_path: str,
    ground_truth_path: Optional[str] = None,
    sample_size: int = 20,
    missing_threshold: float = 0.60,
    accuracy_threshold: float = 0.85,
) -> dict:
    """
    质量检验主流程。
    """
    print(f"加载数据: {input_path}")
    if input_path.endswith('.xlsx'):
        df = pd.read_excel(input_path)
    else:
        df = pd.read_csv(input_path)
    print(f"  {len(df)} 行, {len(df.columns)} 列")

    # 1. 缺失率分析
    print("\n[Step 1] 缺失率分析...")
    missing_df = missing_rate_analysis(df, missing_threshold)

    # 2. 分布概览
    print("\n[Step 2] 分布概览...")
    distribution = distribution_summary(df)

    # 3. 抽样验证（如有 ground truth）
    validation = None
    if ground_truth_path and os.path.exists(ground_truth_path):
        print(f"\n[Step 3] 抽样验证 (n={sample_size})...")
        validation = sample_validation(df, ground_truth_path, sample_size)

        if "error" in validation:
            print(f"  [错误] {validation['error']}")
        else:
            print(f"  总体准确率: {validation['overall_accuracy']}")
            for field, acc in validation.get("field_accuracy", {}).items():
                print(f"    {field}: {acc['准确率']}")
    else:
        print("\n[Step 3] 跳过（未提供 ground truth）")

    # 4. 生成报告
    print(f"\n[Step 4] 生成报告...")
    report = generate_report(
        missing_df=missing_df,
        distribution=distribution,
        validation=validation,
        threshold=missing_threshold,
        accuracy_threshold=accuracy_threshold,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"报告已保存: {output_path}")

    return {
        "rows": len(df),
        "cols": len(df.columns),
        "high_missing_fields": int((missing_df["需关注"] == "是").sum()),
        "report_path": output_path,
    }


# ============ CLI ============

def main():
    parser = argparse.ArgumentParser(
        description="数据质量检验工具"
    )
    parser.add_argument("--input", required=True, help="final_labeled_data.csv 路径")
    parser.add_argument("--output", required=True, help="质量报告输出路径")
    parser.add_argument("--ground-truth", default=None, help="人工标注 ground truth 路径")
    parser.add_argument("--sample-size", type=int, default=20, help="抽样数量 (默认: 20)")
    parser.add_argument("--missing-threshold", type=float, default=0.60,
                        help="缺失率预警阈值 (默认: 0.60)")
    args = parser.parse_args()

    run_quality_check(
        input_path=args.input,
        output_path=args.output,
        ground_truth_path=args.ground_truth,
        sample_size=args.sample_size,
        missing_threshold=args.missing_threshold,
    )


if __name__ == "__main__":
    main()
