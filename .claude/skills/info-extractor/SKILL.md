---
name: info-extractor
description: >
  从裁判文书中批量抽取结构化信息。当用户提起以下关键词时触发：信息抽取、
  提取字段、批量提取、结构化数据、抽取关键信息、填充数据表、生成变量。
  使用 Agent 集群并行处理，结合规则校验确保准确性。支持断点续传。
argument-hint: "[cleaned_index.csv路径]"
user-invocable: true
allowed-tools: Read, Write, Bash, Grep, Glob, Agent, Workflow, TaskCreate
---

# 裁判文书信息抽取

从清洗后的裁判文书中逐案提取结构化字段，生成 `extracted_raw.csv`。

核心策略：**Agent 集群并行抽取 + 规则化后校验**。

## 触发条件

- "抽取信息"、"提取字段"、"批量提取"
- "生成数据表"、"填充字段"
- "结构化数据抽取"

## 抽取流程（三步走）

### Step 1: 准备文本块 → `prepare_chunks.py`

```bash
python .claude/skills/info-extractor/scripts/prepare_chunks.py \
  --index output/cleaned_index.csv \
  --raw-dir output/raw_texts \
  --output output/chunks.jsonl
```

这一步提取每份文书的"本院查明""本院认为""裁判结果"关键段落，
将全文从平均 7500 字缩减到约 3600 字（节约 ~52% 上下文）。

### Step 2: 确认字段 Schema

从对话历史或 `research_config.yaml` 获取待抽取的字段列表。
如果用户是新项目且未配置字段，主动引导：

```
这个研究需要从文书中提取哪些字段？我建议以下分类：

[客观字段 — 正则可自动提取]
  案号、审理法院、审结日期、审级、案由

[分类标签 — 需从文本理解]
  地区（省份）、是否省会、当事人性别

[二分类标签 — 需配合关键词交叉验证]
  是否涉及性别歧视、是否涉及城乡歧视、
  法院是否认定歧视存在、是否额外补偿

[开放文本 — Agent 逐案独立总结]
  事件（纠纷概述）、主张存在歧视的领域、
  裁判要点、当事人援引法律、法院援引法律

你希望增减或修改哪些字段？
```

### Step 3: 试点抽取（5 份）

**重要**：在大规模抽取前，先抽取 5 份作为试点并展示给用户确认。

1. 读取 `output/chunks.jsonl` 的前 5 条
2. 对每条，用 Agent 抽取（不使用 Workflow，直接在对话中进行）
3. 展示抽取结果 → 用户确认字段定义、抽取质量
4. 根据反馈调整 Schema 或 prompt

示例 Agent 指令：

```
从以下裁判文书关键段落中提取结构化信息。

{案件的 agent_input 文本}

请提取以下字段，输出纯 JSON：

事件: 一句话概述案件核心纠纷（不超过 100 字）
地区: 审理法院所在省/自治区/直辖市（从法院名称提取即可）
当事人性别: "男"/"女"/null（从当事人姓名和文本描述判断）
是否涉及性别歧视: 1/0（当事人是否主张性别歧视）
法院是否支持当事人主张: 1/0

重要原则:
1. 只基于原文内容，不得推断或编造
2. 无法确定的值输出 null
3. 只输出 JSON，不要其他文字
```

### Step 4: 批量抽取（Workflow 编排）

用户确认试点结果后，启动批量抽取。

**分批策略**：
- 每批 10 份文书
- 每批内 3-5 个 Agent 并行
- 每批完成后自动保存 checkpoint
- 支持断点续传（中断后可继续）

**编排方式**：使用 Skill 调用 Workflow 工具，或直接在对话中分批循环：

```
现在开始批量抽取。

第 1/29 批 (1-10):
  [Agent 1] 抽取 C001-C003
  [Agent 2] 抽取 C004-C006
  [Agent 3] 抽取 C007-C010
  → 校验 → 保存 checkpoint

第 2/29 批 (11-20):
  ...
```

### Step 5: 结果校验 → `validate_extraction.py`

所有抽取完成后，运行规则校验：

```bash
python .claude/skills/info-extractor/scripts/validate_extraction.py \
  --input output/extracted_raw.jsonl \
  --output output/extracted_validated.csv
```

校验规则：
- **案号/日期/法院名**：正则格式验证
- **省份**：标准省份列表匹配
- **二分类标签**：关键词交叉验证（如"是否涉及性别歧视"字段，Agent 判定为 0 但文本中出现"妇女"→ 标记冲突）
- **分类字段**：值必须在允许集合中

校验结果：
- 冲突项标记为 `REVIEW_NEEDED`
- 汇总展示 → 用户裁定 → 批量处理

### Step 6: 汇报结果

```
信息抽取完成！
  - 总计: 286 份
  - 成功: 280 份
  - 需人工复核: 12 处冲突
  - 已保存: output/extracted_validated.csv

需要我展示冲突条目供你裁定吗？
```

## Agent 抽取 Prompt 模板

```
你是一名法学数据抽取专家。请从以下裁判文书关键段落中提取信息。

{=== 从 chunks.jsonl 中取出的 agent_input 字段 ===}

提取字段及说明：
{字段名称}: {类型说明} - {赋值规范}

输出格式（纯 JSON，无其他内容）：
{
  "字段1": "值",
  "字段2": 0,
  ...
}

原则：
1. 严格基于原文，不得推断
2. 无法确定的值填 null
3. 开放文本字段独立总结，不使用模板
```

## 大规模处理注意事项

- **Token 消耗**：每份文书 Agent 输入约 3600 字（~1000-1500 tokens），286 份总计约 300K-400K tokens
- **时间估算**：每批 10 份约需 60-90 秒，286 份约需 30-45 分钟
- **断点续传**：checkpoint 自动保存在 `checkpoints/extraction_progress.json`
- **中断恢复**：下次触发时自动检测 checkpoint，从未完成的案件继续

## 输出

- `output/chunks.jsonl` — 预处理后的文本块
- `output/extracted_raw.jsonl` — Agent 原始抽取结果（JSONL）
- `output/extracted_validated.csv` — 校验后的数据表（含 REVIEW_NEEDED 标记）
- `checkpoints/extraction_progress.json` — 断点续传进度
