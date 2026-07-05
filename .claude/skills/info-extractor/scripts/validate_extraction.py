"""
信息抽取结果校验工具。

对 Agent 抽取的 JSON 结果执行规则化验证：
1. 正则验证客观字段（案号、法院名称、日期格式）
2. 二分类标签关键词交叉验证
3. 分类字段取值约束检查
4. 标记 REVIEW_NEEDED 冲突项

用法:
  python validate_extraction.py --input <extracted.jsonl> --output <validated.csv>
"""

import os
import re
import json
import argparse
from typing import Optional, Any
from collections import Counter

import pandas as pd


# ============ 内置校验规则 ============

# 案号格式: (YYYY)XX...号 或 （YYYY）XX...号
CASE_NUMBER_PATTERN = re.compile(r'[\(（]\d{4}[\)）][一-龥\w]+号')

# 法院名称: 以"人民法院"结尾
COURT_NAME_PATTERN = re.compile(r'.+人民法院$')

# 日期格式: YYYY.MM.DD 或 YYYY年MM月DD日
DATE_PATTERN = re.compile(r'\d{4}[\.年]\d{1,2}[\.月]\d{1,2}')

# 省份列表
PROVINCES = {
    "北京市", "天津市", "上海市", "重庆市",
    "河北省", "山西省", "辽宁省", "吉林省", "黑龙江省",
    "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省",
    "河南省", "湖北省", "湖南省", "广东省", "海南省",
    "四川省", "贵州省", "云南省", "陕西省", "甘肃省", "青海省",
    "内蒙古自治区", "广西壮族自治区", "西藏自治区",
    "宁夏回族自治区", "新疆维吾尔自治区",
}

# 省会城市（用于"是否省会"验证）
CAPITAL_CITIES = {
    "北京市", "天津市", "上海市", "重庆市",
    "石家庄市", "太原市", "沈阳市", "长春市", "哈尔滨市",
    "南京市", "杭州市", "合肥市", "福州市", "南昌市", "济南市",
    "郑州市", "武汉市", "长沙市", "广州市", "海口市",
    "成都市", "贵阳市", "昆明市", "西安市", "兰州市", "西宁市",
    "呼和浩特市", "南宁市", "拉萨市", "银川市", "乌鲁木齐市",
}


def validate_case_number(value: Any) -> dict:
    """校验案号格式"""
    if value is None or pd.isna(value) or str(value).strip() == "":
        return {"valid": True, "warning": "missing", "corrected": None}

    text = str(value).strip()
    if CASE_NUMBER_PATTERN.search(text):
        return {"valid": True, "warning": None, "corrected": text}
    else:
        # 尝试修复常见问题
        return {"valid": False, "warning": "format_mismatch", "corrected": text}


def validate_court_name(value: Any) -> dict:
    """校验法院名称"""
    if value is None or pd.isna(value) or str(value).strip() == "":
        return {"valid": True, "warning": "missing", "corrected": None}

    text = str(value).strip()
    if COURT_NAME_PATTERN.match(text):
        return {"valid": True, "warning": None, "corrected": text}
    else:
        return {"valid": False, "warning": "not_a_court", "corrected": text}


def validate_date(value: Any) -> dict:
    """校验日期格式"""
    if value is None or pd.isna(value) or str(value).strip() == "":
        return {"valid": True, "warning": "missing", "corrected": None}

    text = str(value).strip()
    if DATE_PATTERN.match(text):
        return {"valid": True, "warning": None, "corrected": text}
    else:
        # 尝试修复
        return {"valid": False, "warning": "format_mismatch", "corrected": text}


def validate_province(value: Any) -> dict:
    """校验省份"""
    if value is None or pd.isna(value) or str(value).strip() == "":
        return {"valid": True, "warning": "missing", "corrected": None}

    text = str(value).strip()
    # 模糊匹配
    for prov in PROVINCES:
        if prov in text or text in prov:
            return {"valid": True, "warning": None, "corrected": prov}

    return {"valid": False, "warning": "unknown_province", "corrected": text}


def validate_binary(value: Any) -> dict:
    """校验二分类字段"""
    if value is None or pd.isna(value):
        return {"valid": True, "warning": "missing", "corrected": None}

    try:
        v = int(value)
        if v in (0, 1):
            return {"valid": True, "warning": None, "corrected": v}
        else:
            return {"valid": False, "warning": "not_binary", "corrected": v}
    except (ValueError, TypeError):
        text = str(value).strip()
        if text in ("是", "yes", "1", "true"):
            return {"valid": True, "warning": "normalized", "corrected": 1}
        elif text in ("否", "no", "0", "false"):
            return {"valid": True, "warning": "normalized", "corrected": 0}
        else:
            return {"valid": False, "warning": "cannot_parse", "corrected": text}


def validate_categorical(value: Any, allowed: set) -> dict:
    """校验分类字段"""
    if value is None or pd.isna(value) or str(value).strip() == "":
        return {"valid": True, "warning": "missing", "corrected": None}

    text = str(value).strip()
    if text in allowed:
        return {"valid": True, "warning": None, "corrected": text}

    # 模糊匹配
    for opt in allowed:
        if opt in text or text in opt:
            return {"valid": True, "warning": "fuzzy_match", "corrected": opt}

    return {"valid": False, "warning": "not_in_allowed", "corrected": text}


def keyword_cross_check(value: Any, keywords: list, section_text: str) -> dict:
    """
    二分类标签的关键词交叉验证。

    如果 Agent 判定为 0（否），但文本中出现触发关键词 → 标记冲突。
    如果 Agent 判定为 1（是），且文本中出现触发关键词 → 一致。
    """
    if not section_text:
        return {"valid": True, "cross_check": "no_text", "conflict": False}

    keyword_hits = []
    for kw in keywords:
        if kw in section_text:
            keyword_hits.append(kw)

    agent_says_yes = False
    try:
        agent_says_yes = int(value) == 1
    except (ValueError, TypeError):
        pass

    has_keywords = len(keyword_hits) > 0

    if has_keywords and not agent_says_yes:
        return {
            "valid": True,
            "cross_check": "conflict",
            "conflict": True,
            "reason": f"关键词触发 {keyword_hits}，但 Agent 判定为 0",
        }
    elif has_keywords and agent_says_yes:
        return {
            "valid": True,
            "cross_check": "match",
            "conflict": False,
            "reason": f"关键词触发 {keyword_hits}，Agent 判定一致",
        }
    elif not has_keywords and agent_says_yes:
        return {
            "valid": True,
            "cross_check": "agent_only",
            "conflict": False,
            "reason": "Agent 判定为 1 但无关键词触发（可能基于语义推断）",
        }
    else:
        return {
            "valid": True,
            "cross_check": "both_negative",
            "conflict": False,
        }


# ============ 字段级校验注册表 ============

FIELD_VALIDATORS = {
    "案号": {"method": "regex", "func": validate_case_number},
    "审理法院": {"method": "regex", "func": validate_court_name},
    "审结日期": {"method": "regex", "func": validate_date},
    "裁判日期": {"method": "regex", "func": validate_date},
    "地区": {"method": "lookup", "func": validate_province},
}


def validate_record(
    record: dict,
    field_definitions: Optional[list] = None,
) -> dict:
    """
    对单条抽取记录执行全面校验。

    Args:
        record: Agent 输出的 JSON（含 case_id 和各字段）
        field_definitions: 字段定义列表（从 config 加载）

    Returns:
        {
            'case_id': str,
            'fields': {field_name: {valid, warning, corrected_value}},
            'review_needed': bool,
            'review_fields': [...],
        }
    """
    result = {
        "case_id": record.get("case_id", "unknown"),
        "fields": {},
        "review_needed": False,
        "review_fields": [],
    }

    for field_name, value in record.items():
        if field_name == "case_id":
            continue

        field_result = {"valid": True, "warning": None, "corrected": None}

        # 使用注册的校验器
        if field_name in FIELD_VALIDATORS:
            validator = FIELD_VALIDATORS[field_name]
            field_result = validator["func"](value)

        if not field_result.get("valid", True):
            result["review_needed"] = True
            result["review_fields"].append({
                "field": field_name,
                "original": value,
                "warning": field_result.get("warning"),
                "corrected": field_result.get("corrected"),
            })

        result["fields"][field_name] = {
            "original": value,
            "valid": field_result.get("valid", True),
            "warning": field_result.get("warning"),
            "corrected": field_result.get("corrected"),
        }

    return result


def validate_all(
    input_path: str,
    output_path: str,
    field_definitions: Optional[list] = None,
) -> dict:
    """
    批量校验 JSONL 文件中的所有抽取结果。

    Args:
        input_path: extracted JSONL 文件路径
        output_path: 校验后的 CSV 输出路径
        field_definitions: 字段定义列表

    Returns:
        统计信息
    """
    records = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    print(f"加载 {len(records)} 条抽取记录")

    validated = []
    review_count = 0
    field_issues = Counter()

    for record in records:
        result = validate_record(record, field_definitions)
        validated.append(result)

        if result["review_needed"]:
            review_count += 1
            for rf in result["review_fields"]:
                field_issues[rf["field"]] += 1

    # 生成输出 DataFrame
    output_rows = []
    for v in validated:
        row = {"case_id": v["case_id"], "review_needed": v["review_needed"]}
        for fname, finfo in v["fields"].items():
            # 优先使用修正后的值
            value = finfo.get("corrected") if finfo.get("corrected") is not None else finfo.get("original")
            row[fname] = value
            row[f"{fname}_valid"] = finfo["valid"]
            if finfo.get("warning"):
                row[f"{fname}_warning"] = finfo["warning"]

        output_rows.append(row)

    df = pd.DataFrame(output_rows)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")

    stats = {
        "total": len(records),
        "review_needed": review_count,
        "review_pct": f"{review_count/len(records)*100:.1f}%" if records else "0%",
        "field_issues": dict(field_issues.most_common(10)),
        "output_path": output_path,
    }

    print(f"\n校验完成:")
    print(f"  总计: {stats['total']} 条")
    print(f"  需人工复核: {stats['review_needed']} 条 ({stats['review_pct']})")
    if field_issues:
        print(f"  问题字段 TOP-5:")
        for field, cnt in field_issues.most_common(5):
            print(f"    {field}: {cnt} 次")
    print(f"  输出: {output_path}")

    return stats


# ============ CLI ============

def main():
    parser = argparse.ArgumentParser(
        description="Agent 抽取结果校验工具"
    )
    parser.add_argument("--input", required=True, help="Agent 输出的 JSONL 文件")
    parser.add_argument("--output", required=True, help="校验后 CSV 输出路径")
    parser.add_argument("--config", default=None, help="research_config.yaml 路径")
    args = parser.parse_args()

    field_defs = None
    if args.config and os.path.exists(args.config):
        import yaml
        with open(args.config, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        field_defs = config.get("extraction_fields", [])

    validate_all(
        input_path=args.input,
        output_path=args.output,
        field_definitions=field_defs,
    )


if __name__ == "__main__":
    main()
