#!/usr/bin/env python3
"""
Image Embedding Fallback Server

Provides OpenAI-compatible image embeddings using Ollama by:
1. Generating captions using a vision LLM (e.g., llava)
2. Embedding those captions using a text embedding model (e.g., nomic-embed-text)

This works around Ollama's lack of native image embedding support.
"""

import argparse
import base64
import io
import sys
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
    import httpx
    import numpy as np
    from PIL import Image
    import uvicorn
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install fastapi uvicorn httpx pillow numpy pydantic")
    sys.exit(1)


app = FastAPI(title="Image Embedding Fallback Server")

# Configuration (set via CLI args)
CONFIG = {
    "ollama_url": "http://localhost:11434",
    "vision_model": "llava",
    "embed_model": "nomic-embed-text",
    "vision_prompt": "Describe this image in detail, focusing on what's visible:",
}


class EmbeddingRequest(BaseModel):
    model: str
    input: list  # OpenAI format with image objects


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: list
    model: str
    usage: dict


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "vision_model": CONFIG["vision_model"], "embed_model": CONFIG["embed_model"]}


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
@app.post("/embeddings", response_model=EmbeddingResponse)
async def create_embedding(request: EmbeddingRequest):
    """OpenAI-compatible embedding endpoint for images."""

    # Extract image from request
    image_data = None
    for item in request.input:
        if isinstance(item, dict) and item.get("type") == "image":
            image_data = extract_image(item)
            break

    if not image_data:
        raise HTTPException(status_code=400, detail="No image found in request. Expected OpenAI format with type='image'")

    # Step 1: Generate description using vision model
    try:
        description = await generate_image_description(image_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vision model error: {e}")

    # Step 2: Embed the description
    try:
        embedding = await embed_text(description)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding model error: {e}")

    return EmbeddingResponse(
        data=[{
            "object": "embedding",
            "index": 0,
            "embedding": embedding,
        }],
        model=request.model,
        usage={"prompt_tokens": 0, "total_tokens": 0},
    )


def extract_image(item: dict) -> Optional[Image.Image]:
    """Extract PIL Image from OpenAI image format."""
    source = item.get("source", {})

    if source.get("type") == "base64":
        data = source.get("data", "")
        img_bytes = base64.b64decode(data)
        return Image.open(io.BytesIO(img_bytes))

    return None


async def generate_image_description(image: Image.Image) -> str:
    """Generate text description of image using vision model via Ollama."""

    # Convert to base64
    buffered = io.BytesIO()
    if image.mode != "RGB":
        image = image.convert("RGB")
    image.save(buffered, format="PNG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{CONFIG['ollama_url']}/api/generate",
            json={
                "model": CONFIG['vision_model'],
                "prompt": CONFIG['vision_prompt'],
                "images": [img_base64],
                "stream": False,
            },
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()

    return data.get("response", "").strip()


async def embed_text(text: str) -> list:
    """Get embedding for text using embedding model via Ollama."""

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{CONFIG['ollama_url']}/api/embeddings",
            json={
                "model": CONFIG['embed_model'],
                "prompt": text,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

    return data.get("embedding", [])


def main():
    parser = argparse.ArgumentParser(
        description="Fallback Image Embedding Server - Provides OpenAI-compatible image embeddings via Ollama"
    )
    parser.add_argument("--port", type=int, default=11435, help="Server port (default: 11435)")
    parser.add_argument("--host", default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    parser.add_argument("--vision-model", default="llava", help="Ollama vision model (default: llava)")
    parser.add_argument("--embed-model", default="nomic-embed-text", help="Ollama embedding model (default: nomic-embed-text)")
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama base URL")
    parser.add_argument("--prompt", default=None, help="Custom vision prompt")

    args = parser.parse_args()

    CONFIG['vision_model'] = args.vision_model
    CONFIG['embed_model'] = args.embed_model
    CONFIG['ollama_url'] = args.ollama_url
    if args.prompt:
        CONFIG['vision_prompt'] = args.prompt

    print(f"Starting Image Embedding Fallback Server")
    print(f"  Host: {args.host}")
    print(f"  Port: {args.port}")
    print(f"  Ollama URL: {CONFIG['ollama_url']}")
    print(f"  Vision Model: {CONFIG['vision_model']}")
    print(f"  Embed Model: {CONFIG['embed_model']}")
    print(f"  Prompt: {CONFIG['vision_prompt'][:50]}...")
    print()
    print(f"Test with: curl http://{args.host}:{args.port}/health")
    print()

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
