"""Semantic relevance filter using Chinese-CLIP."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image

from .base import FilterVerdict, ImageFilter

logger = logging.getLogger(__name__)

DEFAULT_PROMPTS: dict[str, str] = {
    "cake": "蛋糕成品照片",
    "drink": "饮品成品照片",
    "dessert": "甜点特写",
    "bread": "面包烘焙成品",
    "coffee": "咖啡饮料",
}


class ClipRelevanceFilter(ImageFilter):
    """Score images against food-category prompts using Chinese-CLIP ViT-H/14.

    Lazily loads the model on first ``evaluate`` call.
    """

    name = "clip_relevance"

    def __init__(
        self,
        prompts: dict[str, str] | None = None,
        threshold: float = 0.3,
        embedding_dir: Path | None = None,
        device: str | None = None,
    ) -> None:
        self.prompts = prompts or DEFAULT_PROMPTS
        self.threshold = threshold
        self.embedding_dir = embedding_dir
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        self._model = None
        self._preprocess = None
        self._text_features: torch.Tensor | None = None

    # ------------------------------------------------------------------
    # Lazy init
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return

        import cn_clip.clip as clip
        from cn_clip.clip import load_from_name

        self._model, self._preprocess = load_from_name(
            "ViT-H-14", device=self.device, download_root=None
        )
        self._model.eval()

        text_inputs = clip.tokenize(list(self.prompts.values())).to(self.device)
        with torch.no_grad():
            self._text_features = self._model.encode_text(text_inputs)
            self._text_features = self._text_features / self._text_features.norm(
                dim=-1, keepdim=True
            )

        if self.embedding_dir is not None:
            self.embedding_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "[clip_relevance] loaded Chinese-CLIP ViT-H/14 on %s, %d prompts",
            self.device,
            len(self.prompts),
        )

    # ------------------------------------------------------------------
    # Evaluate
    # ------------------------------------------------------------------

    def evaluate(self, image_path: Path, metadata: dict[str, Any]) -> FilterVerdict:
        self._ensure_loaded()
        assert self._model is not None
        assert self._preprocess is not None
        assert self._text_features is not None

        try:
            img = Image.open(image_path).convert("RGB")
            img_input = self._preprocess(img).unsqueeze(0).to(self.device)
        except Exception as exc:
            return FilterVerdict(
                passed=False,
                score=0.0,
                reason=f"cannot open image: {exc}",
                filter_name=self.name,
                details={"error": str(exc)},
            )

        with torch.no_grad():
            image_features = self._model.encode_image(img_input)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            similarities = (image_features @ self._text_features.T).squeeze(0)

        prompt_keys = list(self.prompts.keys())
        category_scores = {
            key: round(float(similarities[i]), 4) for i, key in enumerate(prompt_keys)
        }
        max_score = max(category_scores.values())
        passed = max_score >= self.threshold

        # Save embedding
        embedding_path = ""
        if self.embedding_dir is not None:
            npy_name = f"{image_path.stem}.npy"
            npy_path = self.embedding_dir / npy_name
            np.save(npy_path, image_features.cpu().numpy())
            embedding_path = str(npy_path)

        return FilterVerdict(
            passed=passed,
            score=max_score,
            reason="" if passed else f"max_score={max_score:.4f} below {self.threshold}",
            filter_name=self.name,
            details={
                "category_scores": category_scores,
                "clip_embedding_path": embedding_path,
            },
        )
