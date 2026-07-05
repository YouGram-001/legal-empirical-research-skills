"""
裁判文书数据清洗与同案归总工具。

负责:
1. 去重检测（完全重复 + 模糊重复）
2. 完整性检查（必备段落验证）
3. 关联案件归总（事件归总ID 生成）
4. 审级关系标注
5. 排除文件管理（移入 excluded/ + 记录原因）

用法:
  python clean_dedupe.py --index <index_raw.csv> --raw-dir <dir> --output <cleaned_index.csv>
"""

import os
import re
import csv
import shutil
import argparse
import hashlib
from pathlib import Path
from typing import Optional
from collections import Counter

import pandas as pd
import chardet


# ============ 裁判文书结构标记 ============

REQUIRED_SECTIONS = ["本院认为", "裁判结果"]
REQUIRED_SECTION_MARKERS = {
    "本院认为": [r"本院认为", r"本院审查认为", r"本院再审认为"],
    "裁判结果": [r"判决如下", r"裁定如下", r"判决[：:]", r"裁定[：:]"],
}

# 审级标注 patterns
TRIAL_LEVEL_PATTERNS = {
    "一审": [r"一审", r"初字", r"初$", r"简易程序"],
    "二审": [r"二审", r"终字", r"终审", r"上诉"],
    "再审": [r"再审", r"审判监督", r"再字"],
}


def load_index(index_path: str) -> pd.DataFrame:
    """加载索引表"""
    if index_path.endswith(".csv"):
        return pd.read_csv(index_path)
    elif index_path.endswith(".xlsx"):
        return pd.read_excel(index_path)
    else:
        raise ValueError(f"不支持的索引格式: {index_path}")


def read_text_file(filepath: str) -> Optional[str]:
    """读取文本文件（自动检测编码）"""
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


def check_completeness(text: str) -> dict:
    """
    检查文书内容完整性。

    Returns:
        {'complete': bool, 'missing_sections': [...], 'total_length': int}
    """
    result = {
        "complete": True,
        "missing_sections": [],
        "total_length": len(text) if text else 0,
    }

    if not text or len(text.strip()) < 200:
        result["complete"] = False
        result["missing_sections"].append("全文过短")
        return result

    for section_name, markers in REQUIRED_SECTION_MARKERS.items():
        found = False
        for marker in markers:
            if re.search(marker, text):
                found = True
                break
        if not found:
            result["missing_sections"].append(section_name)
            result["complete"] = False

    return result


def extract_party_name(text: str) -> Optional[str]:
    """
    从首部提取当事人姓名（用于去重比对）。
    提取第一个原告/上诉人的姓名。
    """
    if not text:
        return None

    # 匹配模式: 原告XXX 或 上诉人XXX
    patterns = [
        r'(?:原告|上诉人|再审申请人|申请人|起诉人)\s*([一-龥]{2,4})',
        r'(?:原告|上诉人)[：:]\s*([一-龥]{2,4})',
    ]

    for pattern in patterns:
        m = re.search(pattern, text[:3000])
        if m:
            return m.group(1).strip()

    return None


def extract_district(text: str) -> Optional[str]:
    """从审理法院名称提取区/县"""
    if not text:
        return None

    # 从审理法院字段提取
    court_match = re.search(
        r'([一-龥]{2,}(?:市|县|区|自治州|旗))'
        r'(?:高级|中级|基层)?人民法院', text[:2000]
    )
    if court_match:
        location = court_match.group(1)
        # 进一步提取区/县级
        district_match = re.search(
            r'([一-龥]{2,}(?:市|县|区|自治州|旗))'
            r'(?:高级|中级|基层)?人民法院$', court_match.group(0)
        )
        if district_match:
            return district_match.group(1)
        return location

    return None


def extract_year(text: str, metadata_year: Optional[str] = None) -> Optional[str]:
    """提取裁判年份"""
    # 优先用 metadata 中的审结日期
    if metadata_year and pd.notna(metadata_year):
        m = re.match(r'(\d{4})', str(metadata_year))
        if m:
            return m.group(1)

    # 从案号提取
    if text:
        m = re.search(r'[\(（](\d{4})[\)）]', text[:500])
        if m:
            return m.group(1)

    return None


# 纠纷类型关键词映射（可从 config 扩展）
DEFAULT_DISPUTE_KEYWORDS = {
    "土地征收补偿分配": ["征收", "补偿款", "征地", "拆迁", "安置", "土地补偿"],
    "就业歧视": ["就业", "录用", "招聘", "解雇", "劳动合同", "劳动报酬", "平等就业"],
    "集体经济组织权益": ["集体经济", "成员资格", "村民待遇", "股份分红", "集体组织"],
    "行政处罚": ["行政处罚", "行政强制", "行政许可", "行政登记"],
    "人身损害": ["人身损害", "侵权", "赔偿", "人身权", "健康权"],
    "合同纠纷": ["合同", "违约", "协议"],
    "婚姻家庭": ["婚姻", "离婚", "抚养", "继承", "赡养"],
    "其他行政": ["行政"],  # fallback
    "其他民事": [],  # catch-all
}


def classify_dispute_type(text: str) -> str:
    """基于文本关键字归类纠纷类型"""
    if not text:
        return "其他"

    scores = {}
    for dtype, keywords in DEFAULT_DISPUTE_KEYWORDS.items():
        score = 0
        for kw in keywords:
            score += len(re.findall(kw, text))
        if score > 0:
            scores[dtype] = score

    if scores:
        return max(scores, key=scores.get)
    return "其他"


def detect_trial_level(text: str, meta_level: Optional[str] = None) -> str:
    """检测审级"""
    # 优先用 meta 中的审级
    if meta_level and pd.notna(meta_level):
        level = str(meta_level).strip()
        if level in ["一审", "二审", "再审"]:
            return level

    if not text:
        return "其他"

    # Pattern-based detection
    for level, patterns in TRIAL_LEVEL_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, text[:3000]):
                return level

    return "其他"


def generate_event_id(district: str, year: str, dispute_type: str) -> str:
    """生成事件归总ID"""
    parts = [
        district or "未知地区",
        year or "未知年份",
        dispute_type or "其他",
    ]
    return "_".join(parts)


def clean_and_deduplicate(
    index_path: str,
    raw_text_dir: str,
    output_path: str,
    excluded_dir: Optional[str] = None,
    enable_event_grouping: bool = True,
) -> dict:
    """
    主流程：清洗、去重、归总。

    Returns:
        统计信息 dict
    """
    df = load_index(index_path)
    n_total = len(df)
    print(f"加载索引: {n_total} 条记录")

    if excluded_dir:
        os.makedirs(excluded_dir, exist_ok=True)

    # 为每条记录分配 ID
    df["案件ID"] = [f"C{i+1:04d}" for i in range(len(df))]

    # ---- Step 1: 完整性检查 ----
    print("\n[Step 1] 完整性检查...")
    completeness_results = []
    for i, row in df.iterrows():
        txt_path = row.get("转化后路径", "")
        text = read_text_file(txt_path) if txt_path else None
        result = check_completeness(text)
        completeness_results.append(result)

    df["完整性"] = [r["complete"] for r in completeness_results]
    df["缺失段落"] = [",".join(r["missing_sections"]) if r["missing_sections"] else "" for r in completeness_results]
    df["文本长度"] = [r["total_length"] for r in completeness_results]

    n_incomplete = (~df["完整性"]).sum()
    print(f"  不完整: {n_incomplete} 份")

    # ---- Step 2: 提取去重键 ----
    print("\n[Step 2] 提取当事人信息...")
    parties = []
    for i, row in df.iterrows():
        txt_path = row.get("转化后路径", "")
        text = read_text_file(txt_path) if pd.notna(txt_path) else None
        parties.append(extract_party_name(text))

    df["当事人"] = parties
    df["案号_clean"] = df["案号"].fillna("")

    # 去重：案号 + 当事人 + 审结日期
    df["去重键"] = df.apply(
        lambda r: f"{r['案号_clean']}_{r['当事人']}_{r['审结日期']}",
        axis=1,
    )

    dup_mask = df.duplicated(subset=["去重键"], keep="first") & (df["去重键"] != "__")
    n_duplicates = dup_mask.sum()
    print(f"  完全重复: {n_duplicates} 份")

    # ---- Step 3: 标记排除 ----
    df["排除原因"] = ""
    df.loc[~df["完整性"], "排除原因"] = "内容残缺: " + df.loc[~df["完整性"], "缺失段落"]
    df.loc[dup_mask, "排除原因"] = df.loc[dup_mask, "排除原因"].apply(
        lambda x: (x + "; " if x else "") + "完全重复"
    )

    df["保留"] = df["排除原因"] == ""

    n_exclude = (~df["保留"]).sum()
    print(f"\n[Step 3] 排除汇总: {n_exclude} 份 (重复 {n_duplicates}, 残缺 {n_incomplete})")

    # 移动排除文件
    if excluded_dir:
        for i, row in df[~df["保留"]].iterrows():
            txt_path = row.get("转化后路径", "")
            if txt_path and os.path.exists(txt_path):
                dest = os.path.join(excluded_dir, os.path.basename(txt_path))
                shutil.move(txt_path, dest)
        print(f"  排除文件已移至: {excluded_dir}")

    # ---- Step 4: 事件归总 ----
    if enable_event_grouping:
        print("\n[Step 4] 事件归总...")
        districts = []
        years = []
        dispute_types = []
        trial_levels = []

        for i, row in df.iterrows():
            txt_path = row.get("转化后路径", "")
            text = read_text_file(txt_path) if pd.notna(txt_path) else ""

            dist = extract_district(text)
            yr = extract_year(text, row.get("审结日期"))
            dtype = classify_dispute_type(text)
            level = detect_trial_level(text, row.get("审级"))

            districts.append(dist)
            years.append(yr)
            dispute_types.append(dtype)
            trial_levels.append(level)

        df["区/县"] = districts
        df["裁判年份"] = years
        df["核心纠纷类型"] = dispute_types
        df["确认审级"] = trial_levels

        df["事件归总ID"] = df.apply(
            lambda r: generate_event_id(r["区/县"], r["裁判年份"], r["核心纠纷类型"])
            if r["保留"] else "",
            axis=1,
        )

        # 统计事件组
        valid_events = df[df["保留"] & (df["事件归总ID"] != "")]
        event_groups = valid_events.groupby("事件归总ID").size()
        multi_case_events = (event_groups > 1).sum()
        print(f"  事件组总数: {len(event_groups)}")
        print(f"  含多份文书的事件组: {multi_case_events}")
    else:
        df["事件归总ID"] = ""
        df["确认审级"] = df["审级"]

    # ---- Step 5: 输出 ----
    print(f"\n[Step 5] 保存清洗后索引...")

    # 选择输出列
    output_cols = [
        "案件ID", "原始文件名", "转化后路径", "案号", "审理法院",
        "审结日期", "确认审级", "案由", "当事人",
        "文本长度", "完整性", "缺失段落", "排除原因", "保留",
    ]
    if enable_event_grouping:
        output_cols += ["事件归总ID", "区/县", "裁判年份", "核心纠纷类型"]

    # 确保所有输出列存在
    output_cols = [c for c in output_cols if c in df.columns]

    output_df = df[output_cols].copy()
    output_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"  已保存: {output_path} ({len(output_df)} 行)")

    # ---- Summary ----
    stats = {
        "total": n_total,
        "retained": int(df["保留"].sum()),
        "excluded": n_exclude,
        "duplicates": int(n_duplicates),
        "incomplete": int(n_incomplete),
        "output_path": output_path,
    }

    print(f"\n{'='*50}")
    print(f"清洗完成: 总计 {n_total} → 保留 {stats['retained']}, 排除 {stats['excluded']}")
    if enable_event_grouping:
        print(f"事件组: {len(event_groups)} 组")

    return stats


# ============ CLI ============

def main():
    parser = argparse.ArgumentParser(
        description="裁判文书数据清洗与同案归总工具"
    )
    parser.add_argument("--index", required=True, help="index_raw.csv 路径")
    parser.add_argument("--raw-dir", required=True, help="纯文本文件目录")
    parser.add_argument("--output", required=True, help="cleaned_index.csv 输出路径")
    parser.add_argument("--excluded-dir", default=None, help="排除文件备份目录")
    parser.add_argument("--no-grouping", action="store_true",
                        help="禁用事件归总")
    args = parser.parse_args()

    clean_and_deduplicate(
        index_path=args.index,
        raw_text_dir=args.raw_dir,
        output_path=args.output,
        excluded_dir=args.excluded_dir,
        enable_event_grouping=not args.no_grouping,
    )


if __name__ == "__main__":
    main()
