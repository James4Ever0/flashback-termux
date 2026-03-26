"""Embedding-based semantic search for flashback."""

from pathlib import Path
from typing import List, Optional, Tuple, Union

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None  # type: ignore

from PIL import Image

from flashback.core.config import Config
from flashback.core.database import Database, ScreenshotRecord
from flashback.core.embedding_client import EmbeddingAPIClient


def _check_numpy():
    """Check if numpy is installed, raise helpful error if not."""
    if not HAS_NUMPY:
        raise RuntimeError(
            "numpy is required for embedding search functionality. "
            "Install with: pip install flashback-termux[embedding]"
        )


class BaseEmbeddingSearch:
    """Base class for embedding-based search."""

    def __init__(self, config: Config = None, db: Database = None):
        _check_numpy()
        self.config = config or Config()
        self.db = db or Database(self.config.db_path)

    def _cosine_similarity(self, vec1: "np.ndarray", vec2: "np.ndarray") -> float:
        _check_numpy()
        """Calculate cosine similarity between two vectors."""
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(vec1, vec2) / (norm1 * norm2))

    def _search_by_vector(
        self, query_vec: "np.ndarray", records: List[ScreenshotRecord], embedding_path_attr: str, top_k: int
    ) -> List[Tuple[int, float]]:
        """Search by pre-computed embedding vector."""
        scores = []
        query_norm = np.linalg.norm(query_vec)

        if query_norm == 0:
            return []

        for record in records:
            emb_path = getattr(record, embedding_path_attr, None)
            if not emb_path:
                continue

            try:
                emb_path = Path(emb_path)
                if not emb_path.exists():
                    continue

                emb = np.load(emb_path)
                similarity = self._cosine_similarity(query_vec, emb)
                scores.append((record.id, similarity))
            except Exception:
                continue

        # Sort by similarity descending
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


class TextEmbeddingSearch(BaseEmbeddingSearch):
    """Semantic search using text embeddings (from OCR content)."""

    def __init__(self, config: Config = None, db: Database = None):
        super().__init__(config, db)
        self.client: Optional[EmbeddingAPIClient] = None
        self._init_client()

    def _init_client(self):
        """Initialize the text embedding API client."""
        text_config = self.config.get_text_embedding_config()
        if text_config.get("model"):
            self.client = EmbeddingAPIClient(
                base_url=text_config.get("base_url", "https://api.openai.com/v1"),
                api_key=text_config.get("api_key", ""),
                model=text_config["model"],
                dimension=text_config.get("dimension"),
                extra_headers=text_config.get("extra_headers", {}),
                name="text",
            )

    def search(self, query: str, top_k: int = 20) -> List[Tuple[int, float]]:
        """Search for screenshots matching text query using text embeddings.

        Args:
            query: Text query to search for
            top_k: Number of top results to return

        Returns:
            List of (record_id, score) tuples sorted by relevance
        """
        if self.client is None:
            raise RuntimeError("Text embedding client not initialized")

        query_embedding = self.client.get_text_embedding(query)
        records = self.db.get_all_with_text_embeddings()
        return self._search_by_vector(query_embedding, records, "text_embedding_path", top_k)

    def encode(self, text: str) -> "np.ndarray":
        """Encode text to embedding vector."""
        if self.client is None:
            raise RuntimeError("Text embedding client not initialized")
        return self.client.get_text_embedding(text)


class ImageEmbeddingSearch(BaseEmbeddingSearch):
    """Visual similarity search using image embeddings."""

    def __init__(self, config: Config = None, db: Database = None):
        super().__init__(config, db)
        self.client: Optional[EmbeddingAPIClient] = None
        self._init_client()

    def _init_client(self):
        """Initialize the image embedding API client."""
        image_config = self.config.get_image_embedding_config()
        if image_config.get("model"):
            self.client = EmbeddingAPIClient(
                base_url=image_config.get("base_url", "http://localhost:11434/v1"),
                api_key=image_config.get("api_key", ""),
                model=image_config["model"],
                dimension=image_config.get("dimension"),
                extra_headers=image_config.get("extra_headers", {}),
                name="image",
            )

    def search_by_image(self, image: Union[str, Image.Image, bytes], top_k: int = 20) -> List[Tuple[int, float]]:
        """Search for screenshots visually similar to an image.

        Args:
            image: Image path, PIL Image, or image bytes
            top_k: Number of top results to return

        Returns:
            List of (record_id, score) tuples sorted by relevance
        """
        if self.client is None:
            raise RuntimeError("Image embedding client not initialized")

        # Convert path to PIL Image if needed
        if isinstance(image, str):
            image = Image.open(image)
        elif isinstance(image, bytes):
            image = Image.open(BytesIO(image))

        query_embedding = self.client.get_image_embedding(image)
        records = self.db.get_all_with_image_embeddings()
        return self._search_by_vector(query_embedding, records, "image_embedding_path", top_k)

    def search_by_text(self, query: str, top_k: int = 20) -> List[Tuple[int, float]]:
        """Search for images using text query (requires CLIP-like model).

        Note: This only works if the image embedding model supports text encoding
        (i.e., it's a multimodal model like CLIP).

        Args:
            query: Text description of the image
            top_k: Number of top results to return

        Returns:
            List of (record_id, score) tuples sorted by relevance
        """
        if self.client is None:
            raise RuntimeError("Image embedding client not initialized")

        # Try to use text embedding through the image client
        # This works for CLIP-like models that share embedding space
        try:
            query_embedding = self.client.get_text_embedding(query)
            records = self.db.get_all_with_image_embeddings()
            return self._search_by_vector(query_embedding, records, "image_embedding_path", top_k)
        except Exception as e:
            raise RuntimeError(
                f"Text-to-image search not supported by the configured image embedding model: {e}"
            )

    def encode_image(self, image: Union[str, Image.Image]) -> "np.ndarray":
        """Encode image to embedding vector."""
        if self.client is None:
            raise RuntimeError("Image embedding client not initialized")

        if isinstance(image, str):
            image = Image.open(image)
        return self.client.get_image_embedding(image)


class HybridEmbeddingSearch(BaseEmbeddingSearch):
    """Hybrid search combining text and image embeddings with RRF fusion."""

    def __init__(self, config: Config = None, db: Database = None):
        super().__init__(config, db)
        self.text_search = TextEmbeddingSearch(config, db)
        self.image_search = ImageEmbeddingSearch(config, db)
        self.weights = self.config.get_hybrid_weights()

    def search_fused(
        self,
        text_query: Optional[str] = None,
        image_query: Optional[Union[str, Image.Image]] = None,
        top_k: int = 20,
    ) -> Tuple[List[Tuple[int, float]], dict]:
        """Search with optional text and/or image queries, fusing results.

        Args:
            text_query: Optional text query
            image_query: Optional image query (path or PIL Image)
            top_k: Number of top results to return

        Returns:
            Tuple of (results, metadata) where results is List[(record_id, score)]
            and metadata contains score breakdown
        """
        from flashback.search.fusion import reciprocal_rank_fusion

        text_results: List[Tuple[int, float]] = []
        image_results: List[Tuple[int, float]] = []

        # Get text search results
        if text_query and self.text_search.client:
            try:
                text_results = self.text_search.search(text_query, top_k=top_k * 2)
            except Exception as e:
                print(f"[HybridSearch] Text search error: {e}")

        # Get image search results
        if image_query and self.image_search.client:
            try:
                if isinstance(image_query, str) and Path(image_query).exists():
                    image_results = self.image_search.search_by_image(image_query, top_k=top_k * 2)
                elif isinstance(image_query, Image.Image):
                    image_results = self.image_search.search_by_image(image_query, top_k=top_k * 2)
            except Exception as e:
                print(f"[HybridSearch] Image search error: {e}")

        # Fuse results using RRF
        rrf_k = self.weights.get("rrf_k", 60)

        # Determine weights based on what queries were provided
        if text_query and image_query:
            text_weight = self.weights.get("text_weight", 0.5)
            image_weight = self.weights.get("image_weight", 0.5)
        elif text_query:
            text_weight = 1.0
            image_weight = 0.0
        elif image_query:
            text_weight = 0.0
            image_weight = 1.0
        else:
            return [], {"error": "No query provided"}

        # Normalize weights
        total = text_weight + image_weight
        if total > 0:
            text_weight /= total
            image_weight /= total

        # Apply RRF fusion
        if text_results and image_results:
            fused = reciprocal_rank_fusion(text_results, image_results, top_k=top_k, k=rrf_k)
        elif text_results:
            fused = text_results[:top_k]
        elif image_results:
            fused = image_results[:top_k]
        else:
            fused = []

        metadata = {
            "text_results_count": len(text_results),
            "image_results_count": len(image_results),
            "text_weight": text_weight,
            "image_weight": image_weight,
            "rrf_k": rrf_k,
        }

        return fused, metadata


# Backwards compatibility alias
EmbeddingSearch = TextEmbeddingSearch
