"""
配置加载与生成模块。

负责:
1. 加载已有的 research_config.yaml
2. 根据对话中收集的信息生成新配置
3. 校验配置完整性
4. 自动检测项目状态
"""

import os
import yaml
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# 默认配置模板
DEFAULT_CONFIG = {
    "project": {
        "name": "未命名实证研究项目",
        "topic": "general",
        "description": "",
        "version": "1.0",
        "created": datetime.now().strftime("%Y-%m-%d"),
        "last_modified": datetime.now().strftime("%Y-%m-%d %H:%M"),
    },
    "input": {
        "documents_dir": "",
        "document_format": "mixed",
        "reference_papers_dirs": [],
    },
    "extraction_fields": [],
    "text_sections": {
        "facts": ["本院查明", "经审理查明", "再审查明"],
        "reasoning": ["本院认为", "本院审查认为"],
        "judgment": ["判决如下", "裁定如下"],
    },
    "cleaning": {
        "exclusion_rules": [
            {
                "name": "duplicate",
                "description": "案号、当事人、裁判日期完全一致",
                "keys": ["案号", "当事人", "裁判日期"],
                "action": "exclude",
            },
            {
                "name": "incomplete",
                "description": "缺少本院认为或裁判结果部分",
                "required_sections": ["本院认为", "裁判结果"],
                "action": "exclude",
            },
        ],
        "case_consolidation": {
            "enabled": True,
            "group_by": ["区/县", "年份", "核心纠纷类型"],
            "id_format": "{district}_{year}_{dispute_type}",
        },
    },
    "extraction": {
        "batch_size": 5,
        "max_parallel_agents": 3,
        "trial_run_size": 5,
        "retry_on_validation_failure": 1,
    },
    "label_unification": {
        "target_fields": [],
        "auto_suggest": True,
    },
    "quality_check": {
        "missing_threshold": 0.60,
        "sample_size": 20,
        "accuracy_threshold": 0.85,
    },
    "output": {
        "base_dir": "./output",
        "raw_texts": "./output/raw_texts",
        "excluded": "./output/excluded",
    },
}

# 内置参考数据
PROVINCE_LIST = [
    "北京市", "天津市", "上海市", "重庆市",
    "河北省", "山西省", "辽宁省", "吉林省", "黑龙江省",
    "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省",
    "河南省", "湖北省", "湖南省", "广东省", "海南省",
    "四川省", "贵州省", "云南省", "陕西省", "甘肃省", "青海省",
    "内蒙古自治区", "广西壮族自治区", "西藏自治区",
    "宁夏回族自治区", "新疆维吾尔自治区",
]

CAPITAL_CITIES = {
    "北京市": ["北京市"],
    "天津市": ["天津市"],
    "上海市": ["上海市"],
    "重庆市": ["重庆市"],
    "河北省": ["石家庄市"],
    "山西省": ["太原市"],
    "辽宁省": ["沈阳市"],
    "吉林省": ["长春市"],
    "黑龙江省": ["哈尔滨市"],
    "江苏省": ["南京市"],
    "浙江省": ["杭州市"],
    "安徽省": ["合肥市"],
    "福建省": ["福州市"],
    "江西省": ["南昌市"],
    "山东省": ["济南市"],
    "河南省": ["郑州市"],
    "湖北省": ["武汉市"],
    "湖南省": ["长沙市"],
    "广东省": ["广州市"],
    "海南省": ["海口市"],
    "四川省": ["成都市"],
    "贵州省": ["贵阳市"],
    "云南省": ["昆明市"],
    "陕西省": ["西安市"],
    "甘肃省": ["兰州市"],
    "青海省": ["西宁市"],
    "内蒙古自治区": ["呼和浩特市"],
    "广西壮族自治区": ["南宁市"],
    "西藏自治区": ["拉萨市"],
    "宁夏回族自治区": ["银川市"],
    "新疆维吾尔自治区": ["乌鲁木齐市"],
}

# 裁判文书结构标记
JUDGMENT_STRUCTURE_MARKERS = {
    "header_start": ["人民法院", "民事判决书", "行政判决书", "刑事判决书", "民事裁定书"],
    "facts": ["本院查明", "经审理查明", "再审查明", "原审查明"],
    "reasoning": ["本院认为", "本院审查认为", "本院再审认为"],
    "judgment": ["判决如下", "裁定如下", "判决", "裁定"],
    "appeal_notice": ["如不服本判决", "如不服本裁定"],
}


def get_project_root() -> str:
    """获取项目根目录"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_config_path() -> str:
    """获取配置文件路径"""
    return os.path.join(get_project_root(), "output", "research_config.yaml")


def load_config(config_path: Optional[str] = None) -> dict:
    """
    加载研究配置文件。

    Args:
        config_path: 配置文件路径，默认为 output/research_config.yaml

    Returns:
        配置字典，如果文件不存在则返回默认模板
    """
    if config_path is None:
        config_path = get_config_path()

    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config
    else:
        return DEFAULT_CONFIG.copy()


def save_config(config: dict, config_path: Optional[str] = None) -> str:
    """
    保存研究配置文件。

    Args:
        config: 配置字典
        config_path: 保存路径，默认为 output/research_config.yaml

    Returns:
        保存的文件路径
    """
    if config_path is None:
        config_path = get_config_path()

    config["project"]["last_modified"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    os.makedirs(os.path.dirname(config_path), exist_ok=True)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return config_path


def create_config_from_dialog(
    project_name: str,
    research_topic: str,
    documents_dir: str,
    extraction_fields: list,
    document_format: str = "mixed",
    reference_papers_dirs: Optional[list] = None,
    custom_exclusion_rules: Optional[list] = None,
    target_label_fields: Optional[list] = None,
) -> dict:
    """
    从对话中收集的信息生成完整配置。

    Args:
        project_name: 项目名称
        research_topic: 研究主题
        documents_dir: 文书所在目录
        extraction_fields: 字段定义列表
        document_format: 文书格式 ("doc", "docx", "mixed")
        reference_papers_dirs: 参考论文目录列表
        custom_exclusion_rules: 自定义排除规则
        target_label_fields: 需要标签统一的字段列表

    Returns:
        完整的配置字典
    """
    config = DEFAULT_CONFIG.copy()
    now = datetime.now().strftime("%Y-%m-%d")

    config["project"].update({
        "name": project_name,
        "topic": research_topic,
        "created": now,
        "last_modified": now,
    })
    config["input"]["documents_dir"] = documents_dir
    config["input"]["document_format"] = document_format
    if reference_papers_dirs:
        config["input"]["reference_papers_dirs"] = reference_papers_dirs

    config["extraction_fields"] = extraction_fields

    if custom_exclusion_rules:
        config["cleaning"]["exclusion_rules"].extend(custom_exclusion_rules)

    if target_label_fields:
        config["label_unification"]["target_fields"] = target_label_fields

    return config


def detect_project_status(config: dict) -> dict:
    """
    检测当前项目处理状态。

    Returns:
        {
            "format_conversion": "done" | "pending" | "not_applicable",
            "data_cleaning": "done" | "pending",
            "info_extraction": "done" | "pending",
            "label_unification": "done" | "pending",
            "quality_check": "done" | "pending",
        }
    """
    root = get_project_root()
    output_dir = config.get("output", {}).get("base_dir", "./output")
    output_path = os.path.join(root, output_dir)

    status = {
        "format_conversion": _check_step(
            os.path.exists(os.path.join(output_path, "index_raw.csv"))
        ),
        "data_cleaning": _check_step(
            os.path.exists(os.path.join(output_path, "cleaned_index.csv"))
        ),
        "info_extraction": _check_step(
            os.path.exists(os.path.join(output_path, "extracted_raw.csv"))
        ),
        "label_unification": _check_step(
            os.path.exists(os.path.join(output_path, "final_labeled_data.csv"))
        ),
        "quality_check": _check_step(
            os.path.exists(os.path.join(output_path, "quality_report.txt"))
        ),
    }
    return status


def format_status_report(status: dict) -> str:
    """将状态字典格式化为人类可读的汇报文本"""
    step_labels = {
        "format_conversion": "格式转化",
        "data_cleaning": "数据清洗",
        "info_extraction": "信息抽取",
        "label_unification": "标签统一",
        "quality_check": "质量检验",
    }
    lines = ["当前项目状态："]
    for key, label in step_labels.items():
        state = status.get(key, "pending")
        if state == "done":
            lines.append(f"  [OK] {label} — 已完成")
        elif state == "pending":
            lines.append(f"  [  ] {label} — 待执行")
    return "\n".join(lines)


def _check_step(condition: bool) -> str:
    return "done" if condition else "pending"


def get_field_validation_rules(field: dict) -> dict:
    """
    从字段定义中提取校验规则。

    Args:
        field: 字段定义字典（来自 extraction_fields）

    Returns:
        {
            "method": "regex" | "lookup" | "keyword_cross_check" | None,
            "pattern": ...,
            "trigger_keywords": [...],
            "options": [...],
        }
    """
    validation = field.get("validation", {})
    if not validation:
        return {"method": None}

    rules = {}
    if validation.get("regex"):
        rules["method"] = "regex"
        rules["pattern"] = validation["regex"]
    elif validation.get("values_from") == "province_list":
        rules["method"] = "lookup"
        rules["options"] = PROVINCE_LIST
    elif validation.get("values"):
        rules["method"] = "lookup"
        rules["options"] = validation["values"]
    elif validation.get("keyword_triggers"):
        rules["method"] = "keyword_cross_check"
        rules["trigger_keywords"] = validation["keyword_triggers"]
    else:
        rules["method"] = None

    return rules


if __name__ == "__main__":
    # 测试：生成示例配置并输出
    test_fields = [
        {
            "name": "案号",
            "type": "text",
            "source_sections": ["header"],
            "description": "案件编号",
            "validation": {"regex": r"\(\d{4}\)[一-龥\w]+号"},
        },
        {
            "name": "地区",
            "type": "categorical",
            "source_sections": ["header"],
            "description": "审理法院所在省级行政单位",
            "validation": {"values_from": "province_list"},
        },
        {
            "name": "事件",
            "type": "open_text",
            "source_sections": ["facts", "reasoning"],
            "description": "案件核心纠纷事件描述",
            "validation": None,
        },
    ]

    config = create_config_from_dialog(
        project_name="测试项目",
        research_topic="测试",
        documents_dir="./test_docs",
        extraction_fields=test_fields,
    )

    path = save_config(config)
    print(f"测试配置已保存到: {path}")

    status = detect_project_status(config)
    print(format_status_report(status))
