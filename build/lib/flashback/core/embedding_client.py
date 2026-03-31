"""OpenAI-compatible embedding API client for flashback."""

import base64
import io
from typing import Any, Dict, List, Optional, Union

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None  # type: ignore

from PIL import Image

try:
    import requests

    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    requests = None  # type: ignore


def _check_numpy():
    """Check if numpy is installed, raise helpful error if not."""
    if not HAS_NUMPY:
        raise RuntimeError(
            "numpy is required for embedding functionality. "
            "Install with: pip install flashback-termux[embedding]"
        )


class EmbeddingAPIClient:
    """Client for OpenAI-compatible embedding APIs.

    Supports both text and image embeddings via HTTP API calls.
    Compatible with OpenAI, Ollama, LocalAI, llama.cpp server, etc.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dimension: Optional[int] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        name: str = "embedding",
    ):
        """Initialize the embedding API client.

        Args:
            base_url: API base URL (e.g., "https://api.openai.com/v1" or "http://localhost:11434/v1")
            api_key: API key (can be empty for local servers)
            model: Model name to use for embeddings
            dimension: Expected embedding dimension (optional, for validation)
            extra_headers: Additional HTTP headers to include
            name: Client name for logging ("text" or "image")
        """
        if not HAS_REQUESTS:
            raise RuntimeError(
                "requests not installed. Run: pip install requests"
            )

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimension = dimension
        self.extra_headers = extra_headers or {}
        self.name = name

        # Setup headers
        self.headers = {
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"

        # Detect endpoint type
        self._endpoint_type = self._detect_endpoint_type()

    def _detect_endpoint_type(self) -> str:
        """Detect the type of API endpoint."""
        # Ollama uses /api/embeddings
        if "/v1" not in self.base_url and ("11434" in self.base_url or "ollama" in self.base_url.lower()):
            return "ollama"
        # Standard OpenAI-compatible uses /embeddings
        return "openai"

    def _get_embedding_url(self) -> str:
        """Get the embeddings endpoint URL."""
        if self._endpoint_type == "ollama":
            return f"{self.base_url}/api/embeddings"
        return f"{self.base_url}/embeddings"

    def _validate_dimension(self, embedding: "np.ndarray") -> "np.ndarray":
        _check_numpy()
        """Validate embedding dimension matches expected."""
        if self.dimension is not None:
            if embedding.shape[0] != self.dimension:
                raise ValueError(
                    f"Embedding dimension mismatch for {self.name}: "
                    f"expected {self.dimension}, got {embedding.shape[0]}. "
                    f"Update config: workers.embedding.{self.name}.dimension"
                )
        return embedding

    def get_text_embedding(self, text: str) -> "np.ndarray":
        _check_numpy()
        """Get embedding vector for text.

        Args:
            text: Input text to embed

        Returns:
            Numpy array of embedding vector
        """
        url = self._get_embedding_url()

        if self._endpoint_type == "ollama":
            payload = {
                "model": self.model,
                "prompt": text,
            }
        else:
            payload = {
                "model": self.model,
                "input": text,
            }

        try:
            response = requests.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()

            # Parse response based on endpoint type
            if self._endpoint_type == "ollama":
                # Ollama returns: {"embedding": [...]}
                embedding = np.array(data["embedding"], dtype=np.float32)
            else:
                # OpenAI returns: {"data": [{"embedding": [...]}]}
                embedding_data = data.get("data", [{}])[0]
                if "embedding" in embedding_data:
                    embedding = np.array(embedding_data["embedding"], dtype=np.float32)
                else:
                    # Direct embedding array
                    embedding = np.array(embedding_data, dtype=np.float32)

            return self._validate_dimension(embedding)

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Text embedding API call failed for {self.name}: {e}")
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected API response format: {e}. Response: {data}")

    def get_image_embedding(self, image: Union[Image.Image, str, bytes]) -> "np.ndarray":
        _check_numpy()
        """Get embedding vector for an image.

        Args:
            image: PIL Image, path string, or image bytes

        Returns:
            Numpy array of embedding vector
        """
        # Convert to PIL Image if needed
        if isinstance(image, str):
            image = Image.open(image)
        elif isinstance(image, bytes):
            image = Image.open(io.BytesIO(image))

        # Convert to base64
        buffered = io.BytesIO()
        # Convert to RGB if necessary (handles RGBA, etc.)
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

        url = self._get_embedding_url()

        if self._endpoint_type == "ollama":
            # Ollama vision model format
            payload = {
                "model": self.model,
                "prompt": "Describe this image",  # Required but may be ignored by embedding endpoint
                "images": [img_base64],
            }
        else:
            # OpenAI-style image embedding
            payload = {
                "model": self.model,
                "input": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_base64,
                        },
                    }
                ],
            }

        try:
            response = requests.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()

            # Parse response
            if self._endpoint_type == "ollama":
                embedding = np.array(data.get("embedding", []), dtype=np.float32)
                if embedding.size == 0:
                    # Try alternative response format
                    embedding = np.array(data.get("embeddings", [[]])[0], dtype=np.float32)
            else:
                embedding_data = data.get("data", [{}])[0]
                if "embedding" in embedding_data:
                    embedding = np.array(embedding_data["embedding"], dtype=np.float32)
                else:
                    embedding = np.array(embedding_data, dtype=np.float32)

            if embedding.size == 0:
                raise ValueError(f"Empty embedding returned from {self.name} API")

            return self._validate_dimension(embedding)

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Image embedding API call failed for {self.name}: {e}")
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected API response format: {e}. Response: {data}")

    def test_connection(self) -> Dict[str, Any]:
        """Test the API connection and return info.

        Returns:
            Dict with success status, dimension (if detected), and message
        """
        try:
            # Try text embedding as a test
            test_text = "Test connection"
            embedding = self.get_text_embedding(test_text)
            return {
                "success": True,
                "dimension": embedding.shape[0],
                "message": f"Successfully connected. Detected dimension: {embedding.shape[0]}",
            }
        except Exception as e:
            return {
                "success": False,
                "dimension": None,
                "message": str(e),
            }

    def test_image_embedding(self, image_path: Optional[str] = None) -> Dict[str, Any]:
        """Test image embedding capability.

        Args:
            image_path: Optional path to test image (creates a simple test image if not provided)

        Returns:
            Dict with success status, dimension (if detected), and message
        """
        try:
            if image_path:
                image = Image.open(image_path)
            else:
                # Create a simple test image
                image = Image.new("RGB", (100, 100), color="red")

            embedding = self.get_image_embedding(image)
            return {
                "success": True,
                "dimension": embedding.shape[0],
                "message": f"Image embedding successful. Detected dimension: {embedding.shape[0]}",
            }
        except Exception as e:
            return {
                "success": False,
                "dimension": None,
                "message": str(e),
            }
