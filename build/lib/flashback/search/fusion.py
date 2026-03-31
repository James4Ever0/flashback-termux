"""Search result fusion for hybrid search."""

from typing import Dict, List, Tuple


def reciprocal_rank_fusion(
    *result_lists: List[Tuple[int, float]],
    k: int = 60,
    top_k: int = 20,
) -> List[Tuple[int, float]]:
    """
    Merge multiple ranked lists using Reciprocal Rank Fusion (RRF).

    RRF formula: score = sum(1 / (k + rank)) for each list

    Args:
        result_lists: Multiple lists of (id, score) tuples
        k: RRF constant (higher = more weight to lower ranks)
        top_k: Number of results to return

    Returns:
        Merged list of (id, score) tuples sorted by RRF score
    """
    # Track ranks for each document in each list
    doc_scores: Dict[int, float] = {}

    for results in result_lists:
        for rank, (doc_id, _) in enumerate(results, start=1):
            rrf_score = 1.0 / (k + rank)
            doc_scores[doc_id] = doc_scores.get(doc_id, 0.0) + rrf_score

    # Sort by RRF score descending
    fused = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
    return fused[:top_k]


def weighted_fusion(
    bm25_results: List[Tuple[int, float]],
    embedding_results: List[Tuple[int, float]],
    bm25_weight: float = 0.3,
    embedding_weight: float = 0.7,
    top_k: int = 20,
) -> List[Tuple[int, float]]:
    """
    Merge search results using weighted score combination.

    Args:
        bm25_results: BM25 search results
        embedding_results: Embedding search results
        bm25_weight: Weight for BM25 scores
        embedding_weight: Weight for embedding scores
        top_k: Number of results to return

    Returns:
        Merged list of (id, score) tuples
    """
    # Normalize scores to [0, 1] range
    def normalize(results: List[Tuple[int, float]]) -> Dict[int, float]:
        if not results:
            return {}
        max_score = max(s for _, s in results) if results else 1.0
        min_score = min(s for _, s in results) if results else 0.0
        range_score = max_score - min_score if max_score > min_score else 1.0

        return {
            doc_id: (score - min_score) / range_score
            for doc_id, score in results
        }

    bm25_norm = normalize(bm25_results)
    embedding_norm = normalize(embedding_results)

    # Combine scores
    all_docs = set(bm25_norm.keys()) | set(embedding_norm.keys())
    combined: Dict[int, float] = {}

    for doc_id in all_docs:
        score = (
            bm25_weight * bm25_norm.get(doc_id, 0.0)
            + embedding_weight * embedding_norm.get(doc_id, 0.0)
        )
        combined[doc_id] = score

    # Sort by combined score descending
    results = sorted(combined.items(), key=lambda x: x[1], reverse=True)
    return results[:top_k]
