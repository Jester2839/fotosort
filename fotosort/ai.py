"""AI hodnocení: CLIP ViT-L/14 embedding → LAION aesthetic skóre + zero-shot kategorie.

Importuje torch, takže se načítá jen v hlavním procesu a jen když je AI zapnuté.
"""

from __future__ import annotations

import os
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

# Ztišit nepodstatná varování Hugging Face (symlinky na Windows, nepřihlášené stahování).
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")
warnings.filterwarnings("ignore", module="huggingface_hub")

import torch  # noqa: E402
from torch import nn  # noqa: E402

from . import config as C
from .analyze import load_preview
from .cull import Score
from .media import Shot

# Váhy OpenAI jsou trénované s aktivací QuickGELU; bez "-quickgelu" by embeddingy byly zkreslené.
MODEL_NAME = "ViT-L-14-quickgelu"
CLIP_EDGE = 448  # náhled pro CLIP; model si ho stejně zmenší na 224
BATCH = 16


class AestheticMLP(nn.Module):
    """Architektura z christophschuhmann/improved-aesthetic-predictor (vstup 768 = CLIP L/14)."""

    def __init__(self) -> None:
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(768, 1024), nn.Dropout(0.2),
            nn.Linear(1024, 128), nn.Dropout(0.2),
            nn.Linear(128, 64), nn.Dropout(0.1),
            nn.Linear(64, 16),
            nn.Linear(16, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.layers(x)


class Scorer:
    def __init__(self, aesthetic_weights: Path | None, categories: dict[str, list[str]] | None,
                 pretrained: str | None = "openai"):
        import open_clip

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            MODEL_NAME, pretrained=pretrained, device=self.device)
        self.model.eval()

        self.mlp = AestheticMLP().to(self.device).eval()
        if aesthetic_weights:
            state = torch.load(aesthetic_weights, map_location=self.device, weights_only=True)
            self.mlp.load_state_dict(state)

        self.cat_names: list[str] = []
        self.cat_features = None
        if categories:
            tokenizer = open_clip.get_tokenizer(MODEL_NAME)
            feats = []
            with torch.no_grad():
                for name, prompts in categories.items():
                    t = self.model.encode_text(tokenizer(prompts).to(self.device)).float()
                    t = t / t.norm(dim=-1, keepdim=True)
                    mean = t.mean(dim=0)
                    feats.append(mean / mean.norm())
                    self.cat_names.append(name)
            self.cat_features = torch.stack(feats)

    @torch.no_grad()
    def score_images(self, images: list) -> list[Score]:
        batch = torch.stack([self.preprocess(img) for img in images]).to(self.device)
        with torch.autocast(self.device, enabled=self.device == "cuda"):
            emb = self.model.encode_image(batch)
        emb = emb.float()
        emb = emb / emb.norm(dim=-1, keepdim=True)
        aesthetic = self.mlp(emb).squeeze(-1).tolist()

        results = [Score(a) for a in aesthetic]
        if self.cat_features is not None:
            probs = (100.0 * emb @ self.cat_features.T).softmax(dim=-1)
            best_p, best_i = probs.max(dim=-1)
            for r, p, i in zip(results, best_p.tolist(), best_i.tolist()):
                r.category = self.cat_names[i] if p >= C.CATEGORY_MIN_PROB else "ostatni"
                r.category_prob = p
        return results


def score_all(shots: list[Shot], scorer: Scorer,
              progress: Callable[[int, int, str], None] | None = None) -> list[Score]:
    """Načítá náhledy ve vláknech a posílá je do modelu po dávkách."""
    def load(shot: Shot):
        try:
            return load_preview(shot.files, CLIP_EDGE)
        except Exception:
            return None

    results: list[Score] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for start in range(0, len(shots), BATCH):
            chunk = shots[start:start + BATCH]
            images = list(pool.map(load, chunk))
            ok = [(i, img) for i, img in enumerate(images) if img is not None]
            scores = scorer.score_images([img for _, img in ok]) if ok else []
            chunk_results = [Score(None) for _ in chunk]
            for (i, _), sc in zip(ok, scores):
                chunk_results[i] = sc
            results.extend(chunk_results)
            if progress:
                progress(min(start + BATCH, len(shots)), len(shots), chunk[-1].stem)
    return results
