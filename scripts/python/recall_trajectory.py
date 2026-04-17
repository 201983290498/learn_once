#!/usr/bin/env python3
"""
recall_trajectory.py - 从 task 描述召回最相似的轨迹

用法:
    python recall_trajectory.py "<task 描述>"
    python recall_trajectory.py "<task 描述>" --top-k 3
    python recall_trajectory.py "<task 描述>" --json

输入 task 描述，生成 embedding 后与 pkl 中的向量进行矩阵相似度运算，
返回按 file_path 去重后的 top_k 轨迹列表。
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

import numpy as np
import requests

# --- 路径配置 ---

DEFAULT_META_PATH = Path.home() / '.claude' / 'learn-once' / 'meta' / 'meta.json'
DEFAULT_PKL_PATH = Path.home() / '.claude' / 'learn-once' / 'index' / 'embeddings.pkl'

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


def generate_embedding(text: str, api_key: str) -> List[float]:
    """
    调用 Jina API 生成单个 embedding

    Args:
        text: 查询文本
        api_key: Jina API key

    Returns:
        embedding vector (list of floats)
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": JINA_MODEL,
        "input": [text],
        "encoding_format": "float",
        "dimensions": JINA_DIMS
    }

    response = requests.post(JINA_API_URL, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    result = response.json()

    embedding = result['data'][0]['embedding']

    if len(embedding) != JINA_DIMS:
        raise ValueError(f"Expected {JINA_DIMS} dims, got {len(embedding)}")

    return embedding


def cosine_similarity_matrix(query: np.ndarray, embeddings: np.ndarray) -> np.ndarray:
    """
    计算查询向量与多个向量的余弦相似度

    Args:
        query: shape (D,) 或 (1, D)
        embeddings: shape (N, D)

    Returns:
        shape (N,) 的相似度数组
    """
    query_norm = np.linalg.norm(query)
    emb_norms = np.linalg.norm(embeddings, axis=1)

    if query.ndim == 1:
        query = query.reshape(1, -1)

    dot_products = (query @ embeddings.T).flatten()

    similarities = dot_products / (query_norm * emb_norms)
    return similarities


def load_meta_json(meta_path: Path) -> Dict[str, Any]:
    """加载 meta.json"""
    with open(meta_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_pkl(pkl_path: Path) -> dict:
    """加载 pkl 文件"""
    import pickle
    with open(pkl_path, 'rb') as f:
        return pickle.load(f)


def recall_trajectories(
    query: str,
    top_k: int = 5,
    meta_path: Optional[Path] = None,
    pkl_path: Optional[Path] = None,
    api_key: Optional[str] = None,
) -> List[Tuple[str, float]]:
    """
    召回最相似的轨迹

    Args:
        query: task 描述文本
        top_k: 返回数量
        meta_path: meta.json 路径
        pkl_path: pkl 文件路径
        api_key: Jina API key

    Returns:
        [(file_path, score), ...] 列表，按 file_path 去重，按 score 降序
    """
    meta_path = meta_path or DEFAULT_META_PATH
    pkl_path = pkl_path or DEFAULT_PKL_PATH
    api_key = api_key or get_jina_api_key()

    # 1. 生成查询 embedding
    print(f"Generating embedding for query: '{query[:60]}...'")
    query_embedding = generate_embedding(query, api_key)
    query_array = np.array(query_embedding, dtype=np.float32)
    print(f"  Generated {len(query_embedding)}-dim embedding")

    # 2. 加载 pkl
    print(f"Loading pkl: {pkl_path}")
    pkl_data = load_pkl(pkl_path)
    embedding_texts = pkl_data['embedding_text']
    embeddings = pkl_data['embedding']
    print(f"  Loaded {len(embedding_texts)} embeddings, shape: {embeddings.shape}")

    # 3. 矩阵相似度运算
    print("Computing cosine similarity...")
    scores = cosine_similarity_matrix(query_array, embeddings)

    # 4. 按相似度排序
    sorted_indices = np.argsort(scores)[::-1]

    # 5. 查找文件路径并按 file_path 去重
    meta = load_meta_json(meta_path)
    seen_paths = set()
    results = []

    for idx in sorted_indices:
        emb_text = embedding_texts[idx]
        score = float(scores[idx])

        # 从 meta.json 查找 file_path
        entry = meta.get(emb_text)
        if not entry:
            continue

        file_path = entry.get('file_path', '')
        if not file_path:
            continue

        # 按 file_path 去重，保留最高分
        if file_path not in seen_paths:
            seen_paths.add(file_path)
            results.append((file_path, round(score, 4)))

        if len(results) >= top_k:
            break

    return results


def format_results(results: List[Tuple[str, float]]) -> str:
    """格式化输出结果"""
    if not results:
        return "No matching trajectories found."

    output = []
    for i, (path, score) in enumerate(results, 1):
        output.append(f"\n{i}. {Path(path).name}")
        output.append(f"   File: {path}")
        output.append(f"   Score: {score}")

    return '\n'.join(output)


def main():
    parser = argparse.ArgumentParser(description='Recall similar trajectories by task description')
    parser.add_argument('query', help='Task description text')
    parser.add_argument('--top-k', type=int, default=5, help='Number of results (default: 5)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--meta-path', type=str, help='Override meta.json path')
    parser.add_argument('--pkl-path', type=str, help='Override pkl path')
    args = parser.parse_args()

    meta_path = Path(args.meta_path).expanduser() if args.meta_path else DEFAULT_META_PATH
    pkl_path = Path(args.pkl_path).expanduser() if args.pkl_path else DEFAULT_PKL_PATH

    if not meta_path.exists():
        print(f"Error: meta.json not found at {meta_path}")
        print("Run ingest_trajectory.py first")
        sys.exit(1)

    if not pkl_path.exists():
        print(f"Error: pkl file not found at {pkl_path}")
        print("Run ingest_trajectory.py first")
        sys.exit(1)

    try:
        api_key = get_jina_api_key()
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    results = recall_trajectories(
        query=args.query,
        top_k=args.top_k,
        meta_path=meta_path,
        pkl_path=pkl_path,
        api_key=api_key,
    )

    # 输出结果
    if args.json:
        output = [{"file_path": path, "score": score} for path, score in results]
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"\nRecall results for: '{args.query}' (top_k={args.top_k})")
        print(format_results(results))


if __name__ == '__main__':
    main()
