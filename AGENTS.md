# Learn-Once - Agent 路由

## 概述

本插件为 Claude Code 提供轨迹记忆能力：将成功的交互模式捕获为可复用的经验，并在类似任务出现时进行召回。

## 关键词触发规则

| 关键词 / 命令 | 动作 | 描述 |
|---|---|---|
| `/trajectory-capture` 或 `/tc` | 加载 `skills/trajectory-capture/SKILL.md` | 手动捕获并精炼当前会话的轨迹经验 |
| `/trajectory-suggest` 或 `/ts` | 加载 `skills/trajectory-suggest/SKILL.md` | 召回相似轨迹并生成规划建议 |
| `/trajectory-status` 或 `/tst` | 加载 `skills/trajectory-status/SKILL.md` | 显示已存储轨迹的统计概览 |
| 用户提及 "轨迹沉淀" 或 "capture trajectory" | 加载 `skills/trajectory-capture/SKILL.md` | 捕获的自然语言触发 |
| 用户提及 "轨迹推荐" 或 "suggest trajectory" | 加载 `skills/trajectory-suggest/SKILL.md` | 推荐的自然语言触发 |

## Agent 目录

| Agent | 文件 | 模型层级 | 用途 |
|---|---|---|---|
| `trajectory-memory-constructor` | `agents/trajectory-memory-constructor.md` | MEDIUM (Sonnet) | 读取会话日志，将多轮轨迹精炼为结构化经验文档 |
| `trajectory-memory-suggester` | `agents/trajectory-memory-suggester.md` | MEDIUM (Sonnet) | 检查规划覆盖范围，召回相似轨迹，生成可执行的规划建议 |

## 流水线定义

### 捕获流水线 (`/trajectory-capture`)
1. 主 agent 回顾最近的对话，提出 2-4 个候选任务范围
2. 用户确认目标任务
3. 主 agent 创建 `trajectory-memory-constructor`，传入 `session_locator`
4. Constructor 运行 `locate_session.py` → 读取原始日志 → 按 SOP 精炼 → 写入草稿
5. 主 agent 向用户展示草稿以供确认
6. 确认后：写入 `~/.claude/learn-once/trajectories/` → 运行 `ingest_trajectory.py`

### 建议流水线（通过 hook 自动触发或 `/trajectory-suggest`）
1. `UserPromptSubmit` hook 读取 `~/.claude/learn-once/config.json` → 若启用则注入提示
2. 主 agent 创建 `trajectory-memory-suggester`，传入当前提示 + 状态
3. Suggester 读取 `~/.claude/learn-once/state/active_suggestion.md` → 检查覆盖范围
4. 若 coverage_in → 返回 "无更多参考"
5. 若 coverage_out → 运行 `recall_trajectory.py` → 按 SOP 生成新规划 → 写入状态文件
