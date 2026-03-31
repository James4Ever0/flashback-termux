# Image Embedding Fallback Server

A standalone microservice that provides **OpenAI-compatible image embeddings** using [Ollama](https://ollama.com), working around Ollama's lack of native image embedding support.

## Problem

Ollama supports vision models (like `llava`) for image understanding, but does **not** expose image embeddings via the OpenAI-compatible `/embeddings` endpoint. This prevents using Ollama for visual similarity search.

## Solution

This server provides a two-step embedding pipeline:

1. **Caption Generation**: Use a vision model (e.g., `llava`) to generate a text description of the image
2. **Text Embedding**: Embed that description using a text embedding model (e.g., `nomic-embed-text`)

The result is a semantically meaningful embedding that captures what's in the image.

## Dependencies

This is a **standalone project** with no relation to the main Flashback codebase.

### Required

```bash
pip install fastapi uvicorn httpx pillow numpy pydantic
```

| Package | Version | Purpose |
|---------|---------|---------|
| fastapi | >=0.100.0 | HTTP server framework |
| uvicorn | >=0.23.0 | ASGI server |
| httpx | >=0.24.0 | HTTP client for Ollama API |
| pillow | >=10.0.0 | Image processing |
| numpy | >=1.24.0 | Array handling |
| pydantic | >=2.0.0 | Data validation |

### External Requirements

- **Ollama** must be running (see [ollama.com](https://ollama.com/download))
- **Vision model** pulled in Ollama (e.g., `ollama pull llava`)
- **Embedding model** pulled in Ollama (e.g., `ollama pull nomic-embed-text`)

## Quick Start

### 1. Install Ollama and Models

```bash
# Install Ollama (see https://ollama.com/download)

# Pull required models
ollama pull llava              # or llava-llama3, bakllava, etc.
ollama pull nomic-embed-text   # or mxbai-embed-large
```

### 2. Install Python Dependencies

```bash
pip install fastapi uvicorn httpx pillow numpy pydantic
```

### 3. Start the Server

```bash
python server.py
```

Or with custom options:

```bash
python server.py \
    --port 11435 \
    --vision-model llava \
    --embed-model nomic-embed-text \
    --ollama-url http://localhost:11434
```

### 4. Test

```bash
# Health check
curl http://localhost:11435/health

# Test embedding (requires a test image)
curl -X POST http://localhost:11435/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "model": "fallback-image",
    "input": [{"type": "image", "source": {"type": "base64", "data": "'$(base64 -w 0 test_image.png)'"}}]
  }'
```

## Usage with Flashback

Configure Flashback to use this server for image embeddings:

```yaml
# ~/.config/flashback/config.yaml
workers:
  embedding:
    mode: "text-image-hybrid"

    text:
      base_url: "http://localhost:11434/v1"
      api_key: ""
      model: "nomic-embed-text"
      dimension: 768

    image:
      # Point to this fallback server instead of Ollama directly
      base_url: "http://localhost:11435/v1"
      api_key: ""
      model: "fallback-image"  # Any name works, server ignores it
      dimension: 768  # Must match text embedding dimension
```

Then test:

```bash
flashback config test-embedding --type image --write
```

## API

### `POST /v1/embeddings`

OpenAI-compatible embedding endpoint.

**Request:**

```json
{
  "model": "fallback-image",
  "input": [
    {
      "type": "image",
      "source": {
        "type": "base64",
        "data": "iVBORw0KGgoAAAANSUhEUgAA..."
      }
    }
  ]
}
```

**Response:**

```json
{
  "object": "list",
  "data": [
    {
      "object": "embedding",
      "index": 0,
      "embedding": [0.023, -0.045, ...]
    }
  ],
  "model": "fallback-image",
  "usage": {
    "prompt_tokens": 0,
    "total_tokens": 0
  }
}
```

### `GET /health`

Health check endpoint.

## Command-Line Options

```
python server.py [OPTIONS]

Options:
  --port PORT          Server port (default: 11435)
  --host HOST          Server host (default: 127.0.0.1)
  --vision-model MODEL Ollama vision model (default: llava)
  --embed-model MODEL  Ollama embedding model (default: nomic-embed-text)
  --ollama-url URL     Ollama base URL (default: http://localhost:11434)
  --prompt PROMPT      Custom vision prompt
```

## Custom Vision Prompts

You can customize how images are described:

```bash
python server.py \
    --prompt "List all visible UI elements, buttons, and text in this screenshot:"
```

This is useful for:
- **Screenshots**: Focus on UI elements and text
- **Photographs**: Focus on objects and scenes
- **Diagrams**: Focus on structure and relationships

## Trade-offs

**Pros:**
- Works with any Ollama setup
- No additional model downloads beyond what Ollama provides
- Descriptions are human-readable (debuggable)
- Captures semantic content well

**Cons:**
- **Slower**: Requires 2 API calls per image (~2-5 seconds total)
- **Lossy**: Fine visual details may be lost in captioning
- **Higher compute**: Running vision model is expensive

## Performance Tips

1. **Use a smaller vision model**: `llava-phi3` is faster than `llava`
2. **Run on GPU**: Ollama uses GPU automatically if available
3. **Cache results**: Consider adding a caching layer for repeated images
4. **Batch processing**: Process multiple images in parallel

## Troubleshooting

**"Connection refused" errors:**
- Ensure Ollama is running: `ollama serve` or check system tray
- Verify Ollama URL with: `curl http://localhost:11434/api/tags`

**"Vision model error":**
- Ensure vision model is pulled: `ollama pull llava`
- Check model name matches exactly (case-sensitive)

**"Embedding model error":**
- Ensure embedding model is pulled: `ollama pull nomic-embed-text`

**Slow responses:**
- First request is slow (model loading)
- GPU acceleration helps significantly
- Consider using smaller models

## Alternatives

| Option | Pros | Cons |
|--------|------|------|
| This fallback | Free, local, works with Ollama | Slower, 2-step process |
| OpenAI CLIP API | Fast, accurate, native image embeddings | Requires API key, not free |
| Jina AI Embeddings | Free tier, supports images | Cloud service, rate limits |
| Self-host CLIP | Fast, free, native embeddings | Requires PyTorch, more setup |

## License

Same as Flashback (MIT)

## No Relation to Main Project

This is an **example/standalone tool** provided as a workaround. It is:
- Not imported by the main Flashback codebase
- Not required for Flashback to function
- Maintained separately as a community utility
