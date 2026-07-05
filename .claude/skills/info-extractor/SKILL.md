---
name: info-extractor
description: >
  从裁判文书中批量抽取结构化信息。当用户提起以下关键词时触发：信息抽取、
  提取字段、批量提取、结构化数据、抽取关键信息、填充数据表、生成变量。
  使用 Workflow 并行处理，自动生命周期管理，支持断点续传。
argument-hint: "[cleaned_index.csv路径]"
user-invocable: true
allowed-tools: Read, Write, Bash, Grep, Glob, Agent, Workflow, TaskCreate
---

# 裁判文书信息抽取

从清洗后的裁判文书中逐案提取结构化字段，生成 `extracted_raw.csv`。

核心策略：**Workflow pipeline 并行抽取 + 自动生命周期管理 + 规则化后校验**。

## 与旧版的关键区别

**旧版**：裸 Agent 集群手动分批 → Agent 可能在主进程完成后仍然运行，浪费 token。
**新版**：Workflow 编排 → 所有子 Agent 的生命周期由 Workflow 管理，Workflow 结束 = 全部 Agent 自动终止。

## 触发条件

- "抽取信息"、"提取字段"、"批量提取"
- "生成数据表"、"填充字段"
- "结构化数据抽取"

## 抽取流程

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
如果用户是新项目且未配置字段，主动引导确认。

### Step 3: 试点抽取（5 份）→ 必须执行

**重要：在大规模抽取前，先抽取 5 份试点并展示给用户确认。**

直接在主对话中读取 `output/chunks.jsonl` 的前 5 条，用 Agent 逐条抽取，
展示结果 → 用户确认字段定义和抽取质量 → 调整 Schema。

### Step 4: 批量抽取 → 使用 Workflow

用户确认试点后，**使用 Workflow 工具**启动批量抽取。

#### Workflow 脚本模板

```javascript
export const meta = {
  name: 'batch-extraction',
  description: '批量抽取裁判文书结构化字段',
  phases: [
    { title: '抽取', detail: 'pipeline 并行抽取全部文档' },
    { title: '校验', detail: '规则校验 + 标记冲突' },
  ],
}

// 从 chunks.jsonl 读取全部文档
const fs = require('fs')
const chunks = JSON.parse(fs.readFileSync('output/chunks.jsonl', 'utf-8'))
  .map(c => JSON.parse(c))
// 如果有 checkpoint，只取未完成的
const completed = loadCheckpoint()  // 从 checkpoints/extraction_progress.json 读取
const pending = chunks.filter(c => !completed.includes(c.案件ID))

if (pending.length === 0) {
  log('全部文档已完成，跳过抽取。')
  return { allDone: true }
}

log(`待抽取: ${pending.length} 份 (共 ${chunks.length} 份，已完成 ${completed.length})`)

phase('抽取')

// pipeline: 每份文档独立推进，一份完成立即保存，不等待其他
const results = await pipeline(
  pending,
  (chunk) => agent(
    `从以下裁判文书关键段落中提取结构化信息。

${chunk.agent_input}

请提取以下字段，输出纯 JSON：
{
  "案号": "...",
  "审理法院": "...",
  "审级": "一审/二审/再审",
  ...（字段列表从 research_config.yaml 读取）
}

格式规范：
- 所有比例/程度/强度字段使用小数（0-1），如 60% → 0.6，10% → 0.1
- 所有日期字段统一为 YYYY-MM-DD（连字符，非点号），如 2026-01-08
- 二进制字段使用整数 0 或 1

原则：
1. 严格基于原文，不得推断或编造
2. 无法确定的值输出 null
3. 只输出 JSON，不要其他文字`,
    {
      label: `extract:${chunk.案件ID}`,
      phase: '抽取',
      schema: EXTRACTION_SCHEMA,  // 从 research_config.yaml 构建
    }
  ).then(result => {
    // 每个文档抽取完成后立即保存 checkpoint
    saveCheckpoint(chunk.案件ID, result)
    return result
  })
)

phase('校验')
const validated = await agent(
  `对以下 ${results.length} 条抽取结果进行规则校验...`,
  { label: 'validate', phase: '校验' }
)

return { results: validated.filter(Boolean), total: chunks.length, extracted: results.length }
```

#### 关键优势

- **自动清理**：Workflow 结束时，所有 pipeline 子 Agent 立即终止 — 不会泄漏
- **pipeline 模式**：文档 A 在校验阶段时，文档 B 可能还在抽取 — 最大化并行
- **checkpoint**：每个文档抽取完立即落盘，中断后可续传
- **进度可见**：`/workflows` 命令实时查看每个文档的抽取进度

### Step 5: 结果合并 → CSV

```bash
python -c "
import json, csv, glob
records = []
for f in glob.glob('checkpoints/extraction_*.json'):
    with open(f) as fp:
        records.append(json.load(fp))
with open('output/extracted_raw.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=records[0].keys())
    writer.writeheader()
    writer.writerows(records)
print(f'Merged {len(records)} records → output/extracted_raw.csv')
"
```

### Step 6: 汇报结果

```
信息抽取完成！
  - 总计: 188 份
  - 成功: 188 份
  - 已保存: output/extracted_raw.csv
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

## 生命周期管理规则

⚡ **重要：防止 Agent 泄漏**

1. **优先 Workflow**：批量抽取必须用 Workflow，不得用裸 Agent 集群
2. **及时止损**：当主进程已拿到足够数据推进下一步时，如果还有 Agent 在运行：
   - 用 `TaskStop(task_id="<agent_id>")` 终止不需要的 Agent
   - 不要等待它们自然完成
3. **结果优先**：当各 Agent 的结果文件已落盘、总和达到目标数量时，立即合并推进，
   不要等待所有 Agent 的 task-notification
4. **失败重试**：个别 Agent 超时或失败，用 checkpoint 只补抽缺失文档，
   不要重新抽全部

## 输出

- `output/chunks.jsonl` — 预处理后的文本块
- `output/extracted_raw.csv` — 最终结构化数据表
- `checkpoints/extraction_progress.json` — 断点续传进度
