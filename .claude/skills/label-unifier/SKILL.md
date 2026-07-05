---
name: label-unifier
description: >
  统一开放文本字段的标签表述。当用户提起以下关键词时触发：统一标签、
  合并同类表述、标签标准化、同义词归并、分类统一、规范标签。
  对开放字段做频次统计，辅助识别同义词，生成 label_mapping.json。
argument-hint: "[extracted.csv路径]"
user-invocable: true
allowed-tools: Read, Write, Bash, Grep, Glob
---

# 标签统一化

将开放文本字段的同类表述归纳统一，确保全数据集使用一致的标签。

## 触发条件

- "统一标签"、"合并同类表述"、"标签标准化"
- "同义词归并"、"统一分类"
- "这些表述应该合并"

## 工作流程

### Step 1: 频次统计

```bash
python .claude/skills/label-unifier/scripts/unify_labels.py \
  --input output/extracted_validated.csv \
  --output output/final_labeled_data.csv \
  --freq-output output/frequency_report.csv
```

脚本自动对每个开放文本字段做频次统计，输出 TOP-30 高频表述。

### Step 2: Agent 辅助识别同义词

将频次报告展示给用户，Agent 辅助识别：

```
字段「事件」的高频表述：
  [25] 土地征收补偿款分配纠纷
  [12] 征地补偿款分配
  [ 8] 土地征收补偿纠纷
  [ 5] 征收补偿分配

建议映射：
  "征地补偿款分配" → "土地征收补偿分配"
  "土地征收补偿纠纷" → "土地征收补偿分配"
  "征收补偿分配" → "土地征收补偿分配"

确认应用吗？或者你想调整？
```

### Step 3: 人工确认 + 应用映射

**关键原则：每类映射先展示给用户确认，不直接替换。**

用户确认后：
1. 将映射写入 `output/label_mapping.json`
2. 运行脚本应用映射
3. 汇报变化：`事件字段：4 类表述合并为 1 类，涉及 50 条记录`

```bash
python .claude/skills/label-unifier/scripts/unify_labels.py \
  --input output/extracted_validated.csv \
  --output output/final_labeled_data.csv \
  --mapping output/label_mapping.json
```

### Step 4: 产出说明

- `output/label_mapping.json` — 映射字典（原始表述 → 统一标签）
- `output/final_labeled_data.csv` — 标签统一后的最终数据表

## 映射规则格式

`label_mapping.json` 格式：

```json
{
  "事件": {
    "征地补偿款分配": "土地征收补偿分配",
    "土地征收补偿纠纷": "土地征收补偿分配",
    "不予受理起诉": "程序性驳回",
    "驳回起诉": "程序性驳回",
    "裁定驳回": "程序性驳回"
  },
  "具体案由": {
    "劳动争议": "劳动人事争议",
    "劳动合同纠纷": "劳动人事争议"
  }
}
```

## 注意事项

- **忠实原文**：归并后的统一标签必须保持与原表述一致的核心含义
- **不强制统一**：开放文本（如"事件""裁判要点"）的归并是建议性的，用户可以选择保留部分原始表述
- **渐进式**：每轮归并后都可以检查和调整，支持多轮迭代
- **可追溯**：所有映射记录在 label_mapping.json 中，确保处理过程可复现
