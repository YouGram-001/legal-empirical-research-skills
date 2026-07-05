"""
质量检验辅助工具：分层抽样 + 准备幻觉检测材料。

从 final_labeled_data.csv 中分层随机抽样 N 条记录，
为每条记录匹配原始裁判文书纯文本路径和 AI 抽取结果，
输出为 JSON 供 Agent 做幻觉比对。

用法:
  python sample_for_review.py \
    --input output/final_labeled_data.csv \
    --raw-dir output/raw_texts \
    --index output/cleaned_index.csv \
    --output output/review_sample.json \
    --sample-size 20
"""

import os
import json
import random
import argparse
import pandas as pd


def stratified_sample(df: pd.DataFrame, n: int, strata_cols: list = None) -> pd.DataFrame:
    """
    分层抽样，确保覆盖不同审级和防卫认定结果。

    如果指定 strata_cols，按这些列的值组合分层，
    每层至少抽 1 条，剩余名额按层大小比例分配。
    """
    if strata_cols is None:
        strata_cols = ["审级"]

    # 尝试加入防卫相关字段（如果存在）
    for col in ["被告是否主张正当防卫", "法院是否认定互殴"]:
        if col in df.columns:
            strata_cols.append(col)
            break

    available_cols = [c for c in strata_cols if c in df.columns]
    if not available_cols:
        return df.sample(n=min(n, len(df)), random_state=42)

    # 构建分层键
    df = df.copy()
    df["_stratum"] = ""
    for col in available_cols:
        df["_stratum"] += df[col].astype(str) + "|"

    strata = df["_stratum"].value_counts()
    n_strata = len(strata)

    sampled = []
    remaining = n

    # 每层至少 1 条
    for stratum in strata.index:
        if remaining <= 0:
            break
        stratum_df = df[df["_stratum"] == stratum]
        take = max(1, min(len(stratum_df), remaining // max(n_strata, 1)))
        sampled.append(stratum_df.sample(n=take, random_state=42))
        remaining -= take
        n_strata -= 1

    # 如果还有名额，从整体随机补足
    if remaining > 0:
        sampled_ids = pd.concat(sampled).index
        remaining_pool = df[~df.index.isin(sampled_ids)]
        if len(remaining_pool) > 0:
            sampled.append(remaining_pool.sample(n=min(remaining, len(remaining_pool)), random_state=42))

    result = pd.concat(sampled).drop(columns=["_stratum"])
    return result


def find_raw_text(row: pd.Series, raw_dir: str, index_df: pd.DataFrame = None) -> str:
    """根据案号或文件名查找对应的原始纯文本"""
    case_id = str(row.get("案号", ""))

    # 方法 1: 通过 index 查找
    if index_df is not None:
        match = index_df[index_df["案号"] == case_id]
        if len(match) > 0:
            txt_path = match.iloc[0].get("转化后路径", "")
            if txt_path and os.path.exists(txt_path):
                return txt_path

    # 方法 2: 遍历 raw_texts 目录搜索
    if os.path.isdir(raw_dir):
        for fname in os.listdir(raw_dir):
            if fname.endswith(".txt"):
                fpath = os.path.join(raw_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read(500)
                    if case_id in content:
                        return fpath
                except Exception:
                    pass

    return None


def main():
    parser = argparse.ArgumentParser(description="分层抽样 + 准备幻觉检测材料")
    parser.add_argument("--input", required=True, help="final_labeled_data.csv 路径")
    parser.add_argument("--raw-dir", required=True, help="原始纯文本目录")
    parser.add_argument("--index", default=None, help="cleaned_index.csv 路径（用于匹配原文）")
    parser.add_argument("--output", required=True, help="输出 JSON 路径")
    parser.add_argument("--sample-size", type=int, default=None,
                        help="抽样数量（不指定则按规则自动计算：<100全量，100-1000抽30%%，>1000抽15%%）")
    parser.add_argument("--exclude", type=str, default=None,
                        help="排除已检测的案号文件（JSON list），用于迭代重抽")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    random.seed(args.seed)

    # 读取数据
    df = pd.read_csv(args.input, encoding="utf-8-sig")
    print(f"输入: {len(df)} 条记录")

    # 自动计算抽样量
    if args.sample_size is None:
        N = len(df)
        if N < 100:
            args.sample_size = N  # 逐一检验
        elif N < 1000:
            args.sample_size = max(20, int(N * 0.3))
        else:
            args.sample_size = max(50, int(N * 0.15))
        print(f"自动抽样量: {args.sample_size} (总 {N} 条, 规则: {'<100→全量' if N < 100 else '100-1000→30%' if N < 1000 else '>1000→15%'})")

    # 排除已检测记录（迭代重抽用）
    excluded_cases = set()
    if args.exclude and os.path.exists(args.exclude):
        with open(args.exclude, 'r', encoding='utf-8') as f:
            excluded_cases = set(json.load(f))
        print(f"排除已检测: {len(excluded_cases)} 条")

    # 从数据中排除
    if excluded_cases:
        df = df[~df['案号'].isin(excluded_cases)]
        print(f"剩余可抽样: {len(df)} 条")

    # 读取索引（如果有）
    index_df = None
    if args.index and os.path.exists(args.index):
        index_df = pd.read_csv(args.index, encoding="utf-8-sig")

    # 分层抽样
    sample_size = min(args.sample_size, len(df))
    sampled = stratified_sample(df, sample_size)
    print(f"抽样: {len(sampled)} 条")
    print(f"  审级分布: {sampled['审级'].value_counts().to_dict()}")

    # 为每条记录准备比对材料
    review_items = []
    found_text = 0

    for _, row in sampled.iterrows():
        txt_path = find_raw_text(row, args.raw_dir, index_df)

        item = {
            "案号": str(row.get("案号", "")),
            "审理法院": str(row.get("审理法院", "")),
            "审级": str(row.get("审级", "")),
            "原始文本路径": txt_path or "NOT_FOUND",
            "ai_extracted": {},
        }

        # 复制所有 AI 抽取字段
        for col in df.columns:
            val = row[col]
            if pd.isna(val):
                item["ai_extracted"][col] = None
            elif isinstance(val, (int, float)):
                item["ai_extracted"][col] = val
            else:
                item["ai_extracted"][col] = str(val)

        if txt_path:
            found_text += 1

        review_items.append(item)

    # 输出
    output = {
        "sample_size": len(review_items),
        "total_records": len(df),
        "text_match_rate": f"{found_text}/{len(review_items)}",
        "items": review_items,
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"文本匹配: {found_text}/{len(review_items)}")
    print(f"输出: {args.output}")


if __name__ == "__main__":
    main()
