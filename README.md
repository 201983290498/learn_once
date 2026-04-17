# Learn-Once：让 Claude Code 记住走过的路

> 第一次走过的路，第二次直接参考。踩过的坑，不会再踩第二次。

---

## 故事从一个熟悉的场景开始

深夜 11 点，你让 Agent 完成一个任务："把本地 docx 和 pptx 文件上传到飞书，在知识库里创建归档文档"。

Agent 信心满满地选择了 `lark-wiki` 的 `+import` 命令，结果报错——pptx 不支持 import 格式。你告诉它："pptx 要用 `lark-drive` 上传，docx 才能用 `lark-wiki` 导入。"

Agent 修正后继续，又在创建归档文档时选错了 Hook 类型。你再次纠正。

第七轮对话结束时，任务终于完成了。你看着长长的对话记录，心想："这条路走通了，但下次遇到类似任务，难道还要重新走一遍这些弯路吗？"

**更现实的困境是**：你的项目里已经有 20+ 个 skills 了。每个 skill 都很强大，但 Agent 总是在"选哪个 skill、选哪个工具"上反复踩坑。日常工作流往往是重复的——上传文件、归档文档、同步数据。每次都要重新解释背景、重新纠偏、重新试错。

**这不是你想要的协作方式。** 你想要的是：第一次走过的路，第二次能直接参考；踩过的坑，下次会提前预警；重复的工作流，一次沉淀，多次复用。

**RAG Trajectory Skills 就是为了解决这个问题而生。**

---

## 三大痛点，三个答案

**痛点一：Skills 越来越多，Agent 却总在选技能时踩坑**

项目里的 skills 和工具越来越多，Agent 的能力确实变强了，但面对复杂任务时，"选哪个 skill、选哪个工具、选哪个近似能力"反而成了主要成本。典型表现：在多个近似 skill 之间来回尝试、选错工具导致返工、最终通过多轮试错才逼近正确解法。

**答案：轨迹沉淀 + 策略型推荐**

通过 `/trajectory-capture`（或 `/tc`）手动触发，系统会先与你确认"这次要沉淀的任务边界是什么"，然后自动定位对应的会话日志，提炼多轮对话中的纠偏点、关键判断、有效路径，生成结构化轨迹文档存入经验库。

下次遇到相似任务，通过 `/trajectory-suggest`（或 `/ts`），系统会召回相似历史轨迹，生成面向当前任务的策略型经验建议，明确告诉你：先做什么、后做什么、选什么工具、避什么坑。

**就像给你的项目装了一个"经验库"**：第一次走通的路，下次可以直接参考；踩过的坑，下次会提前预警。

**痛点二：复杂任务需要多轮纠偏，但日常工作流是重复的**

很多任务看似复杂，实则是"多轮纠偏"的结果。真正昂贵的不是最后那一下"改对了"，而是这一路上的试错、纠偏与选择。而日常工作流往往是重复的——上传文件、归档文档、同步数据。每次都要重新解释背景、重新探索、重新试错。

**答案：结构化轨迹文档**

每条轨迹不是"对话总结"，而是"可复用的经验说明书"，包含：任务一句话说明这条轨迹要解决什么、前置与约束说明环境目录和不可做项、有效路径按顺序列清楚怎么做、关键纠偏点说明哪里错过为什么错怎么改回来、工具 skill 调用提纯说明哪些调用保留哪些删掉、复用提示说明未来遇到什么情况能直接照抄。

**就像人类工程师的工作笔记**：不是记录"某天某时做了什么"，而是记录"这类问题怎么处理、最容易在哪里出错、上次是怎么解决的"。

**痛点三：如何最小化对主 Agent 上下文的影响**

沉淀复杂任务时，如果把完整多轮对话传给子 Agent，会挤占主 Agent 的上下文窗口。但不传完整对话，子 Agent 又无法理解任务全貌。

**答案：上下文控制 + 子 Agent 自主定位**

主 Agent 只传达轻量的"任务边界"（confirmed_task_description + anchor_user_message），然后由 `trajectory-memory-constructor` 子 Agent 自主完成所有后续工作：调用 `locate_session.py` 定位会话日志，从 `~/.claude/projects/{project-path}/*.jsonl` 读取原始轨迹，按 SOP 精炼，生成轨迹草稿。

**关键设计**：主 Agent 不传递完整对话，只传任务边界；子 Agent 拥有完整的自主定位与提取证据的能力。最小化对主 Agent 上下文的占用。

**就像人类团队的协作方式**：Leader 只交代"做什么、边界是什么"，执行者自己去查资料、找证据、完成工作，不需要 Leader 把背景知识全部复述一遍。

---

## 核心设计：如何解决三大痛点？

### 问题一：Skills 越来越多，Agent 却总在踩坑

**问题根源**：Skills 和工具越来越多，Agent 在"选哪个 skill、选哪个工具"上更容易踩坑。而历史经验散落在对话记录里，无法直接复用。

**解决方案**：

RAG Trajectory 提供两个核心命令。`/trajectory-capture`（手动沉淀）在你完成一个复杂任务、觉得"这条路走通了，值得沉淀"时触发。系统会先与你确认"这次要沉淀的任务边界"，然后创建 `trajectory-memory-constructor` 子 Agent，子 Agent 自主定位日志、提炼经验、生成轨迹草稿，你确认草稿后正式入库。

`/trajectory-suggest`（策略型推荐）在你遇到一个新任务、想参考历史经验时触发。系统会召回相似历史轨迹，生成面向当前任务的策略型经验建议，明确告诉你先做什么后做什么选什么工具避什么坑。

**关键设计**：轨迹不是"对话总结"，而是"可复用的经验说明书"；推荐不是"罗列历史"，而是"面向当前任务的策略型建议"。

**就像有经验的搭档**：在你开始之前，先告诉你"这类问题通常怎么处理、最容易在哪里出错、上次是怎么解决的"。

### 问题二：复杂任务需要多轮纠偏，但日常工作流是重复的

**问题根源**：多轮对话中，真正有价值的是"怎么从走偏走到正确轨道"的过程，但这个过程散落在长长的对话记录里，难以直接复用。

**解决方案**：

`trajectory-memory-constructor` 的核心工作不是"转写聊天记录"，而是把多轮对话、工具调用、用户纠偏和最终成功路径压缩成一份可复用的经验说明书。它遵循严格的 SOP：分类标注每个步骤（progress/correction/exploration/noise/verification），判断交互模式（纠偏模式 vs 递进模式），应用精炼规则（保留所有纠偏点关键判断有效路径，压缩连续同类步骤，删除纯噪音），生成结构化轨迹 Markdown（含 frontmatter 元数据、核心纠偏点、步骤流程）。

**关键设计**：主 Agent 只传达任务边界，不传递完整对话（避免上下文过载）；子 Agent 自主定位日志、自主判断哪些该保留哪些该删；产物不是"对话总结"，而是"可复用的经验说明书"。

**就像人类工程师的工作笔记**：不是记录"某天某时做了什么"，而是记录"这类问题怎么处理、最容易在哪里出错、上次是怎么解决的"。

### 问题三：如何最小化对主 Agent 上下文的影响

**问题根源**：沉淀复杂任务时，如果把完整多轮对话传给子 Agent，会挤占主 Agent 的上下文窗口。但不传完整对话，子 Agent 又无法理解任务全貌。

**解决方案**：

主 Agent 只传达轻量的"任务边界"（confirmed_task_description + anchor_user_message），然后由 `trajectory-memory-constructor` 子 Agent 自主完成所有后续工作。主 Agent 只传任务边界：
```json
{
  "session_locator": {
    "task": "<confirmed_task_description>",
    "anchor_user_message": "<anchor_user_message>",
    "workspace_folder": "<当前工作目录路径>"
  }
}
```

子 Agent 自主定位：调用 `locate_session.py` 定位会话日志，从 `~/.claude/projects/{project-path}/*.jsonl` 读取原始轨迹，按 SOP 精炼，生成轨迹草稿。返回摘要供确认：
```json
{
  "task_description": "<task_description>",
  "trajectory_summary": "<trajectory_summary>",
  "trajectory_file": "<path to the saved .md file>"
}
```

**关键设计**：主 Agent 只传达任务边界，不传递完整对话；子 Agent 拥有完整的自主定位与提取证据的能力；最小化对主 Agent 上下文的占用。

**就像人类团队的协作方式**：Leader 只交代"做什么、边界是什么"，执行者自己去查资料、找证据、完成工作，不需要 Leader 把背景知识全部复述一遍。

---

## 安装说明

### 前置条件

- **Claude Code**：确保已安装并配置好 Claude Code
- **oh-my-claudecode (OMC)**：RAG Trajectory 依赖 OMC 的插件系统
- **Python 环境**：需要 Python 3.6+（用于运行召回、定位、入库脚本）
- **依赖库**：`numpy`、`requests`

### 安装步骤

**步骤 1：安装依赖**

```bash
cd learn-once
pip install -r requirements.txt
```

**步骤 2：配置运行时参数**

创建运行时配置目录和文件：

```bash
mkdir -p ~/.claude/learn-once
cat > ~/.claude/learn-once/config.json << 'EOF'
{
    "JINA_API_KEY": "your_jina_api_key_here",
    "enable_auto_recall": true
}
EOF
```

获取 Jina API Key: https://jina.ai/embeddings/

**步骤 3：加载插件**

有三种方式：

**方式一：通过 OMC 插件注册到 Marketplace（推荐）**

```bash
/plugin marketplace add <git-repo-url>
```

**方式二：通过 --plugin-dir 加载（开发/本地使用）**

启动 Claude Code 时指定插件目录：

```bash
claude --plugin-dir /path/to/learn-once
```

或在 oh-my-claudecode 中通过 `omc --plugin-dir`：

```bash
omc --plugin-dir /path/to/learn-once
```

> **注意**：使用 `--plugin-dir` 时，hooks.json 中的 `$CLAUDE_PLUGIN_ROOT` 环境变量需要正确设置：
> ```bash
> export CLAUDE_PLUGIN_ROOT=/path/to/learn-once
> claude --plugin-dir /path/to/learn-once
> ```

**方式三：复制到用户插件目录（手动安装）**

将项目复制到 Claude Code 的插件缓存目录，然后在 settings 中启用：

```bash
# 1. 复制到插件缓存
mkdir -p ~/.claude/plugins/cache/manual/learn-once/latest
cp -r * ~/.claude/plugins/cache/manual/learn-once/latest/

# 2. 在 ~/.claude/settings.json 的 enabledPlugins 中添加
#    "learn-once@manual": true

# 3. 在 installed_plugins.json 中注册安装信息
```

> 注：方式三需要手动修改多个 JSON 文件，不推荐，仅作了解。

**步骤 4：验证安装**

确保以下文件结构存在：

```
learn-once/
├── .claude-plugin/plugin.json      # 插件声明（agents + skills）
├── AGENTS.md                       # 关键词路由表
├── agents/
│   ├── trajectory-memory-constructor.md
│   └── trajectory-memory-suggester.md
├── skills/
│   ├── trajectory-capture/SKILL.md
│   ├── trajectory-suggest/SKILL.md
│   └── trajectory-status/SKILL.md
├── hooks/hooks.json                # Hook 事件定义
├── scripts/
│   ├── python/
│   │   ├── locate_session.py       # 会话日志定位
│   │   ├── recall_trajectory.py    # 向量相似度召回
│   │   └── ingest_trajectory.py    # Markdown → embedding 入库
│   └── hooks/auto_recall.js        # UserPromptSubmit 自动触发
├── docs/                           # 设计文档（仅供参考，不随插件加载）
├── config.json                     # 项目级配置模板
└── requirements.txt
```

---

## 使用示例

### 场景一：手动沉淀经验

你完成了一个复杂任务，想沉淀经验：

```bash
/trajectory-capture
# 或缩写
/tc
```

系统会：回顾最近对话，提出 2-4 个候选任务范围；你确认要沉淀的任务边界；自动定位日志、提炼经验、生成轨迹草稿；你确认草稿后，正式入库。

**入库报告**：
```
轨迹沉淀完成。
- 任务：把本地 docx 和 pptx 文件上传到飞书，并在知识库里创建归档文档
- 轨迹 ID：feishu_wiki_upload_archive_v1
- 文件：~/.claude/learn-once/trajectories/feishu_wiki_upload_archive_v1.md
- 适用场景：需要区分 docx(import) 与 pptx(upload) 的正确上传方式
- 关键纠偏点：入口触发应使用 UserPromptSubmit 而非 PreToolUse
```

### 场景二：获取推荐规划

你遇到一个新任务，想参考历史经验：

```bash
/trajectory-suggest
# 或缩写
/ts
```

系统会：召回相似历史轨迹；生成面向当前任务的策略型经验建议。

**推荐规划**：
```
## 推荐规划

1. 先探索目标 skill 目录结构，理解现有设计
2. 对比参考 skill 的结构，提取可复用模式
3. 基于对比结果，生成结构化改进计划

完整建议已写入 `~/.claude/learn-once/state/active_suggestion.md`，请参考执行。
```

### 场景三：查看轨迹统计

你想了解已沉淀的轨迹情况：

```bash
/trajectory-status
# 或缩写
/tst
```

系统会返回：已沉淀轨迹数量、按 tags 分布的统计、最近更新的轨迹列表。

### 自动推荐模式

在 `~/.claude/learn-once/config.json` 中设置 `enable_auto_recall: true`，每轮对话前系统会自动检查历史经验。

---

## 技术亮点

| 亮点 | 传统做法 | RAG Trajectory |
|------|---------|----------------|
| 经验沉淀 | 对话结束即清零 | 结构化轨迹文档，永久保存 |
| 经验复用 | 每次重新探索 | 向量检索召回，策略型建议 |
| 上下文管理 | 完整对话传给子 Agent | 只传任务边界，子 Agent 自主定位 |
| 轨迹精炼 | 线性总结 | 结构化解剖 + 选择性压缩 |
| 技能选择 | 在近似 skill 间试错 | 历史经验明确推荐路径 |

---

## 运行时文件

| 路径 | 用途 |
|------|------|
| `~/.claude/learn-once/config.json` | 运行时配置 |
| `~/.claude/learn-once/trajectories/*.md` | 轨迹文件 |
| `~/.claude/learn-once/meta/meta.json` | 元数据索引 |
| `~/.claude/learn-once/index/embeddings.pkl` | 向量索引 |
| `~/.claude/learn-once/state/active_suggestion.md` | 当前推荐规划 |

---

## 设计哲学

> **"不是总结过去，而是指导未来"**

RAG Trajectory 不是"对话总结工具"，而是"经验复用系统"。

通过轨迹沉淀，把多轮对话中的纠偏经验固化为可复用的文档；通过策略型推荐，把历史经验转化为面向当前任务的行动建议；通过上下文控制，让主 Agent 不被长任务挤占上下文窗口。

最终，让 Claude Code 记住走过的路，减少重复试错成本。

---

**🎉 现在，让你的 Claude Code 记住走过的路吧！**
