"""Tokenizer backends for search (BM25)."""

import re
from abc import ABC, abstractmethod
from typing import List


class BaseTokenizer(ABC):
    """Base class for tokenizers."""

    @abstractmethod
    def tokenize(self, text: str) -> List[str]:
        """Tokenize text into a list of terms."""
        pass


class SimpleTokenizer(BaseTokenizer):
    """Simple regex tokenizer (ASCII only)."""

    def tokenize(self, text: str) -> List[str]:
        if not text:
            return []
        return re.findall(r"[a-zA-Z0-9]+", text.lower())


class SpacyTokenizer(BaseTokenizer):
    """Spacy tokenizer for multilingual text."""

    def __init__(self, model: str = "en_core_web_sm", auto_download: bool = True):
        self.model = model
        self.auto_download = auto_download
        self._nlp = None

    def _ensure_model(self):
        """Ensure spacy model is loaded."""
        if self._nlp is not None:
            return self._nlp

        try:
            import spacy
            self._nlp = spacy.load(self.model)
        except OSError:
            if self.auto_download:
                import spacy.cli
                spacy.cli.download(self.model)
                self._nlp = spacy.load(self.model)
            else:
                raise
        return self._nlp

    def tokenize(self, text: str) -> List[str]:
        """Tokenize text using spacy."""
        if not text:
            return []
        try:
            nlp = self._ensure_model()
            doc = nlp(text)
            return [token.text.lower() for token in doc]
        except Exception:
            # Fallback to simple tokenizer
            return SimpleTokenizer().tokenize(text)


class JiebaTokenizer(BaseTokenizer):
    """Jieba tokenizer for Chinese."""

    def __init__(self, mode: str = "accurate"):
        self.mode = mode
        self._jieba = None

    def _ensure_jieba(self):
        if self._jieba is None:
            import jieba
            self._jieba = jieba
        return self._jieba

    def tokenize(self, text: str) -> List[str]:
        if not text:
            return []
        try:
            jieba = self._ensure_jieba()
            if self.mode == "search":
                return list(jieba.cut_for_search(text))
            elif self.mode == "full":
                return list(jieba.cut(text, cut_all=True))
            else:  # accurate
                return list(jieba.cut(text, cut_all=False))
        except Exception:
            # Fallback to simple tokenizer
            return SimpleTokenizer().tokenize(text)


class AutoTokenizer(BaseTokenizer):
    """Auto-detect language and use appropriate tokenizer."""

    def __init__(self, config: dict):
        self.config = config
        # Default to en_core_web_sm for English, can be configured for other languages
        spacy_model = config.get("spacy", {}).get("model", "en_core_web_sm")
        self.spacy = SpacyTokenizer(
            model=spacy_model,
            auto_download=config.get("spacy", {}).get("auto_download", True)
        )
        self.jieba = JiebaTokenizer(
            mode=config.get("jieba", {}).get("mode", "accurate")
        )
        self.simple = SimpleTokenizer()
        self.threshold = config.get("language_confidence_threshold", 0.7)

    def _detect_language(self, text: str) -> str:
        """Detect if text is primarily Chinese or English."""
        if not text:
            return "simple"

        # Count Chinese characters (CJK range)
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        total_chars = len(text.strip())

        if total_chars == 0:
            return "simple"

        ratio = chinese_chars / total_chars
        if ratio > self.threshold:
            return "chinese"
        elif ratio < 0.1:  # Less than 10% Chinese, assume English
            return "english"
        else:
            return "mixed"

    def tokenize(self, text: str) -> List[str]:
        if not text:
            return []

        lang = self._detect_language(text)

        if lang == "chinese":
            return self.jieba.tokenize(text)
        elif lang == "english":
            return self.spacy.tokenize(text)
        else:  # mixed or unknown
            # For mixed text, try jieba first (handles both)
            try:
                return self.jieba.tokenize(text)
            except:
                return self.spacy.tokenize(text)


def get_tokenizer(config: dict) -> BaseTokenizer:
    """Factory function to get tokenizer based on config.

    Args:
        config: Tokenizer configuration dict

    Returns:
        Tokenizer instance
    """
    backend = config.get("backend", "jieba")  # Default to jieba

    if backend == "spacy":
        return SpacyTokenizer(
            model=config.get("spacy", {}).get("model", "en_core_web_sm"),
            auto_download=config.get("spacy", {}).get("auto_download", True)
        )
    elif backend == "jieba":
        return JiebaTokenizer(
            mode=config.get("jieba", {}).get("mode", "accurate")
        )
    elif backend == "simple":
        return SimpleTokenizer()
    else:  # auto
        return AutoTokenizer(config)
