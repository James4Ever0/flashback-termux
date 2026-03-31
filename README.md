# Flashback

Search through your screenshot history with OCR and semantic search.

Flashback continuously captures screenshots, extracts text using OCR, and generates semantic embeddings so you can search through your visual history.

## Features

- **Automatic Screenshot Capture** - Captures your Android screen at configurable intervals (requires root)
- **OCR Text Extraction** - Extracts text from screenshots using Tesseract
- **Semantic Search** - Find screenshots by meaning, not just exact text matches
- **Timeline View** - See context around any screenshot
- **Web UI** - Browser-based search interface
- **CLI** - Command-line search and management
- **Privacy-First** - All data stays local on your device
- **Android/Termux Support** - Designed for Termux on Android with root access

## Installation

**Note:** Flashback for Termux is designed for Android with root access.

```bash
pip install flashback-termux[all]
```

Or install with specific features:
```bash
pip install flashback-termux              # Core only
pip install flashback-termux[ocr]         # With OCR
pip install flashback-termux[search]      # With search capabilities
pip install flashback-termux[embedding]   # With embedding/semantic search
pip install flashback-termux[webui]       # With web interface
```

### System Dependencies

**Tesseract OCR:**

Install tesseract via Termux packages:
```bash
pkg install tesseract
```

**OCR Language Data:**

Language data files are not available via apt in Termux. Download them manually from the [tesseract-ocr/tessdata](https://github.com/tesseract-ocr/tessdata) repository:

```bash
# Create tessdata directory
mkdir -p /data/data/com.termux/files/usr/share/tessdata
cd /data/data/com.termux/files/usr/share/tessdata

# Download language files (examples)
curl -L -o eng.traineddata https://github.com/tesseract-ocr/tessdata/raw/main/eng.traineddata
curl -L -o chi_sim.traineddata https://github.com/tesseract-ocr/tessdata/raw/main/chi_sim.traineddata
curl -L -o chi_tra.traineddata https://github.com/tesseract-ocr/tessdata/raw/main/chi_tra.traineddata
curl -L -o jpn.traineddata https://github.com/tesseract-ocr/tessdata/raw/main/jpn.traineddata

# List available languages at: https://github.com/tesseract-ocr/tessdata
```

### Multi Language Search Support

For searching multilingual text, install spacy for better word segmentation:

```bash
pip install flashback-screenshots[multilingual]  # Or: pip install spacy
```

Then configure the tokenizer in your config:

```yaml
search:
  bm25:
    tokenizer:
      backend: "spacy"  # Default: jieba (good for Chinese/English)
      # Other options:
      # backend: "spacy"    # For multilingual tokenization
      # backend: "simple"   # Fast regex tokenizer (ASCII only)
      # backend: "auto"     # Auto-detect Multilingual

      # Spacy-specific settings
      # For more models, visit: https://spacy.io/models
      spacy:
        model: "en_core_web_sm"  # Options: en_core_web_sm, zh_core_web_sm, etc.
        auto_download: true       # Download model if missing
```

When using `backend: "auto"`, the tokenizer will detect Chinese text and use jieba for segmentation, otherwise use spacy.

## Quick Start

```bash
# 1. (Recommended) Set up Ollama for local embeddings
ollama pull nomic-embed-text
ollama pull llava  # optional, for image search

# 2. Initialize default config
flashback config init

# 3. Edit config for Ollama (see Configuration section below)
flashback config edit

# 4. Test embedding API
flashback config test-embedding --type text --write

# 5. Start the backend daemon
flashback serve --daemon

# 6. Start the web UI (optional)
flashback webui --daemon

# 7. Check status
flashback status

# 8. Search from CLI
flashback search "meeting notes"

# 9. Or open the web UI
open http://localhost:8080
```

## CLI Commands

### `flashback serve`
Start the backend daemon that captures screenshots and processes them.

```bash
flashback serve              # Run in foreground
flashback serve --daemon     # Run as background daemon
```

### `flashback webui`
Start the web UI server.

```bash
flashback webui              # Run on http://localhost:8080
flashback webui --port 3000  # Custom port
```

### `flashback search`
Search through screenshot history.

```bash
# Text search (default: text_hybrid mode)
flashback search "important email"

# Semantic search only
flashback search -m text_embedding_only "dashboard with charts"

# Search with image similarity (requires image embedding configured)
flashback search --image screenshot.png --search-mode image_embedding_only

# Multi-modal: search with both text and image
flashback search "meeting" --image whiteboard.jpg --search-mode text_and_image

# Time range search
flashback search "error" --from 1d --to now

# Show OCR preview in results
flashback search "TODO" --preview -n 10
```

### `flashback view`
View a specific screenshot.

```bash
flashback view 20240320_142312
flashback view 20240320_142312 --text      # Show OCR text
flashback view 20240320_142312 --neighbors  # Show timeline context
```

### `flashback status`
Check daemon health and database stats.

```bash
flashback status
flashback status --json
flashback status -w 5  # Watch mode
```

### `flashback config`
Manage configuration.

```bash
flashback config show
flashback config edit
flashback config set workers.screenshot.interval_seconds 300

# Test embedding API and auto-detect dimensions (for Ollama/OpenAI)
flashback config test-embedding --type text
flashback config test-embedding --type text --write   # Save to config
flashback config test-embedding --type image --image /path/to/test.jpg --write
```

## Configuration

### Configuration File Locations

Flashback looks for `config.yaml` in the following order:

1. **Environment variable** (highest priority):
   ```bash
   export FLASHBACK_CONFIG=/path/to/custom/config.yaml
   flashback status
   ```

2. **Current directory**:
   ```bash
   ./config.yaml
   ```

3. **User config directory** (default):
   ```bash
   ~/.config/flashback/config.yaml
   ```

### Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `FLASHBACK_CONFIG` | Path to config file | `/etc/flashback/config.yaml` |

### Example Configuration

```yaml
data_dir: ~/.local/share/flashback

screenshot:
  interval_seconds: 60
  quality: 85
  backend: "screencap"  # Screenshot backend (only "screencap" is supported on Android/Termux)
  # Note: Screenshots require root access (su) on Android/Termux

workers:
  ocr:
    enabled: true
    languages: ["eng", "chi_sim"]
  embedding:
    enabled: true
  cleanup:
    retention_days: 7
  window_title:
    enabled: true
    poll_interval_seconds: 1      # How often to check active window
    max_screenshot_age_seconds: 30  # Only update screenshots taken within this time

search:
  enabled_methods:
    bm25: true
    text_embedding: true
    image_embedding: true
  bm25:
    refresh_interval_seconds: 600  # BM25 index refresh interval
    tokenizer:
      backend: "jieba"  # Tokenizer: jieba (default), spacy, simple, or auto
      spacy:
        model: "en_core_web_sm"  # Spacy model for multilingual support

# Web UI configuration
webui:
  enabled: true
  host: "127.0.0.1"
  port: 8080
  latest_screenshot_age_limit_seconds: 120  # Max age for /screenshots/now endpoint
```

### Active App Tracking (Window Title)

Flashback can track the active Android app and associate it with screenshots. This helps you search for screenshots based on what app was active when they were taken.

```yaml
workers:
  window_title:
    enabled: true
    poll_interval_seconds: 1      # How often to check the active app (default: 1)
    max_screenshot_age_seconds: 30  # Only associate with screenshots taken within this time window (default: 30)
```

**How it works:**
- The worker polls the active Android app every `poll_interval_seconds` using `dumpsys`
- When the app changes, it finds the most recent screenshot without an app context
- If that screenshot was taken within `max_screenshot_age_seconds`, it updates it with the app name
- This prevents updating old screenshots when you switch apps long after they were captured

**Requirements:**
- Root access (`su`) is required to query the active app on Android
- Optional: `aapt` binary for resolving human-readable app names from package IDs

**Example:** With `max_screenshot_age_seconds: 30`, if you take a screenshot at 10:00:00 and switch to a different app at 10:00:15, the screenshot will be tagged with the new app name. But if you switch apps at 10:00:45 (45 seconds later), the screenshot won't be updated.

### Requirements

**Root Access:** Flashback for Termux requires root access (`su`) for:
- Capturing screenshots via Android's `screencap` binary
- Detecting the active app for window title tracking

**Optional Dependencies:**
- `aapt` binary for resolving human-readable app names from package IDs
- `tesseract-ocr` for OCR text extraction

### Screenshot Backend

Flashback for Termux uses Android's `screencap` binary to capture screenshots. This is the only supported backend on Android/Termux.

```yaml
screenshot:
  backend: "screencap"  # Only "screencap" is supported on Android/Termux
```

If an unsupported backend is configured, the screenshot worker will fail to start with an error message.

### BM25 Index Refresh

Flashback uses BM25 for fast text search on OCR content. The BM25 index is cached in memory and refreshed periodically to include new screenshots without blocking search requests.

```yaml
search:
  bm25:
    refresh_interval_seconds: 600  # Refresh every 10 minutes (default)
```

**How it works:**
- On first search, the BM25 index is built from all screenshots with OCR text
- The index is cached in memory and reused for subsequent searches
- A background thread rebuilds the index every `refresh_interval_seconds`
- The new index is swapped atomically - searches continue using the old index until the new one is ready
- Lower values = fresher results but more CPU usage. Higher values = better performance but may miss very recent screenshots.

**When to adjust:**
- Decrease (e.g., 300 = 5 min) if you frequently search for very recent screenshots
- Increase (e.g., 1800 = 30 min) if you have many screenshots and search performance is more important than freshness

### Using Ollama for Local Embeddings

Flashback supports [Ollama](https://ollama.com) for generating embeddings locally, keeping all your data private and on your machine.

#### 1. Install Ollama

Follow the instructions at [ollama.com/download](https://ollama.com/download) to install Ollama for your platform.

#### 2. Pull an Embedding Model

For text embeddings:
```bash
# Good all-around text embedding model
ollama pull nomic-embed-text

# Alternative: mxbai-embed-large (higher quality, slower)
ollama pull mxbai-embed-large
```

> **Note:** Ollama does not currently support image embeddings via the OpenAI-compatible endpoint. For image similarity search, you need either:
> 1. A different embedding service (e.g., OpenAI's CLIP via API, or self-hosted)
> 2. Use the [fallback image embedding server](../examples/image-embedding-fallback/)
>
> Text embeddings work perfectly with Ollama.

#### 3. Configure Flashback

Edit your `~/.config/flashback/config.yaml`:

```yaml
workers:
  embedding:
    enabled: true
    # Set mode based on your needs:
    # - text-only: Fastest, indexes OCR text only
    # - image-only: Indexes screenshot pixels only (requires vision model)
    # - text-image-hybrid: Indexes both (most accurate, slower)
    mode: "text-image-hybrid"

    # Text embedding configuration (for indexing OCR content)
    text:
      base_url: "http://localhost:11434/v1"
      api_key: ""           # Ollama doesn't require an API key
      model: "nomic-embed-text"
      dimension: null       # Will auto-detect (768 for nomic-embed-text)
      extra_headers: {}

    # Image embedding configuration (for visual similarity)
    # NOTE: Ollama does NOT support image embeddings via OpenAI-compatible endpoint.
    # Options for image search:
    #   1. Use OpenAI CLIP API (requires API key)
    #   2. Use the fallback server (see examples/image-embedding-fallback/)
    #   3. Disable image search: set enabled_methods.image_embedding: false
    image:
      base_url: "http://localhost:11434/v1"
      api_key: ""           # Ollama doesn't require an API key
      model: "llava"
      dimension: null       # Will auto-detect
      extra_headers: {}

    # Hybrid weights for combining text and image search
    hybrid_weights:
      text_weight: 0.5
      image_weight: 0.5
      rrf_k: 60
```

#### 4. Test and Detect Embedding Dimensions

Flashback needs to know the embedding dimension for your models. Test and save it automatically:

```bash
# Test text embedding and save dimension
flashback config test-embedding --type text --write

# Test image embedding and save dimension
flashback config test-embedding --type image --write
```

If the tests pass, you're ready to go! If not, check:
- Ollama is running (`ollama serve` or the system tray app)
- The model name matches what you pulled

#### 5. Start the Daemon

```bash
flashback serve --daemon
```

The embedding worker will now use Ollama to generate embeddings locally.

#### Common Ollama Models Reference

| Model | Type | Dimension | Description |
|-------|------|-----------|-------------|
| nomic-embed-text | Text | 768 | Fast, good quality |
| mxbai-embed-large | Text | 1024 | Higher quality, slower |
| llava | Image | 4096 | Vision + language |
| llava-llama3 | Image | 4096 | Better vision quality |

#### Troubleshooting

**"Connection refused" errors:**
- Ensure Ollama is running: `ollama serve` or check the system tray icon
- Check the base_url matches your Ollama installation (usually `http://localhost:11434/v1`)

**"Empty embedding returned":**
- Some models may not support embeddings properly. Try nomic-embed-text for text or llava for images
- Check Ollama logs for errors

**Slow embedding generation:**
- First embedding is slow (model loading)
- Consider a smaller model if performance is an issue
- GPU acceleration significantly improves speed

## Storage Estimates

Assuming 1920x1080 screenshots at 1 per minute:

| Period | Screenshots | Storage |
|--------|-------------|---------|
| 1 hour | 60 | ~12 MB |
| 1 day | 1,440 | ~300 MB |
| 1 week | 10,080 | ~2.1 GB |

With 7-day retention, expect ~2-3 GB of storage.

## Logging

Flashback provides configurable logging for debugging and monitoring.

### CLI Logging Options

Global verbosity flags can be used with **any** command:

```bash
# Verbosity levels (cumulative -v flags)
flashback -v serve                  # INFO level (general progress)
flashback -vv search "query"        # DEBUG level (detailed diagnostics)
flashback -vvv status               # TRACE level (function entry/exit)

# Alternative forms
flashback --verbose serve           # Same as -v
flashback --debug serve             # Same as -vv
flashback --trace serve             # Same as -vvv (maximum verbosity)
flashback --quiet serve             # Only errors (overrides -v)

# Log to file
flashback serve --log-file /var/log/flashback.log

# Combine options
flashback -vv --log-file flashback.log serve --daemon
```

**Verbosity Levels:**
| Flag | Level | Output |
|------|-------|--------|
| (none) | WARNING | Errors and warnings only |
| `-v` | INFO | General progress messages |
| `-vv` | DEBUG | Detailed diagnostics |
| `-vvv` | TRACE | Function entry/exit, maximum detail |

### Configuration File Logging

```yaml
logging:
  level: INFO

  console:
    enabled: true
    level: INFO
    format: "rich"      # rich, simple, or detailed
    show_location: false

  file:
    enabled: true
    level: DEBUG
    path: "~/.local/share/flashback/flashback.log"
    max_size: "10MB"
    max_files: 5
```

### Environment Variables

```bash
export FLASHBACK_LOG_LEVEL=DEBUG
export FLASHBACK_LOG_FILE=/path/to/flashback.log
export FLASHBACK_VERBOSE=1
export FLASHBACK_TRACE=1
```

### Module-Specific Logging

```yaml
logging:
  modules:
    workers.embedding: DEBUG    # Debug embedding issues
    workers.ocr: WARNING        # OCR can be noisy
    api.server: INFO
```

### Log Levels

| Level | Description |
|-------|-------------|
| `ERROR` | Only errors |
| `WARNING` | Errors and warnings (default) |
| `INFO` | General operation info |
| `DEBUG` | Detailed debug info |

## API

Flashback provides a REST API at `http://localhost:8080/api/v1`:

- `GET /api/v1/search?q=query` - Search screenshots
- `GET /api/v1/screenshots` - List screenshots
- `GET /api/v1/screenshots/{timestamp}` - Get screenshot details
- `GET /api/v1/screenshots/{timestamp}/neighbors` - Timeline context
- `GET /api/v1/status` - System status

## License

MIT License
