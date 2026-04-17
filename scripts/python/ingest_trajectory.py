#!/usr/bin/env python3
"""
ingest_trajectory.py - 从轨迹 Markdown 文件入库到 meta.json + pkl

用法:
    python ingest_trajectory.py <trajectory_md_path>
    python ingest_trajectory.py --all

从 trajectory-format-mvp.md 规定的 Markdown 文件中解析字段，
构建 embedding 文本，调用 Jina API 生成向量，
更新 meta.json 和 pkl 文件。
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

import numpy as np
import requests

# --- 路径配置 ---

DEFAULT_META_PATH = Path.home() / '.claude' / 'learn-once' / 'meta' / 'meta.json'
DEFAULT_PKL_PATH = Path.home() / '.claude' / 'learn-once' / 'index' / 'embeddings.pkl'
DEFAULT_TRAJECTORIES_DIR = Path.home() / '.claude' / 'learn-once' / 'trajectories'

# --- Jina Embedding 配置 ---

JINA_API_URL = "https://api.jina.ai/v1/embeddings"
JINA_MODEL = "jina-embeddings-v3"
JINA_DIMS = 1024

DEFAULT_CONFIG_PATH = Path.home() / '.claude' / 'learn-once' / 'config.json'


def get_jina_api_key() -> str:
    """
    按优先级获取 Jina API Key：
    1. ~/.claude/learn-once/config.json 中的 JINA_API_KEY
    2. 环境变量 JINA_API_KEY
    3. 默认值
    """
    # 1. 从 config.json 读取
    if DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
        api_key = config.get('JINA_API_KEY')
        if api_key:
            return api_key

    # 2. 从环境变量读取
    api_key = os.environ.get('JINA_API_KEY')
    if api_key:
        return api_key

    # 3. 使用默认值
    return 'jina_98991993c3bd430ea16e1b2e285d39b23Y1BH2w92d75LHE0ENq7rsCJPszz'


def generate_embeddings(texts: List[str], api_key: str) -> List[List[float]]:
    """
    调用 Jina API 批量生成 embedding

    Args:
        texts: 文本列表
        api_key: Jina API key

    Returns:
        embedding vectors list
    """
    if not texts:
        return []

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": JINA_MODEL,
        "input": texts,
        "encoding_format": "float",
        "dimensions": JINA_DIMS
    }

    response = requests.post(JINA_API_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    result = response.json()

    embeddings = [item['embedding'] for item in result['data']]

    for emb in embeddings:
        if len(emb) != JINA_DIMS:
            raise ValueError(f"Expected {JINA_DIMS} dims, got {len(emb)}")

    return embeddings


def parse_frontmatter(md_path: Path) -> Dict[str, Any]:
    """
    解析 Markdown 文件的 YAML frontmatter

    Returns:
        包含 trajectory_id, task, when_to_use, tags, trigger_keywords 的字典
    """
    content = md_path.read_text(encoding='utf-8')

    # 匹配 frontmatter 块
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if not match:
        raise ValueError(f"No YAML frontmatter found in {md_path}")

    fm_text = match.group(1)
    fields: Dict[str, Any] = {}

    for line in fm_text.split('\n'):
        line = line.strip()
        if not line:
            continue

        # 简单 YAML 解析（支持字符串、列表）
        if ':' not in line:
            continue

        key, _, value = line.partition(':')
        key = key.strip()
        value = value.strip()

        if value.startswith('[') and value.endswith(']'):
            # 内联列表: ["a", "b"]
            items = re.findall(r'"([^"]*)"', value)
            fields[key] = items
        elif value.startswith('- '):
            # 列表项（单行）
            fields[key] = [value[2:].strip()]
        elif value.startswith('"') and value.endswith('"'):
            fields[key] = value[1:-1]
        else:
            fields[key] = value

    return fields


def build_embedding_texts(fields: Dict[str, Any]) -> Dict[str, str]:
    """
    根据解析出的字段构建多个 embedding 文本

    Returns:
        {text_type: text} 字典
    """
    task = fields.get('task', '')
    when_to_use = fields.get('when_to_use', [])
    tags = fields.get('tags', [])
    trigger_keywords = fields.get('trigger_keywords', [])

    if isinstance(when_to_use, str):
        when_to_use = [when_to_use]
    if isinstance(tags, str):
        tags = [tags]
    if isinstance(trigger_keywords, str):
        trigger_keywords = [trigger_keywords]

    texts = {}

    # 主索引文本
    index_text = f"{task} {' '.join(when_to_use)} {' '.join(tags)} {' '.join(trigger_keywords)}"
    texts['index_text'] = index_text.strip()

    # task 单独文本
    if task:
        texts['task'] = task.strip()

    # when_to_use 聚合文本
    wtu_text = ' '.join(when_to_use).strip()
    if wtu_text:
        texts['when_to_use'] = wtu_text

    return texts


def load_meta_json(meta_path: Path) -> Dict[str, Any]:
    """加载 meta.json，不存在则返回空字典"""
    if meta_path.exists():
        with open(meta_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_meta_json(meta_path: Path, meta: Dict[str, Any]):
    """保存 meta.json"""
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def load_pkl(pkl_path: Path) -> dict:
    """加载 pkl 文件，不存在则返回空结构"""
    import pickle
    if pkl_path.exists():
        with open(pkl_path, 'rb') as f:
            return pickle.load(f)
    return {
        "embedding_text": [],
        "embedding": np.array([], dtype=np.float32).reshape(0, JINA_DIMS)
    }


def save_pkl(pkl_path: Path, data: dict):
    """保存 pkl 文件"""
    import pickle
    pkl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pkl_path, 'wb') as f:
        pickle.dump(data, f)


def append_to_pkl(pkl_data: dict, new_texts: List[str], new_embeddings: List[List[float]]) -> dict:
    """
    追加新的 embedding 到 pkl 数据

    Args:
        pkl_data: 现有 pkl 数据
        new_texts: 新的 embedding_text 列表
        new_embeddings: 新的 embedding 向量列表

    Returns:
        更新后的 pkl 数据
    """
    pkl_data['embedding_text'].extend(new_texts)

    new_emb_array = np.array(new_embeddings, dtype=np.float32)

    if pkl_data['embedding'].shape[0] == 0:
        pkl_data['embedding'] = new_emb_array
    else:
        pkl_data['embedding'] = np.vstack([pkl_data['embedding'], new_emb_array])

    return pkl_data


def ingest_single(md_path: Path, meta_path: Path, pkl_path: Path, api_key: str):
    """入库单条轨迹"""
    print(f"Ingesting: {md_path}")

    # 1. 解析 frontmatter
    fields = parse_frontmatter(md_path)
    trajectory_id = fields.get('trajectory_id', '')
    if not trajectory_id:
        raise ValueError(f"No trajectory_id found in {md_path}")

    print(f"  trajectory_id: {trajectory_id}")
    print(f"  task: {fields.get('task', '')[:80]}...")

    # 2. 构建 embedding 文本
    embedding_texts = build_embedding_texts(fields)
    print(f"  Embedding texts: {list(embedding_texts.keys())}")

    # 3. 生成 embedding
    text_list = list(embedding_texts.values())
    embeddings = generate_embeddings(text_list, api_key)
    print(f"  Generated {len(embeddings)} embeddings ({JINA_DIMS} dims each)")

    # 4. 更新 meta.json
    meta = load_meta_json(meta_path)
    abs_path = str(md_path.resolve())

    for emb_text in embedding_texts.keys():
        meta[emb_text] = {
            "trajectory_id": trajectory_id,
            "file_path": abs_path
        }

    save_meta_json(meta_path, meta)
    print(f"  Updated meta.json ({len(meta)} entries)")

    # 5. 追加 pkl
    pkl_data = load_pkl(pkl_path)

    # 去重：如果 embedding_text 已存在，先移除旧向量
    existing_texts = set(pkl_data['embedding_text'])
    new_texts = []
    new_embeddings = []
    indices_to_remove = []

    for i, txt in enumerate(pkl_data['embedding_text']):
        if txt in embedding_texts:
            indices_to_remove.append(i)

    if indices_to_remove:
        # 移除旧向量
        mask = np.ones(len(pkl_data['embedding_text']), dtype=bool)
        mask[indices_to_remove] = False
        pkl_data['embedding_text'] = [t for i, t in enumerate(pkl_data['embedding_text']) if mask[i]]
        pkl_data['embedding'] = pkl_data['embedding'][mask]

    for emb_text, emb_vec in zip(embedding_texts.keys(), embeddings):
        new_texts.append(emb_text)
        new_embeddings.append(emb_vec)

    pkl_data = append_to_pkl(pkl_data, new_texts, new_embeddings)
    save_pkl(pkl_path, pkl_data)
    print(f"  Updated pkl ({len(pkl_data['embedding_text'])} total embeddings)")


def ingest_all(trajectories_dir: Path, meta_path: Path, pkl_path: Path, api_key: str):
    """批量入库所有轨迹"""
    md_files = sorted(trajectories_dir.glob('*.md'))
    if not md_files:
        print(f"No .md files found in {trajectories_dir}")
        return

    print(f"Found {len(md_files)} trajectory file(s)")

    for md_file in md_files:
        try:
            ingest_single(md_file, meta_path, pkl_path, api_key)
        except Exception as e:
            print(f"  FAILED: {md_file.name}: {e}")
            continue

    print(f"\nDone. Ingested {len(md_files)} trajectory file(s).")


def main():
    parser = argparse.ArgumentParser(description='Ingest trajectory Markdown into meta.json + pkl')
    parser.add_argument('md_path', nargs='?', help='Path to trajectory Markdown file')
    parser.add_argument('--all', action='store_true', help='Ingest all trajectories')
    parser.add_argument('--meta-path', type=str, help='Override meta.json path')
    parser.add_argument('--pkl-path', type=str, help='Override pkl path')
    parser.add_argument('--trajectories-dir', type=str, help='Override trajectories directory')
    args = parser.parse_args()

    meta_path = Path(args.meta_path).expanduser() if args.meta_path else DEFAULT_META_PATH
    pkl_path = Path(args.pkl_path).expanduser() if args.pkl_path else DEFAULT_PKL_PATH
    trajectories_dir = Path(args.trajectories_dir).expanduser() if args.trajectories_dir else DEFAULT_TRAJECTORIES_DIR

    try:
        api_key = get_jina_api_key()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if args.all:
        ingest_all(trajectories_dir, meta_path, pkl_path, api_key)
    elif args.md_path:
        md_path = Path(args.md_path).expanduser()
        if not md_path.exists():
            print(f"Error: {md_path} not found")
            sys.exit(1)
        ingest_single(md_path, meta_path, pkl_path, api_key)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
