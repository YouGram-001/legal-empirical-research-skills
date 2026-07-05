---
name: doc-converter
description: >
  将裁判文书（.doc/.docx）批量转化为干净的纯文本（.txt）。
  当用户提起以下任何关键词时触发：转格式、doc转文本、文档预处理、
  格式转化、文书转化、word转txt、裁判文书处理。
  自动检测文件格式，用 antiword/python-docx 转化，移除页眉页脚，
  按裁判文书结构分段，提取元数据（案号、法院、日期等），生成索引表。
argument-hint: "[输入目录] [输出目录]"
user-invocable: true
allowed-tools: Read, Write, Bash, Grep, Glob
---

# 裁判文书格式转化

将 .doc / .docx 格式的裁判文书批量转化为纯文本（.txt），为后续清洗和抽取做准备。

## 触发条件

- "转格式"、"doc转文本"、"文档预处理"
- "把这些文书转成纯文本"
- "格式转化"

## 工作流程

### Step 1: 确认输入

首先与用户确认：
- 文书所在目录（如用户未指定，扫描当前目录寻找 .doc/.docx 文件）
- 输出目录（默认 `output/raw_texts/`）

```
我在以下目录发现了裁判文书：
  - ./裁判文书/解压文件/ (333 个 .doc 文件)
输出将保存到: ./output/raw_texts/
开始转化吗？
```

### Step 2: 检查环境

在运行转化前，检查：
- **antiword**：Git Bash 自带，直接可用。`.doc` 文件首选引擎。
- **python-docx**：需 `pip install python-docx`。`.docx` 文件引擎。
- **LibreOffice**（备选）：如果 antiword 不可用，引导用户安装。

```bash
# 检查 antiword
which antiword

# 检查 python-docx
python -c "import docx; print('OK')" 2>&1
```

### Step 3: 执行转化

调用 `scripts/convert_docs.py`：

```bash
python .claude/skills/doc-converter/scripts/convert_docs.py \
  --input-dir "<文书目录>" \
  --output-dir "output/raw_texts" \
  --index-output "output/index_raw.csv"
```

脚本自动：
1. 扫描输入目录，识别 .doc / .docx 文件
2. .doc → antiword（首选）→ LibreOffice（备选）
3. .docx → python-docx
4. 按裁判文书结构分段（识别"本院认为""经审理查明""判决如下"等标记）
5. 正则提取案号、审理法院、审结日期、审级等元数据
6. 生成 `index_raw.csv`

### Step 4: 汇报结果

转化完成后汇报：
- 成功/失败/跳过数量
- 元数据提取率（案号、法院、日期等）
- 异常文件列表（如有）
- 下一步建议："数据已转化为纯文本，要开始数据清洗吗？"

## 转化引擎

| 格式 | 引擎 | 说明 |
|------|------|------|
| .doc | antiword | Git Bash 自带，零安装 |
| .doc (备选) | LibreOffice headless | 需要安装 LibreOffice |
| .docx | python-docx | `pip install python-docx` |
| .doc (纯Python) | mammoth | `pip install mammoth` |

## 输出

- `output/raw_texts/*.txt` — 转化后的纯文本文件
- `output/index_raw.csv` — 索引表，包含：
  - 原始文件名、转化后路径、转化状态
  - 案号、审理法院、审结日期、审级、文书类型、案由

## 注意事项

- **编码**：所有输出使用 UTF-8 编码
- **页眉页脚**：python-docx 自动排除，antiword 默认不输出页眉页脚
- **分段识别**：基于中文裁判文书的标准五段式结构（首部/事实/理由/裁判结果/尾部）
- **容错**：转化失败的文件记录在 index 中而非中断整体流程
