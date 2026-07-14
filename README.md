# 裁判文书实证研究 Skills 套件

一个**对话驱动**的法学实证研究工具包。在 Claude Code 中用自然语言处理、清洗、结构化大量裁判文书（.doc/.docx），最终输出可直接用于统计分析和回归建模的 CSV 数据表。

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

## 快速开始

### 1. 安装 Claude Code

```bash
# 如果还没安装 Claude Code
npm install -g @anthropic-ai/claude-code
```

### 2. 克隆本项目

```bash
git clone <你的仓库地址>
cd 实证研究skills
```

### 3. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

### 4. 开始对话

在 Claude Code 中打开本项目目录，直接说：

```
帮我处理一批裁判文书，数据在 ./裁判文书/解压文件/ 里
```

Skill 会自动引导你完成研究设计、字段规划、清洗规则确认，然后自动编排处理流水线。

**不需要编辑任何配置文件。** 一切通过对话完成。

---

## 能做什么

```
你说                                       Skill 自动做的事
────                                      ──────────────
"帮我处理这批裁判文书"                     启动研究向导，五轮对话确定所有设置
"把这些 doc 转成纯文本"                    333 个 .doc → 333 个 .txt（自动去页眉页脚）
"清洗数据，排除重复和残缺的"               去重 + 完整性检查 + 关联案件归总 + 审级标注
"从文书里提取这些字段..."                  Agent 集群并行抽取 → 正则校验 → 标记冲突
"统一一下开放字段的标签"                   频次统计 → 同义词识别 → 用户确认 → 应用映射
"检查数据质量"                            缺失率统计 + 抽样准确率 + 改进建议
"帮我分析哪些因素影响判决结果"             文献蒸馏 + 数据EDA + 交叉验证 → 变量框架
```

---

## 架构总览

```
用户对话触发
    │
    ├─→ Skill A: start-research (启动实证研究)
    │     五轮对话引导 → 自动生成配置 → 编排流水线
    │
    └─→ Skill B: generate-factors (生成研究因素)
          文献方法论蒸馏 + 数据探索性分析 → 变量框架 + 假设

         ┌──────────┬──────────┬──────────┬──────────┬──────────┐
         ▼          ▼          ▼          ▼          ▼
      Tool 1     Tool 2     Tool 3     Tool 4     Tool 5
     格式转化    数据清洗    信息抽取    标签统一    质量检验
     doc→txt   去重+归总   Agent集群  同义词映射  缺失率+准确率
```

## Skills 清单

| Skill | 触发词 | 功能 |
|-------|--------|------|
| **start-research** | "启动实证研究"、"处理裁判文书" | 对话引导 → 自动配置 → 编排全流程 |
| **generate-factors** | "分析主要因素"、"变量框架" | 文献蒸馏 + 数据EDA → 因素生成 |
| **doc-converter** | "转格式"、"doc转文本" | .doc/.docx → 干净纯文本 |
| **data-cleaner** | "清洗数据"、"去重" | 排重 + 完整性 + 事件归总 |
| **info-extractor** | "抽取信息"、"提取字段" | Agent 集群并行抽取结构化字段 |
| **label-unifier** | "统一标签"、"合并同类" | 频次统计 + 同义词归并 |
| **quality-checker** | "质量检验"、"缺失率" | 缺失率 + 抽样准确率报告 |

## 数据处理流水线

```
.doc/.docx 裁判文书
    │
    ▼
[Tool 1: 格式转化] ──── convert_docs.py (antiword/python-docx)
    │
    ├── raw_texts/*.txt
    └── index_raw.csv
        │
        ▼
[Tool 2: 数据清洗] ──── clean_dedupe.py
    │
    ├── excluded/ (无效文书备查)
    └── cleaned_index.csv (含事件归总ID、审级)
        │
        ▼
[Tool 3: 信息抽取] ──── prepare_chunks.py + Agent集群 + validate_extraction.py
    │
    └── extracted_raw.csv (含 REVIEW_NEEDED 标记)
        │
        ▼
[Tool 4: 标签统一] ──── unify_labels.py + 人工确认
    │
    ├── final_labeled_data.csv  ← 可直接用于回归分析
    └── label_mapping.json
        │
        ▼
[Tool 5: 质量检验] ──── quality_report.py
    │
    └── quality_report.txt
```

## 核心设计原则

### 对话驱动，零文件编辑

所有配置通过对话自动生成。你不需要打开任何 YAML 或 JSON 文件。

```
你：  "我想研究劳动争议中法院支持劳动者的影响因素"
Skill: "好的！你的因变量应该是「法院是否支持劳动者主张」对吗？"
你：  "对，再加一个「是否涉及工伤」字段"
Skill: "已添加。共 16 个字段，现在开始转化格式？"
```

### 人机边界清晰

- **Python 做确定性的事**：格式转化、正则匹配、pandas 操作
- **Agent 做需要理解的事**：从裁判文书中理解纠纷事实、总结裁判要点
- **边界不清的标记出来**：Agent 结果与规则冲突 → 标记 REVIEW_NEEDED → 你来裁定

### 大规模友好

- 分批并行处理（每批 10 份，3-5 个 Agent 并行）
- 断点续传（中断后自动从上次位置继续）
- 上下文优化（仅输入关键段落，节约 52%+ token 消耗）

## 技术栈

| 需求 | 方案 | 说明 |
|------|------|------|
| .doc 转化 | antiword（Git Bash 自带） | 零安装，已验证支持中文 |
| .docx 转化 | python-docx | 段落级控制，自动排除页眉页脚 |
| 信息抽取 | Claude Code Workflow 多 Agent | 不使用外部 API，利用 Claude NLU |
| 数据清洗 | pandas + regex | 可复现的确定性规则 |
| 配置文件 | YAML（对话自动生成） | 用户不需要手动编辑 |

## 环境要求

- **Claude Code**（最新版本）
- **Python 3.9+**（pandas, python-docx, pyyaml, openpyxl, chardet, scipy）
- **Git Bash**（Windows 用户自带 antiword）
- **LibreOffice**（可选，antiword 备选方案）

## 目录结构

```
实证研究skills/
├── README.md                              ← 本文件
├── CLAUDE.md                              # 项目背景（Skill 自动维护）
├── requirements.txt                       # Python 依赖
├── .gitignore
├── .claude/
│   └── skills/
│       ├── start-research/SKILL.md        # 入口 A：启动实证研究
│       ├── generate-factors/SKILL.md      # 入口 B：生成研究因素
│       ├── doc-converter/                 # 工具 1：格式转化
│       │   ├── SKILL.md
│       │   └── scripts/convert_docs.py
│       ├── data-cleaner/                  # 工具 2：数据清洗
│       │   ├── SKILL.md
│       │   └── scripts/clean_dedupe.py
│       ├── info-extractor/                # 工具 3：信息抽取
│       │   ├── SKILL.md
│       │   └── scripts/
│       │       ├── prepare_chunks.py
│       │       └── validate_extraction.py
│       ├── label-unifier/                 # 工具 4：标签统一
│       │   ├── SKILL.md
│       │   └── scripts/unify_labels.py
│       └── quality-checker/               # 工具 5：质量检验
│           ├── SKILL.md
│           └── scripts/quality_report.py
├── scripts/                               # 共享工具
│   ├── config_loader.py
│   └── checkpoint.py
├── output/                                # 运行时产出（gitignored）
│   ├── raw_texts/
│   ├── excluded/
│   └── (各种中间和最终 CSV/JSON/TXT 文件)
└── checkpoints/                           # 断点续传（gitignored）
```

## 适用研究类型

Skill 套件是**通用的、可配置的**，适用于任何基于裁判文书的法学实证研究：

- 反歧视诉讼研究（如已有的 421 件案例）
- 劳动争议中法院裁判影响因素
- 环境公益诉讼的司法认定标准
- 知识产权侵权赔偿金额的影响因素
- 刑事案件量刑的地区差异
- 行政诉讼中原告胜诉率的决定因素
- ...任何可以从裁判文书中提取结构化变量的研究

换研究主题只需在对话中描述新的研究问题，Skill 会自动调整字段 Schema 和抽取规则。

## 支持的字段类型

| 类型 | 说明 | 示例 |
|------|------|------|
| `open_text` | Agent 独立总结的开放文本 | 事件描述、裁判要点 |
| `categorical` | 分类标签 | 地区（省份）、审级、案由 |
| `binary` | 二分类（0/1） | 是否支持、是否涉及性别歧视 |
| `date` | 日期 | 审结日期 |
| `text_copy` | 从原文直接摘录 | 案号、当事人援引法律 |
| `derived` | 从其他字段派生 | 裁判年份（从日期提取） |

每种字段类型都有对应的校验规则：正则匹配、关键词交叉验证、取值约束检查。

## 常见问题

### Q: 我的文书是 .doc 格式，需要装 LibreOffice 吗？

不需要。Git Bash 自带的 `antiword` 可以直接处理 .doc 文件。如果 antiword 不可用，Skill 会自动引导你安装 LibreOffice 作为备选。

### Q: 信息抽取不用 API，用 Claude Code Agent，成本怎么算？

信息抽取是 Claude Code 会话内的工作。每个 Agent 读取一份文书的关键段落（约 1500-3500 字），输出一段 JSON。成本取决于你的 Claude 订阅方案。对于 500 份文书，预计消耗 200K-400K tokens。

### Q: 处理到一半中断了怎么办？

Skill 每批处理完自动保存 checkpoint。下次触发时自动检测并从上次中断的位置继续。所有中间文件（CSV、JSONL）都可以用作断点续传的起点。

### Q: 我能只运行其中某个步骤吗？

可以。每个 Tool Skill 都是独立可触发的。比如只运行格式转化：

```
帮我把 ./文书/ 里的 doc 转成文本
```

### Q: 抽取字段的准确率怎么样？

内置的 `quality-checker` 会自动随机抽样验证。建议在正式分析前跑一次质量检验：对准确率 <85% 的字段调整抽取 prompt 后重新执行。

### Q: 我可以用 Stata/R/SPSS 打开输出的 CSV 吗？

可以。`final_labeled_data.csv` 是标准 UTF-8 编码的 CSV 文件，可直接导入 Stata（`import delimited`）、R（`read.csv`）、SPSS 等统计软件。

## 约束与原则

- **忠实原文**：信息抽取严格基于裁判文书原文，不推断、不补全、不编造
- **可复现**：所有映射规则、剔除标准、归总逻辑记录在配置文件中
- **沟通确认**：边界不清的判断性问题标记 REVIEW_NEEDED，由研究者裁定
- **开放独立**：开放文本字段每个案件独立总结，不强制统一表述

## 版本

### v1.1 — 2026年7月

**两大核心更新：**

#### 1. 数据标准化
- **比例/程度/强度**统一为小数格式（0-1），如 60% → `0.6`
- **日期**统一为 `YYYY-MM-DD`（连字符），如 `2026-01-08`
- **二进制标签**统一为整数 `0` / `1`（不再混用"是/否"文本）
- 所有 Skill 和配置文件的字段定义均已同步更新

#### 2. AI 幻觉检测与修正程序
- **逐字段比对原文**：随机抽样后，Agent 读取原始裁判文书逐字段验证 AI 抽取结果
- **三级分类**：🔴编造 / 🟡偏差 / ✅匹配
- **动态抽样**：<100条全量检验，100-1000条抽30%，>1000条抽15%
- **系统性错误自动标记**：同一字段 >50%出错 → 全量回溯重抽
- **迭代清零**：发现编造 → 抽样翻倍 → 打乱重抽 → 直到连续两轮零编造
- **用户确认不可跳过**：所有疑似编造条目由研究者逐案裁定

#### 其他改进
- 信息抽取从裸 Agent 集群升级为 **Workflow `pipeline()`** 编排，自动管理子 Agent 生命周期，杜绝 token 泄漏

### v1.0 — 2026年7月
首次发布

## 许可

GPL v3
-**copyleft**：使用此开源项目的**衍生作品也必须以相同许可证开源**
