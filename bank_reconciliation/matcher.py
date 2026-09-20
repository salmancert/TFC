"""Candidate generation, scoring and assignment for bank reconciliation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from .features import FEATURE_NAMES, TextSimilarity, build_feature_matrix
from .model import PairScorer, TrainingReport, train_self_supervised
from .schema import NormalizedTable, normalize_table, parse_date_series

LOGGER = logging.getLogger(__name__)


@dataclass
class ReconciliationConfig:
    """Tunable policy for what counts as a match."""

    amount_tolerance: float = 0.01
    amount_band: float = 0.02          # relative band used to widen candidates
    date_window_days: int = 5
    date_tau: float = 3.0
    match_threshold: float = 0.60      # at or above -> accepted automatically
    review_threshold: float = 0.35     # in between -> flagged for a human
    max_candidates_per_row: int = 25
    text_neighbours: int = 10
    sign_convention: str = "auto"      # auto | same | flip
    group_matching: bool = True
    max_group_size: int = 3
    max_assignment_cells: int = 4_000_000
    prior_weight: float = 0.25
    random_state: int = 0

    def validate(self) -> None:
        if self.review_threshold > self.match_threshold:
            raise ValueError("review_threshold must not exceed match_threshold")
        if self.sign_convention not in {"auto", "same", "flip"}:
            raise ValueError("sign_convention must be one of: auto, same, flip")
        if self.max_group_size < 2:
            raise ValueError("max_group_size must be at least 2")


@dataclass
class MatchRecord:
    """One reconciliation decision, covering one or more rows on each side."""

    left_rows: tuple[int, ...]
    right_rows: tuple[int, ...]
    score: float
    status: str      # matched | review
    kind: str        # one_to_one | grouped
    evidence: dict[str, float] = field(default_factory=dict)


@dataclass
class ReconciliationResult:
    left: NormalizedTable
    right: NormalizedTable
    records: list[MatchRecord]
    unmatched_left: list[int]
    unmatched_right: list[int]
    scorer: PairScorer
    sign_flipped: bool
    config: ReconciliationConfig

    @property
    def training(self) -> TrainingReport:
        """How the scorer used for this run was obtained."""
        return self.scorer.report

    @property
    def summary(self) -> dict[str, object]:
        matched = [r for r in self.records if r.status == "matched"]
        review = [r for r in self.records if r.status == "review"]
        grouped = [r for r in self.records if r.kind == "grouped"]
        left_covered = sum(len(r.left_rows) for r in self.records)
        right_covered = sum(len(r.right_rows) for r in self.records)
        return {
            f"Rows in {self.left.name}": len(self.left),
            f"Rows in {self.right.name}": len(self.right),
            "Auto-matched pairs": len(matched),
            "Flagged for review": len(review),
            "Grouped (one-to-many) matches": len(grouped),
            f"Unmatched in {self.left.name}": len(self.unmatched_left),
            f"Unmatched in {self.right.name}": len(self.unmatched_right),
            f"Coverage of {self.left.name}": _percent(left_covered, len(self.left)),
            f"Coverage of {self.right.name}": _percent(right_covered, len(self.right)),
            "Scoring model": self.training.summary(),
            "Sign convention": "flipped" if self.sign_flipped else "as supplied",
            "Auto-match threshold": self.config.match_threshold,
            "Review threshold": self.config.review_threshold,
        }


def _percent(part: int, whole: int) -> str:
    return f"{(100.0 * part / whole):.1f}%" if whole else "n/a"


def detect_sign_flip(left: NormalizedTable, right: NormalizedTable) -> bool:
    """Bank credits are ledger debits in many exports; work out which way round.

    Counts how many left-hand amounts find *any* partner of the same value on
    the right, with and without negating the right-hand side, and keeps
    whichever convention explains more rows.
    """
    left_amounts = left.amount.dropna().to_numpy()
    right_amounts = right.amount.dropna().to_numpy()
    if len(left_amounts) == 0 or len(right_amounts) == 0:
        return False

    def rows_explained(values: np.ndarray) -> int:
        available = {round(float(value), 2) for value in values}
        return sum(1 for value in left_amounts if round(float(value), 2) in available)

    same = rows_explained(right_amounts)
    flipped = rows_explained(-right_amounts)
    if flipped > same:
        LOGGER.info("Sign convention differs between the two tables; flipping %s", right.name)
        return True
    return False


def _align_ambiguous_dates(left: NormalizedTable, right: NormalizedTable) -> None:
    """Settle an undecidable d/m vs m/d column against the other table.

    A column of dates whose day and month are all <= 12 carries no internal
    clue about its convention, but the *other* table usually does: real
    counterparts sit days apart, not months.  Re-read the ambiguous column
    both ways and keep whichever lands inside the other table's date range.
    """
    for ambiguous, reference in ((left, right), (right, left)):
        if not ambiguous.date_ambiguous or reference.date_ambiguous:
            continue
        if ambiguous.roles.date is None:
            continue
        anchor = reference.date.dropna()
        if anchor.empty:
            continue

        raw = ambiguous.frame[ambiguous.roles.date]
        window = pd.Timedelta(days=45)
        low, high = anchor.min() - window, anchor.max() + window

        best_parse, best_hits = None, -1
        for dayfirst in (False, True):
            parsed = parse_date_series(raw, dayfirst=dayfirst)
            valid = parsed.dropna()
            hits = int(((valid >= low) & (valid <= high)).sum())
            if hits > best_hits:
                best_parse, best_hits = parsed, hits
        if best_parse is not None:
            ambiguous.date = best_parse
            ambiguous.date_ambiguous = False


def _candidate_pairs(
    left: NormalizedTable,
    right: NormalizedTable,
    text_similarity: TextSimilarity,
    config: ReconciliationConfig,
) -> np.ndarray:
    """Cheaply shortlist the pairs worth scoring, instead of all n*m of them."""
    n_left, n_right = len(left), len(right)
    if n_left == 0 or n_right == 0:
        return np.empty((0, 2), dtype=int)

    right_amounts = right.amount.to_numpy(dtype=float)
    finite_right = np.flatnonzero(np.isfinite(right_amounts))
    sorted_right = finite_right[np.argsort(right_amounts[finite_right], kind="stable")]
    sorted_values = right_amounts[sorted_right]

    left_amounts = left.amount.to_numpy(dtype=float)
    left_dates = left.date.to_numpy(dtype="datetime64[ns]")
    right_dates = right.date.to_numpy(dtype="datetime64[ns]")

    text_neighbours = (
        text_similarity.top_k(config.text_neighbours)
        if config.text_neighbours > 0
        else np.empty((n_left, 0), dtype=int)
    )

    pairs: list[tuple[int, int]] = []
    for row in range(n_left):
        candidates: set[int] = set()

        amount = left_amounts[row]
        if np.isfinite(amount) and len(sorted_values):
            band = max(config.amount_tolerance, config.amount_band * abs(amount))
            low = np.searchsorted(sorted_values, amount - band, side="left")
            high = np.searchsorted(sorted_values, amount + band, side="right")
            candidates.update(int(i) for i in sorted_right[low:high])

        if text_neighbours.shape[1]:
            candidates.update(int(i) for i in text_neighbours[row])

        # Same-day rows are always worth a look even when the amount drifted
        # (bank fees netted off, FX rounding, partial settlements).
        left_date = left_dates[row]
        if not np.isnat(left_date):
            gap = np.abs((right_dates - left_date) / np.timedelta64(1, "D"))
            same_day = np.flatnonzero(np.isfinite(gap) & (gap <= 1.0))
            if len(same_day) <= config.max_candidates_per_row:
                candidates.update(int(i) for i in same_day)

        pairs.extend((row, column) for column in candidates)

    if not pairs:
        return np.empty((0, 2), dtype=int)
    return np.asarray(sorted(set(pairs)), dtype=int)


def _trim_candidates(
    pairs: np.ndarray, features: np.ndarray, scores: np.ndarray, limit: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Keep only the best ``limit`` candidates per left row."""
    if len(pairs) == 0 or limit <= 0:
        return pairs, features, scores
    keep: list[int] = []
    order = np.lexsort((-scores, pairs[:, 0]))
    current_row, taken = -1, 0
    for index in order:
        row = int(pairs[index, 0])
        if row != current_row:
            current_row, taken = row, 0
        if taken < limit:
            keep.append(int(index))
            taken += 1
    keep_array = np.asarray(sorted(keep), dtype=int)
    return pairs[keep_array], features[keep_array], scores[keep_array]


def _assign(
    pairs: np.ndarray, scores: np.ndarray, n_left: int, n_right: int, config: ReconciliationConfig
) -> list[tuple[int, int, float]]:
    """Pick at most one partner per row, maximising the total score."""
    if len(pairs) == 0:
        return []

    if n_left * n_right <= config.max_assignment_cells:
        cost = np.ones((n_left, n_right), dtype=float)
        cost[pairs[:, 0], pairs[:, 1]] = 1.0 - scores
        rows, columns = linear_sum_assignment(cost)
        score_lookup = {(int(i), int(j)): float(s) for (i, j), s in zip(pairs, scores)}
        return [
            (int(i), int(j), score_lookup[(int(i), int(j))])
            for i, j in zip(rows, columns)
            if (int(i), int(j)) in score_lookup
        ]

    LOGGER.warning(
        "%d x %d is too large for optimal assignment; falling back to greedy matching",
        n_left,
        n_right,
    )
    used_left: set[int] = set()
    used_right: set[int] = set()
    chosen: list[tuple[int, int, float]] = []
    for index in np.argsort(-scores):
        left_row, right_row = int(pairs[index, 0]), int(pairs[index, 1])
        if left_row in used_left or right_row in used_right:
            continue
        used_left.add(left_row)
        used_right.add(right_row)
        chosen.append((left_row, right_row, float(scores[index])))
    return chosen


def _find_group_matches(
    left: NormalizedTable,
    right: NormalizedTable,
    open_left: list[int],
    open_right: list[int],
    config: ReconciliationConfig,
) -> list[MatchRecord]:
    """Explain a leftover bank line as the sum of several ledger lines.

    Batch deposits and lump-sum supplier payments are the everyday case that
    pure one-to-one matching can never close.
    """
    if not open_left or len(open_right) < 2:
        return []

    left_amounts = left.amount.to_numpy(dtype=float)
    right_amounts = right.amount.to_numpy(dtype=float)
    left_dates = left.date.to_numpy(dtype="datetime64[ns]")
    right_dates = right.date.to_numpy(dtype="datetime64[ns]")

    records: list[MatchRecord] = []
    claimed_right: set[int] = set()

    for left_row in open_left:
        target = left_amounts[left_row]
        if not np.isfinite(target) or abs(target) < config.amount_tolerance:
            continue

        pool = [
            r for r in open_right
            if r not in claimed_right
            and np.isfinite(right_amounts[r])
            and np.sign(right_amounts[r]) == np.sign(target)
            and abs(right_amounts[r]) <= abs(target) + config.amount_tolerance
        ]
        left_date = left_dates[left_row]
        if not np.isnat(left_date):
            pool = [
                r for r in pool
                if np.isnat(right_dates[r])
                or abs((right_dates[r] - left_date) / np.timedelta64(1, "D"))
                <= config.date_window_days
            ]
        # Keep the search bounded: C(14, 3) is 364 combinations, C(60, 3) is 34k.
        if len(pool) < 2 or len(pool) > 14:
            continue

        best: tuple[int, ...] | None = None
        for size in range(2, min(config.max_group_size, len(pool)) + 1):
            for combination in combinations(pool, size):
                total = float(np.sum(right_amounts[list(combination)]))
                if abs(total - target) <= config.amount_tolerance:
                    best = combination
                    break
            if best is not None:
                break
        if best is None:
            continue

        if np.isnat(left_date):
            date_proximity = 0.0
        else:
            gaps = [
                abs(float((right_dates[r] - left_date) / np.timedelta64(1, "D")))
                for r in best
                if not np.isnat(right_dates[r])
            ]
            date_proximity = float(np.exp(-np.mean(gaps) / config.date_tau)) if gaps else 0.0

        overlap = max(
            (
                len(left.tokens[left_row] & right.tokens[r])
                / max(len(left.tokens[left_row] | right.tokens[r]), 1)
                for r in best
            ),
            default=0.0,
        )
        score = min(0.99, 0.60 + 0.30 * date_proximity + 0.10 * overlap)
        claimed_right.update(best)
        records.append(
            MatchRecord(
                left_rows=(left_row,),
                right_rows=tuple(sorted(best)),
                score=score,
                status="matched" if score >= config.match_threshold else "review",
                kind="grouped",
                evidence={"date_proximity": date_proximity, "token_jaccard": overlap},
            )
        )
    return records


def reconcile(
    left_frame: pd.DataFrame,
    right_frame: pd.DataFrame,
    left_name: str = "left",
    right_name: str = "right",
    config: ReconciliationConfig | None = None,
    scorer: PairScorer | None = None,
) -> ReconciliationResult:
    """Reconcile two transaction tables and return every decision made."""
    config = config or ReconciliationConfig()
    config.validate()

    left = normalize_table(left_frame, left_name)
    right = normalize_table(right_frame, right_name)

    if len(left) == 0 or len(right) == 0:
        return ReconciliationResult(
            left=left,
            right=right,
            records=[],
            unmatched_left=list(range(len(left))),
            unmatched_right=list(range(len(right))),
            scorer=scorer or PairScorer(report=TrainingReport(reason="nothing to match")),
            sign_flipped=False,
            config=config,
        )

    _align_ambiguous_dates(left, right)

    sign_flipped = (
        detect_sign_flip(left, right)
        if config.sign_convention == "auto"
        else config.sign_convention == "flip"
    )
    if sign_flipped:
        right.amount = -right.amount

    text_similarity = TextSimilarity.fit(left.text.tolist(), right.text.tolist())
    pairs = _candidate_pairs(left, right, text_similarity, config)
    features = build_feature_matrix(
        left,
        right,
        pairs,
        text_similarity,
        amount_tolerance=config.amount_tolerance,
        date_window_days=config.date_window_days,
        date_tau=config.date_tau,
    )

    if scorer is None:
        scorer = train_self_supervised(
            features, pairs, prior_weight=config.prior_weight, random_state=config.random_state
        )
    scores = scorer.score(features)
    pairs, features, scores = _trim_candidates(
        pairs, features, scores, config.max_candidates_per_row
    )

    assignment = _assign(pairs, scores, len(left), len(right), config)
    feature_lookup = {(int(i), int(j)): row for (i, j), row in zip(pairs, features)}

    records: list[MatchRecord] = []
    for left_row, right_row, score in assignment:
        if score < config.review_threshold:
            continue
        evidence = feature_lookup.get((left_row, right_row))
        records.append(
            MatchRecord(
                left_rows=(left_row,),
                right_rows=(right_row,),
                score=float(score),
                status="matched" if score >= config.match_threshold else "review",
                kind="one_to_one",
                evidence=(
                    {name: float(value) for name, value in zip(FEATURE_NAMES, evidence)}
                    if evidence is not None
                    else {}
                ),
            )
        )

    matched_left = {row for record in records for row in record.left_rows}
    matched_right = {row for record in records for row in record.right_rows}
    open_left = [i for i in range(len(left)) if i not in matched_left]
    open_right = [i for i in range(len(right)) if i not in matched_right]

    if config.group_matching:
        grouped = _find_group_matches(left, right, open_left, open_right, config)
        records.extend(grouped)
        matched_left.update(row for record in grouped for row in record.left_rows)
        matched_right.update(row for record in grouped for row in record.right_rows)
        open_left = [i for i in range(len(left)) if i not in matched_left]
        open_right = [i for i in range(len(right)) if i not in matched_right]

    records.sort(key=lambda record: (-record.score, record.left_rows))
    return ReconciliationResult(
        left=left,
        right=right,
        records=records,
        unmatched_left=open_left,
        unmatched_right=open_right,
        scorer=scorer,
        sign_flipped=sign_flipped,
        config=config,
    )
