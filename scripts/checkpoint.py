"""
断点续传模块。

负责:
1. 在大规模处理中保存和恢复进度
2. 支持跨会话恢复
3. 记录每批处理的成功/失败状态
"""

import os
import json
import hashlib
from datetime import datetime
from typing import Optional


def get_checkpoint_path() -> str:
    """获取 checkpoint 文件路径"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "checkpoints", "extraction_progress.json")


def generate_config_hash(config: dict) -> str:
    """生成配置的哈希值，用于检测配置变更"""
    config_str = json.dumps(config, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(config_str.encode()).hexdigest()[:16]


def init_checkpoint(total_cases: int, config: dict) -> dict:
    """
    初始化或加载已有的 checkpoint。

    Args:
        total_cases: 待处理的总案件数
        config: 当前使用的配置（用于检测变更）

    Returns:
        checkpoint 字典
    """
    path = get_checkpoint_path()
    config_hash = generate_config_hash(config)

    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            cp = json.load(f)

        # 检查配置是否变更
        if cp.get("config_hash") != config_hash:
            print("[checkpoint] 检测到配置变更，将重置进度。")
            cp = _create_fresh_checkpoint(total_cases, config_hash)
            save_checkpoint(cp)
        else:
            # 更新 total_cases（可能新增了文件）
            cp["total_cases"] = total_cases
    else:
        cp = _create_fresh_checkpoint(total_cases, config_hash)
        save_checkpoint(cp)

    return cp


def _create_fresh_checkpoint(total_cases: int, config_hash: str) -> dict:
    return {
        "config_hash": config_hash,
        "total_cases": total_cases,
        "completed_cases": [],
        "failed_cases": {},
        "current_batch": 0,
        "total_batches": 0,
        "last_updated": datetime.now().isoformat(),
        "notes": "",
    }


def save_checkpoint(cp: dict) -> None:
    """保存 checkpoint"""
    cp["last_updated"] = datetime.now().isoformat()
    path = get_checkpoint_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cp, f, ensure_ascii=False, indent=2)


def mark_completed(cp: dict, case_id: str) -> None:
    """标记某个案件处理完成"""
    if case_id not in cp["completed_cases"]:
        cp["completed_cases"].append(case_id)
    # 从失败列表中移除（如果之前失败了）
    cp["failed_cases"].pop(case_id, None)
    save_checkpoint(cp)


def mark_failed(cp: dict, case_id: str, error: str, retries: int = 0) -> None:
    """标记某个案件处理失败"""
    cp["failed_cases"][case_id] = {
        "error": error,
        "retries": retries,
        "last_attempt": datetime.now().isoformat(),
    }
    save_checkpoint(cp)


def get_pending_cases(cp: dict, all_case_ids: list) -> list:
    """
    获取尚未处理的案件 ID 列表。

    Args:
        cp: checkpoint 字典
        all_case_ids: 全部案件 ID 列表

    Returns:
        未处理的案件 ID 列表
    """
    completed_set = set(cp["completed_cases"])
    return [cid for cid in all_case_ids if cid not in completed_set]


def get_failed_cases_for_retry(cp: dict, max_retries: int = 3) -> list:
    """
    获取可以重试的失败案件。

    Args:
        cp: checkpoint 字典
        max_retries: 最大重试次数

    Returns:
        可重试的案件 ID 列表
    """
    return [
        cid
        for cid, info in cp["failed_cases"].items()
        if info["retries"] < max_retries
    ]


def get_progress_summary(cp: dict) -> str:
    """生成进度摘要（中文）"""
    total = cp["total_cases"]
    completed = len(cp["completed_cases"])
    failed = len(cp["failed_cases"])
    pending = total - completed - failed
    pct = (completed / total * 100) if total > 0 else 0

    lines = [
        f"处理进度: {completed}/{total} ({pct:.1f}%)",
        f"  [OK] 已完成: {completed}",
        f"  [XX] 失败: {failed}",
        f"  [  ] 待处理: {pending}",
    ]
    if cp.get("notes"):
        lines.append(f"  [*] 备注: {cp['notes']}")

    return "\n".join(lines)


def get_checkpoint_summary() -> Optional[str]:
    """快速获取已有 checkpoint 的摘要（不修改文件）"""
    path = get_checkpoint_path()
    if not os.path.exists(path):
        return None

    with open(path, "r", encoding="utf-8") as f:
        cp = json.load(f)

    return get_progress_summary(cp)


if __name__ == "__main__":
    # 测试
    test_config = {"project": {"name": "test"}}
    cp = init_checkpoint(total_cases=100, config=test_config)
    print(get_progress_summary(cp))

    mark_completed(cp, "C001")
    mark_completed(cp, "C002")
    mark_failed(cp, "C003", "JSON parse error", retries=1)
    print("\n更新后:")
    print(get_progress_summary(cp))
