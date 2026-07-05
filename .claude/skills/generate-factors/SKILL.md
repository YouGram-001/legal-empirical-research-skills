---
name: generate-factors
description: >
  从文献和数据中生成法学实证研究的主要因素。当用户提起以下关键词时触发：
  分析主要因素、生成研究因素、文献分析、变量设计、研究方法、
  设计变量框架、建立假设、确定自变量因变量、文献蒸馏、方法论分析。
  从参考论文中蒸馏研究方法论，从清洗后的数据中做探索性分析，
  交叉验证后生成推荐变量框架和可检验假设。
argument-hint: "[研究主题或数据路径]"
user-invocable: true
allowed-tools: Read, Write, Bash, Grep, Glob, Edit, Agent, Workflow, Skill, TaskCreate, AskUserQuestion
---

# 研究因素生成与分析

从文献和数据两个方向发现"主要因素"，帮助研究者设计变量框架和研究假设。

## 核心方法：混合驱动

```
  ┌──────────────────┐     ┌──────────────────┐
  │ 文献方法论蒸馏     │     │ 数据探索性分析     │
  │ (理论驱动)        │     │ (数据驱动)        │
  └────────┬─────────┘     └────────┬─────────┘
           │                        │
           └───────────┬────────────┘
                       ▼
           ┌─────────────────────────┐
           │ 交叉验证 + 因素生成      │
           │ → 推荐变量框架           │
           │ → 可检验假设列表         │
           └─────────────────────────┘
```

## 触发条件

- "帮我分析主要因素"、"生成研究因素"
- "这些论文用了什么研究方法"
- "帮我设计变量框架"、"应该控制哪些变量"
- "从数据中能发现什么规律"

## 阶段一：文献方法论蒸馏

### Step 1: 确认论文来源

```
我在以下目录发现了参考论文：
  - 参考案例/ (23 篇 PDF)
  - 宪法学结课论文/参考文献/ (18 篇 PDF)

总共 41 篇。需要全部分析还是指定部分？
```

### Step 2: 并行扫描

使用 Claude Code Workflow 并行扫描所有论文：

```javascript
// Workflow: 文献方法论蒸馏
export const meta = {
  name: 'literature-distillation',
  description: '从法学实证研究论文中提取方法论信息',
  phases: [
    { title: '扫描分类', detail: '每篇论文提取元数据和研究方法' },
    { title: '综合报告', detail: '跨论文方法论对比和模式发现' },
  ],
}

phase('扫描分类')
const papers = await parallel(
  pdfFiles.map(f => () => agent(
    `阅读这篇法学实证研究论文的摘要、研究设计和结论部分，
     提取以下信息（输出 JSON）：

     1. 研究问题（一句话，中文）
     2. 方法论类型：描述性/解释性/评估性/混合
     3. 因变量定义与测量方式
     4. 自变量列表（区分核心自变量和控制变量）
     5. 统计方法：OLS/Logistic/DID/PSM-DID/GBDT/QCA/其他
     6. 数据来源：裁判文书网/北大法宝/其他
     7. 样本量
     8. 操作化路径（如何从裁判文书中识别和编码变量）
     9. 核心发现（一句话）
     10. 方法论局限性（作者自述）`,
    {
      label: `scan:${f.name}`,
      phase: '扫描分类',
      schema: {
        type: 'object',
        properties: {
          research_question: { type: 'string' },
          methodology_type: { type: 'string' },
          dependent_var: { type: 'string' },
          independent_vars: { type: 'array', items: { type: 'string' } },
          control_vars: { type: 'array', items: { type: 'string' } },
          stat_method: { type: 'string' },
          data_source: { type: 'string' },
          sample_size: { type: 'string' },
          operationalization: { type: 'string' },
          key_finding: { type: 'string' },
          limitations: { type: 'string' },
        },
        required: ['research_question', 'methodology_type', 'dependent_var']
      }
    }
  ))
)

phase('综合报告')
const synthesis = await agent(
  `综合以下 ${papers.length} 篇法学实证研究论文的方法论信息，
   生成一份方法论综述：

   论文元数据：
   ${JSON.stringify(papers.filter(Boolean))}

   请分析：
   1. 本领域最常用的变量框架（因变量类型分布、高频自变量 TOP-10）
   2. 统计方法选择趋势（哪种方法最常用，分别在什么条件下使用）
   3. 操作化路径总结（研究者如何从裁判文书中识别抽象概念）
   4. 常见的方法论局限性
   5. 对当前研究的建议（基于文献中已验证的因素）`,
  { label: 'synthesis', phase: '综合报告' }
)
```

### Step 3: 展示方法论图谱

将综合结果以结构化方式展示给用户：

```
📚 文献方法论图谱 (基于 41 篇论文)

最常用的因变量：
  1. 法院是否支持原告主张 (binary) — 18 篇
  2. 量刑长度 (continuous) — 9 篇
  3. 赔偿金额 (continuous) — 5 篇

最常用的自变量：
  1. 当事人特征（性别/户籍/年龄） — 28 篇
  2. 案件类型/案由 — 22 篇
  3. 是否有律师代理 — 15 篇
  4. 地区/法院层级 — 14 篇
  5. 年份 — 12 篇

统计方法分布：
  Logistic 回归: 45%
  OLS 回归: 25%
  DID: 10%
  描述性统计: 10%
  其他: 10%

基于此，你的研究可以考虑……
```

## 阶段二：数据探索性分析

### Step 4: 运行 EDA

```bash
python -c "
import pandas as pd
import numpy as np

df = pd.read_csv('output/final_labeled_data.csv')

# 描述性统计
print('=== 描述性统计 ===')
print(df.describe())

# 分类字段分布
for col in df.select_dtypes('object').columns:
    if df[col].nunique() < 20:
        print(f'\n=== {col} ===')
        print(df[col].value_counts())

# 交叉分析
# （根据实际字段动态生成）
"
```

如果数据中包含参考论文中提到的变量，特别关注这些变量的分布和相互关系。

### Step 5: Agent 解读数据

将 EDA 结果交给 Agent 解读：

```
基于以下 EDA 结果，分析数据中浮现的模式：

{EDA 输出}

请分析：
1. 哪些变量分布与文献预测一致/不一致？
2. 数据中是否有意外的模式值得关注？
3. 哪些变量缺失严重，可能影响分析？
4. 有没有明显的多重共线性风险？
5. 建议哪些交互项值得检验？
```

## 阶段三：交叉验证 + 因素生成

### Step 6: 综合报告

将文献发现和数据发现进行交叉验证：

```
🔗 交叉验证结果

文献预测但数据未体现：
  - "律师代理"在文献中频繁出现，但数据缺失 45% → 建议补充

数据揭示但文献未提及：
  - "是否额外补偿"与"法院认定结果"强相关 (φ=0.42) → 值得作为自变量

文献与数据一致：
  - "性别"是显著性因素 ✓
  - "地区（省会 vs 非省会）"差异显著 ✓

💡 推荐变量框架：
┌──────────────┬────────────────────────────────┐
│ 因变量        │ 法院是否支持当事人主张 (0/1)       │
├──────────────┼────────────────────────────────┤
│ 核心自变量    │ 歧视领域、当事人性别、户籍类型      │
│ 控制变量      │ 地区 FE、年份 FE、法院层级         │
│ 建议方法      │ Logistic 回归 + 稳健标准误         │
├──────────────┼────────────────────────────────┤
│ 待检验假设    │                                │
│ H1           │ 性别歧视案件认定率显著高于其他类型   │
│ H2           │ 省会城市法院更倾向于支持原告        │
│ H3           │ 农村户口当事人获得支持的概率更低     │
└──────────────┴────────────────────────────────┘

你觉得这个框架合理吗？需要调整什么？
```

### Step 7: 交互式讨论

用户确认框架后，进入开放讨论：
- 修改变量定义
- 增减假设
- 讨论可能的替代解释
- 确定后续分析步骤（Stata/R 代码建议）

### Step 8: 保存产出

将最终确认的研究设计保存为 `output/研究设计报告.md`。

## 使用 Workflow 的注意事项

- 文献扫描阶段：并行 agent 数量不超过 8 个（避免过载）
- 每个 agent 只扫描一篇论文的摘要+结论（不超过 2000 字）
- 综合阶段只用一个 synthesis agent
- 如果论文数量 > 50，分批进行
