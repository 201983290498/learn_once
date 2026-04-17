#!/usr/bin/env python3
"""
locate_session.py - 根据 anchor_user_message 定位 Claude Code 会话轨迹

通过搜索 ~/.claude/projects/{project-path}/*.jsonl 找到匹配的行，
然后从该行开始到文件末尾，提取为新的轨迹会话文件。

用法:
    python locate_session.py \
        --anchor-user-message "<用户最初的提问>" \
        --workspace-folder "<工作目录路径>"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def project_path_from_cwd(cwd: str) -> str:
    """将工作目录路径转为 Claude Code 项目路径格式。
    规则：每个非 ASCII 字母数字字符替换为 '-'。
    """
    return re.sub(r'[^a-zA-Z0-9]', '-', cwd)


def find_session_dir() -> Path:
    """返回 Claude Code 会话目录路径。"""
    return Path.home() / ".claude" / "projects"


def _normalize(text: str) -> str:
    """去除空白后小写，用于模糊匹配。"""
    return "".join(text.strip().lower().split())


def _extract_all_text(value) -> str:
    """从任意嵌套 JSON 结构中递归提取所有文本片段。"""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_extract_all_text(item) for item in value)
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if k in {"content", "text", "input", "output", "message"}:
                parts.append(_extract_all_text(v))
            elif isinstance(v, (str, list, dict)):
                parts.append(_extract_all_text(v))
        return "\n".join(parts)
    return str(value) if value is not None else ""


def search_anchor_in_file(file_path: Path, anchor: str) -> int | None:
    """在 .jsonl 文件中搜索 anchor_user_message，返回首次匹配的行号（1-indexed），未找到返回 None。"""
    anchor_norm = _normalize(anchor)
    with open(file_path, "r", encoding="utf-8") as f:
        for line_number, raw_line in enumerate(f, start=1):
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            # 递归提取所有文本内容并搜索
            full_text = _extract_all_text(payload)
            if anchor_norm and anchor_norm in _normalize(full_text):
                return line_number

    return None


def _simplify_message(payload: dict) -> dict | None:
    """将原始会话记录压缩为 role + content 结构。

    删除字段:
      - isMeta / isSidechain / parentUuid / uuid / timestamp 等追踪信息
      - progress / file-history-snapshot / last-prompt / 空 system 等非对话消息
    保留字段:
      - role + content（含 thinking / tool_use / tool_result / text）
      - tool_use.id + tool_result.tool_use_id（调用-结果链路）
    截断策略:
      - tool_result 内容限 500 字符
      - 超长字符串限 200 字符
    """
    msg_type = payload.get("type")

    # 丢弃非对话类型
    if msg_type not in ("user", "assistant"):
        return None
    if payload.get("isMeta"):
        return None

    msg = payload.get("message", {})
    if not msg:
        return None

    role = msg.get("role", msg_type)
    content = msg.get("content", "")

    # 列表内容块 → 简化每个 block
    if isinstance(content, list):
        simplified: list[dict] = []
        for block in content:
            bt = block.get("type")
            if bt == "text":
                simplified.append({"type": "text", "text": block.get("text", "")})
            elif bt == "thinking":
                simplified.append({"type": "thinking", "thinking": block.get("thinking", "")})
            elif bt == "tool_use":
                simplified.append({
                    "type": "tool_use",
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "input": block.get("input", {}),
                })
            elif bt == "tool_result":
                c = block.get("content", "")
                # agent 工具结果：content 是列表，第二项为 agentId/usage 元数据，丢弃
                if isinstance(c, list) and len(c) > 1:
                    c = c[0]
                simplified.append({
                    "type": "tool_result",
                    "tool_use_id": block.get("tool_use_id", ""),
                    "content": c[:500] if isinstance(c, str) else c,
                    "is_error": block.get("is_error", False),
                })
        content = simplified

    # 超长字符串截断
    elif isinstance(content, str) and len(content) > 5000:
        content = content[:200] + "\n...[truncated]..."

    result = {"role": role, "content": content}

    # 保留 isCompactSummary 标记（压缩后注入的会话摘要）
    if payload.get("isCompactSummary"):
        result["isCompactSummary"] = True

    return result


def simplify_trajectory(input_path: Path, output_path: Path) -> dict:
    """预处理原始 .jsonl 会话文件，输出简化版对话记录。

    返回统计信息 dict。
    """
    kept = 0
    dropped = 0
    thinking_count = 0
    tool_use_count = 0
    tool_result_count = 0

    with open(input_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                dropped += 1
                continue

            simplified = _simplify_message(payload)
            if simplified is None:
                dropped += 1
                continue

            json.dump(simplified, fout, ensure_ascii=False)
            fout.write("\n")
            kept += 1

            # 统计
            for block in (simplified["content"] if isinstance(simplified["content"], list) else []):
                bt = block.get("type")
                if bt == "thinking":
                    thinking_count += 1
                elif bt == "tool_use":
                    tool_use_count += 1
                elif bt == "tool_result":
                    tool_result_count += 1

    import os
    return {
        "input_size_kb": round(os.path.getsize(input_path) / 1024, 1),
        "output_size_kb": round(os.path.getsize(output_path) / 1024, 1),
        "kept": kept,
        "dropped": dropped,
        "thinking_blocks": thinking_count,
        "tool_use_blocks": tool_use_count,
        "tool_result_blocks": tool_result_count,
        "reduction_pct": round((1 - os.path.getsize(output_path) / max(os.path.getsize(input_path), 1)) * 100),
    }


def _is_trajectory_capture_command(payload: dict) -> bool:
    """检测是否为 /trajectory-capture 命令的触发消息。

    精确匹配 user 消息中包含 <command-message>trajectory-capture</command-message> 的行。
    不匹配仅包含 "trajectory-capture" 字样的文件路径或普通文本。
    """
    if payload.get("type") != "user":
        return False
    msg = payload.get("message", {})
    if not msg:
        return False
    content = msg.get("content", "")
    # 精确匹配 <command-message>trajectory-capture</command-message>
    marker = "<command-message>trajectory-capture</command-message>"
    # content 可能是字符串
    if isinstance(content, str) and marker in content:
        return True
    # content 可能是列表，其中某个 text block 包含标记
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                text = block.get("text", "")
                if marker in text:
                    return True
    return False


def _find_end_line(file_path: Path, start_line: int) -> int | None:
    """从 start_line 开始搜索 /trajectory-capture 命令，返回匹配行号（1-indexed）。
    未找到返回 None，表示应输出到文件末尾。
    """
    with open(file_path, "r", encoding="utf-8") as f:
        for i, raw_line in enumerate(f, start=1):
            if i < start_line:
                continue
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if _is_trajectory_capture_command(payload):
                return i
    return None


def extract_from_line(file_path: Path, start_line: int, output_path: Path) -> dict:
    """从指定行号开始提取，遇到 /trajectory-capture 命令时停止（不包含该行）。

    如果找不到 /trajectory-capture，则输出到文件末尾。
    返回统计信息 dict。
    """
    end_line = _find_end_line(file_path, start_line)
    kept = 0
    dropped = 0

    with open(file_path, "r", encoding="utf-8") as src, \
         open(output_path, "w", encoding="utf-8") as dst:
        for i, raw_line in enumerate(src, start=1):
            if i < start_line:
                continue
            if end_line is not None and i >= end_line:
                break
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                dropped += 1
                continue

            simplified = _simplify_message(payload)
            if simplified is None:
                dropped += 1
                continue

            json.dump(simplified, dst, ensure_ascii=False)
            dst.write("\n")
            kept += 1

    import os
    info = {
        "output_size_kb": round(os.path.getsize(output_path) / 1024, 1),
        "kept": kept,
        "dropped": dropped,
    }
    if end_line is not None:
        info["stopped_at"] = f"{file_path.name}:{end_line} (trajectory-capture found)"
    else:
        info["stopped_at"] = f"{file_path.name}:EOF (no trajectory-capture found)"
    return info


def main():
    parser = argparse.ArgumentParser(
        description="根据 anchor_user_message 定位并提取 Claude Code 会话轨迹"
    )
    parser.add_argument(
        "--anchor-user-message",
        required=True,
        help="用户最初的提问，用于定位轨迹起点",
    )
    parser.add_argument(
        "--workspace-folder",
        required=True,
        help="当前工作目录路径",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出文件路径（默认: /tmp/trajectory-session-<uuid>.jsonl）",
    )
    args = parser.parse_args()

    anchor = args.anchor_user_message
    cwd = args.workspace_folder

    # 1. 找到会话目录
    proj_path = project_path_from_cwd(cwd)
    session_dir = find_session_dir() / proj_path

    if not session_dir.is_dir():
        print(f"[ERROR] 会话目录不存在: {session_dir}", file=sys.stderr)
        sys.exit(1)

    jsonl_files = sorted(session_dir.glob("*.jsonl"))
    if not jsonl_files:
        print(f"[ERROR] 会话目录下没有 .jsonl 文件: {session_dir}", file=sys.stderr)
        sys.exit(1)

    # 2. 逐个搜索 anchor 消息
    matched_file = None
    matched_line = None

    for jl in jsonl_files:
        line = search_anchor_in_file(jl, anchor)
        if line is not None:
            matched_file = jl
            matched_line = line
            break

    if matched_file is None:
        print(f"[ERROR] 未找到匹配的 anchor 消息: {anchor!r}", file=sys.stderr)
        print(f"搜索范围: {session_dir}/*.jsonl ({len(jsonl_files)} 个文件)", file=sys.stderr)
        sys.exit(1)

    # 3. 提取并输出简化版轨迹
    output_path = Path(args.output) if args.output else Path(f"/tmp/trajectory-session-{matched_file.stem}.simple.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    stats = extract_from_line(matched_file, matched_line, output_path)

    print(f"[OK] 找到 anchor: {matched_file.name}:{matched_line}")
    print(f"[OK] 已提取简化轨迹: {output_path}")
    print(f"[OK] 保留 {stats['kept']} 条消息，丢弃 {stats['dropped']} 条，输出 {stats['output_size_kb']} KB")
    print(f"[OK] 停止位置: {stats['stopped_at']}")


if __name__ == "__main__":
    main()
