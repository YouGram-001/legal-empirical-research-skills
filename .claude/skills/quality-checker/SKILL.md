---
name: quality-checker
description: >
  检验数据质量。当用户提起以下关键词时触发：质量检验、数据质量、
  缺失率、准确率验证、质量报告、数据验证、抽样检查。
  统计各字段缺失率，随机抽样验证准确率，生成 quality_report.txt。
argument-hint: "[final_labeled_data.csv路径]"
user-invocable: true
allowed-tools: Read, Write, Bash, Grep, Glob
---

# 数据质量检验

生成数据质量报告，包含缺失率统计、字段分布概览和抽样准确率。

## 触发条件

- "检查数据质量"、"质量检验"
- "看看缺失率和准确率"、"质量报告"
- "验证抽取结果"

## 工作流程

### Step 1: 缺失率分析

```bash
python .claude/skills/quality-checker/scripts/quality_report.py \
  --input output/final_labeled_data.csv \
  --output output/quality_report.txt
```

自动输出各字段的缺失数、缺失率，高于 60% 的字段标记为"需关注"。

### Step 2: 抽样验证（如有 ground truth）

如果用户有人工标注的 ground truth 数据：

```bash
python .claude/skills/quality-checker/scripts/quality_report.py \
  --input output/final_labeled_data.csv \
  --output output/quality_report.txt \
  --ground-truth ground_truth.csv \
  --sample-size 20
```

- 随机抽取 20 条记录
- 逐字段比对 Agent 抽取结果 vs 人工标注
- 计算各字段准确率

如果用户没有 ground truth，可以**现场做**：
- 随机抽 20 件文书
- 逐条展示 Agent 抽取结果 vs 原文关键句
- 用户（研究者）现场判断准确与否
- 汇总为准确率统计

### Step 3: 解读报告 + 行动建议

```
质量检验完成：

📊 缺失率：
  - 整体良好，大部分字段缺失率 < 10%
  - ⚠ "当事人援引法律"缺失 45% → 建议评估是否保留
  - ⚠ "是否额外补偿"缺失 72% → 建议回溯补充或标记为可选字段

📋 抽样准确率 (n=20):
  - 案号: 100%
  - 地区: 95%
  - 法院是否认定歧视: 90%
  - ⚠ 事件: 70% → 建议调整该字段抽取 prompt
  - 总体: 85%

建议：
  1. "当事人援引法律"缺失率较高，可能原因是部分判决未单独列出
  2. "事件"字段准确率偏低，建议在 prompt 中增加示例
  3. 其余字段质量良好，可进入统计分析阶段
```

### Step 4: 迭代改进

根据报告建议：
- 准确率 <85% 的字段 → 回到 info-extractor，调整 prompt 重新抽取
- 缺失率 >60% 的非核心字段 → 标记为可选或删除
- 缺失率 >60% 的核心字段 → 回溯原文补充

## 输出

- `output/quality_report.txt` — 质量检验报告，包含：
  - 字段缺失率统计
  - 高缺失率预警
  - 字段分布概览
  - 抽样准确率（如有）
  - 改进建议

## 注意事项

- 本步骤**非强制**，但建议在正式分析前至少做一次
- 抽样验证时优先选择有代表性的案件（不同审级、不同纠纷类型）
- 准确率阈值 85% 是建议值，可根据研究需求调整
- Ground truth 可以从已有的 `final_dataset_cleaned.xlsx` 获取
