"""Turn a candidate (bank row, ledger row) pair into a feature vector.

Every feature is scaled to [0, 1] and "higher means more likely a match",
which keeps the learned weights interpretable and lets the heuristic
fallback be a plain weighted average of the same vector.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .schema import NormalizedTable

FEATURE_NAMES: tuple[str, ...] = (
    "amount_exact",
    "amount_close",
    "amount_relative",
    "sign_match",
    "date_proximity",
    "date_within_window",
    "date_known",
    "text_cosine",
    "token_jaccard",
    "reference_overlap",
)

# Fallback weights, used when there is not enough signal in a file to train.
# They encode the accountant's own priorities: the amount rules, the date
# narrows, and the narrative breaks ties.
HEURISTIC_WEIGHTS: dict[str, float] = {
    "amount_exact": 3.0,
    "amount_close": 1.5,
    "amount_relative": 0.5,
    "sign_match": 0.5,
    "date_proximity": 1.2,
    "date_within_window": 0.8,
    "date_known": 0.0,
    "text_cosine": 1.5,
    "token_jaccard": 1.0,
    "reference_overlap": 2.0,
}


@dataclass
class TextSimilarity:
    """Character n-gram TF-IDF cosine similarity between two tables."""

    left: "np.ndarray | object"
    right: "np.ndarray | object"

    @classmethod
    def fit(cls, left_text: list[str], right_text: list[str]) -> "TextSimilarity":
        corpus = [t for t in list(left_text) + list(right_text) if t]
        if not corpus:
            return cls(left=None, right=None)
        vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
        vectorizer.fit(corpus)
        return cls(
            left=vectorizer.transform(list(left_text)),
            right=vectorizer.transform(list(right_text)),
        )

    def similarity(self, left_rows: np.ndarray, right_rows: np.ndarray) -> np.ndarray:
        """Cosine similarity for aligned index arrays (TF-IDF rows are L2-normed)."""
        if self.left is None or self.right is None or len(left_rows) == 0:
            return np.zeros(len(left_rows), dtype=float)
        products = self.left[left_rows].multiply(self.right[right_rows])
        return np.clip(np.asarray(products.sum(axis=1)).ravel(), 0.0, 1.0)

    def top_k(self, k: int) -> np.ndarray:
        """Indices of the k most textually similar right-rows for each left-row."""
        if self.left is None or self.right is None or k <= 0:
            return np.empty((self.left.shape[0] if self.left is not None else 0, 0), dtype=int)
        scores = (self.left @ self.right.T).toarray()
        k = min(k, scores.shape[1])
        return np.argpartition(-scores, kth=k - 1, axis=1)[:, :k]


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = len(left | right)
    return len(left & right) / union if union else 0.0


def build_feature_matrix(
    left: NormalizedTable,
    right: NormalizedTable,
    pairs: np.ndarray,
    text_similarity: TextSimilarity,
    amount_tolerance: float = 0.01,
    date_window_days: float = 5.0,
    date_tau: float = 3.0,
) -> np.ndarray:
    """Build an (n_pairs, n_features) matrix for the given candidate pairs."""
    if len(pairs) == 0:
        return np.empty((0, len(FEATURE_NAMES)), dtype=float)

    left_rows = pairs[:, 0]
    right_rows = pairs[:, 1]

    left_amount = left.amount.to_numpy(dtype=float)[left_rows]
    right_amount = right.amount.to_numpy(dtype=float)[right_rows]
    amount_known = np.isfinite(left_amount) & np.isfinite(right_amount)
    delta = np.where(amount_known, np.abs(left_amount - right_amount), np.inf)
    magnitude = np.maximum(np.abs(left_amount), np.abs(right_amount))
    magnitude = np.where(np.isfinite(magnitude) & (magnitude > 1.0), magnitude, 1.0)

    amount_exact = (delta <= amount_tolerance).astype(float)
    # Decays over a scale proportional to the transaction size, so a 5c drift
    # on a $4 coffee is penalised far harder than on a $50,000 wire.
    amount_close = np.where(amount_known, np.exp(-delta / (0.02 * magnitude + 0.05)), 0.0)
    amount_relative = np.where(amount_known, np.clip(1.0 - delta / magnitude, 0.0, 1.0), 0.0)
    sign_match = np.where(
        amount_known, (np.sign(left_amount) == np.sign(right_amount)).astype(float), 0.0
    )

    left_date = left.date.to_numpy(dtype="datetime64[ns]")[left_rows]
    right_date = right.date.to_numpy(dtype="datetime64[ns]")[right_rows]
    date_known = (~np.isnat(left_date) & ~np.isnat(right_date)).astype(float)
    day_gap = np.where(
        date_known.astype(bool),
        np.abs((left_date - right_date) / np.timedelta64(1, "D")).astype(float),
        np.inf,
    )
    date_proximity = np.where(date_known.astype(bool), np.exp(-day_gap / max(date_tau, 1e-6)), 0.0)
    date_within_window = (day_gap <= date_window_days).astype(float)

    text_cosine = text_similarity.similarity(left_rows, right_rows)
    token_jaccard = np.array(
        [_jaccard(left.tokens[i], right.tokens[j]) for i, j in pairs], dtype=float
    )
    reference_overlap = np.array(
        [1.0 if (left.references[i] & right.references[j]) else 0.0 for i, j in pairs],
        dtype=float,
    )

    return np.column_stack(
        [
            amount_exact,
            amount_close,
            amount_relative,
            sign_match,
            date_proximity,
            date_within_window,
            date_known,
            text_cosine,
            token_jaccard,
            reference_overlap,
        ]
    )


def heuristic_scores(features: np.ndarray) -> np.ndarray:
    """Weighted-average score in [0, 1], used when no model can be trained."""
    if len(features) == 0:
        return np.empty(0, dtype=float)
    weights = np.array([HEURISTIC_WEIGHTS[name] for name in FEATURE_NAMES], dtype=float)
    return np.clip(features @ weights / weights.sum(), 0.0, 1.0)
