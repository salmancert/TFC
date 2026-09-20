"""Detect and normalise the columns of an arbitrary transaction table.

Bank exports and accounting ledgers never agree on column names, so the
reconciler works off *roles* (date / amount / description / reference)
that are inferred from the data itself rather than off hard-coded headers.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

DATE_NAME_HINTS = (
    "date", "posted", "posting", "booked", "value date", "transaction date",
    "trans date", "settled", "cleared", "datum",
)
AMOUNT_NAME_HINTS = (
    "amount", "value", "sum", "total", "net", "gross", "balance change",
    "betrag", "montant",
)
DEBIT_NAME_HINTS = ("debit", "withdrawal", "paid out", "payment out", "dr")
CREDIT_NAME_HINTS = ("credit", "deposit", "paid in", "payment in", "cr")
DESCRIPTION_NAME_HINTS = (
    "description", "narrative", "details", "memo", "particulars", "payee",
    "counterparty", "vendor", "customer", "name", "text", "remark", "note",
)
REFERENCE_NAME_HINTS = (
    "reference", "ref", "invoice", "document", "doc no", "cheque", "check",
    "transaction id", "txn", "voucher", "receipt", "order",
)

# Boilerplate that appears on nearly every bank line and therefore carries
# no discriminating power between candidate matches.
NOISE_TOKENS = frozenset({
    "ach", "pos", "eft", "sepa", "bacs", "chaps", "transfer", "transaction",
    "payment", "pmt", "debit", "credit", "card", "purchase", "withdrawal",
    "deposit", "wire", "online", "mobile", "banking", "ref", "reference",
    "inv", "invoice", "no", "nr", "num", "number", "the", "and", "for",
    "from", "to", "in", "out", "of", "id",
})

_AMOUNT_CLEAN_RE = re.compile(r"[^\d,.\-+()]")
_REF_TOKEN_RE = re.compile(r"[A-Za-z]{0,6}[-/]?\d[A-Za-z0-9\-/]*")
_WORD_RE = re.compile(r"[a-z0-9]+")
_NUMERIC_DATE_RE = re.compile(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\s*$")

LOGGER = logging.getLogger(__name__)


@dataclass
class ColumnRoles:
    """Which source column plays which role in a transaction table."""

    date: str | None = None
    amount: str | None = None
    debit: str | None = None
    credit: str | None = None
    description: list[str] = field(default_factory=list)
    reference: list[str] = field(default_factory=list)

    def describe(self) -> str:
        amount = self.amount or (
            f"{self.debit}/{self.credit}" if self.debit or self.credit else None
        )
        return (
            f"date={self.date!r} amount={amount!r} "
            f"description={self.description!r} reference={self.reference!r}"
        )


@dataclass
class NormalizedTable:
    """A transaction table reduced to the fields reconciliation needs."""

    frame: pd.DataFrame
    roles: ColumnRoles
    date: pd.Series           # datetime64[ns], NaT where unknown
    amount: pd.Series         # float64, NaN where unknown
    text: pd.Series           # cleaned free-text description
    tokens: list[set[str]]    # informative word tokens per row
    references: list[set[str]]  # normalised reference/document numbers
    name: str = "table"
    # True when the date column is written d/m/y-or-m/d/y and nothing in it
    # says which; the caller may be able to settle it from the other table.
    date_ambiguous: bool = False

    def __len__(self) -> int:
        return len(self.frame)


def _norm_name(name: object) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(name).lower()).strip()


def _name_matches(name: str, hints: Iterable[str]) -> bool:
    normalised = _norm_name(name)
    padded = f" {normalised} "
    return any(f" {hint} " in padded or normalised.startswith(hint) for hint in hints)


def parse_amount_series(series: pd.Series) -> pd.Series:
    """Parse currency-ish text into floats, honouring (1.00) and 100.00 CR."""
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        return series.astype("float64")

    def parse(value: object) -> float:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return np.nan
        if isinstance(value, (int, float, np.integer, np.floating)):
            return float(value)
        raw = str(value).strip()
        if not raw:
            return np.nan
        sign = -1.0 if raw.upper().endswith(("DR", "DB")) else 1.0
        if raw.upper().endswith(("CR", "DR", "DB")):
            raw = raw[:-2].strip()
        cleaned = _AMOUNT_CLEAN_RE.sub("", raw)
        if cleaned.startswith("(") and cleaned.endswith(")"):
            sign *= -1.0
            cleaned = cleaned[1:-1]
        cleaned = cleaned.replace("(", "").replace(")", "")
        if not cleaned or cleaned in {"-", "+", ".", ","}:
            return np.nan
        # 1.234,56 (European) vs 1,234.56 (Anglo): the last separator wins.
        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            decimals = cleaned.split(",")[-1]
            cleaned = (
                cleaned.replace(",", ".")
                if len(decimals) in (1, 2) and cleaned.count(",") == 1
                else cleaned.replace(",", "")
            )
        try:
            return sign * float(cleaned)
        except ValueError:
            return np.nan

    return series.map(parse).astype("float64")


def looks_like_yyyymmdd(series: pd.Series) -> bool:
    """True for the 20240102 integer date format some exports still use."""
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return False
    return bool(
        (values == values.round()).all()
        and (values >= 19000101).all()
        and (values <= 21001231).all()
    )


def has_numeric_dates(series: pd.Series) -> bool:
    """True when the column uses the ambiguous 03/09/2024 style at all."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return False
    return bool(
        series.dropna().astype(str).map(lambda v: bool(_NUMERIC_DATE_RE.match(v))).any()
    )


def infer_dayfirst(series: pd.Series) -> bool | None:
    """Decide whether 03/09/2024 means 3 September or 9 March.

    Returns True for day-first, False for month-first, or None when every
    value in the column is ambiguous and the convention cannot be read off
    the data.  Getting this wrong shifts dates by months, which quietly
    destroys every date-based match, so it is worth inferring per column.
    """
    day_first_evidence = month_first_evidence = 0
    for value in series.dropna().astype(str):
        match = _NUMERIC_DATE_RE.match(value)
        if not match:
            continue
        first, second = int(match.group(1)), int(match.group(2))
        if first > 12 >= second:
            day_first_evidence += 1
        elif second > 12 >= first:
            month_first_evidence += 1
    if day_first_evidence == month_first_evidence == 0:
        return None
    return day_first_evidence > month_first_evidence


def _to_datetime(series: pd.Series, dayfirst: bool) -> pd.Series:
    try:
        parsed = pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=dayfirst)
    except (ValueError, TypeError):
        parsed = pd.to_datetime(series, errors="coerce", dayfirst=dayfirst)
    if pd.api.types.is_datetime64_any_dtype(parsed) and getattr(parsed.dt, "tz", None):
        parsed = parsed.dt.tz_localize(None)
    return parsed


def parse_date_series(series: pd.Series, dayfirst: bool | None = None) -> pd.Series:
    """Parse a column into datetimes without raising on junk values.

    ``dayfirst`` overrides the automatic convention detection.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        parsed = pd.to_datetime(series, errors="coerce")
        if getattr(parsed.dt, "tz", None):
            parsed = parsed.dt.tz_localize(None)
        return parsed

    if pd.api.types.is_numeric_dtype(series):
        # Bare numbers are epoch nanoseconds to pandas, which turns an amount
        # column into 1970. Only the yyyymmdd convention is a real date here.
        if looks_like_yyyymmdd(series):
            digits = pd.to_numeric(series, errors="coerce")
            return pd.to_datetime(
                digits.map(lambda v: "" if pd.isna(v) else str(int(v))),
                errors="coerce",
                format="%Y%m%d",
            )
        return pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")

    if dayfirst is None:
        dayfirst = infer_dayfirst(series)
        if dayfirst is None:
            # Nothing in the column disambiguates d/m from m/d. Try both and
            # keep whichever parses more rows, defaulting to month-first.
            month_first = _to_datetime(series, dayfirst=False)
            day_first = _to_datetime(series, dayfirst=True)
            if day_first.notna().sum() > month_first.notna().sum():
                return day_first
            if month_first.notna().any():
                LOGGER.debug(
                    "Date column %r is ambiguous (all day/month values <= 12); "
                    "assuming month-first.",
                    series.name,
                )
            return month_first
    return _to_datetime(series, dayfirst=bool(dayfirst))


def _ratio_parsed(parsed: pd.Series, original: pd.Series) -> float:
    populated = original.notna() & (original.astype(str).str.strip() != "")
    if not populated.any():
        return 0.0
    return float(parsed[populated].notna().mean())


def _looks_like_identifier(series: pd.Series) -> bool:
    """True for short, mostly-unique, digit-bearing codes (invoice/cheque no.)."""
    values = series.dropna().astype(str).str.strip()
    values = values[values != ""]
    if len(values) < 2:
        return False
    if values.str.len().mean() > 24:
        return False
    has_digit = values.str.contains(r"\d").mean()
    few_words = (values.str.count(r"\s+") + 1).mean() <= 2.0
    unique_ratio = values.nunique() / len(values)
    return bool(has_digit >= 0.6 and few_words and unique_ratio >= 0.7)


def detect_roles(frame: pd.DataFrame) -> ColumnRoles:
    """Infer the role of every column from its name and its contents."""
    roles = ColumnRoles()
    columns = list(frame.columns)

    # --- date -------------------------------------------------------------
    date_scores: dict[str, float] = {}
    for column in columns:
        series = frame[column]
        if (
            pd.api.types.is_numeric_dtype(series)
            and not pd.api.types.is_datetime64_any_dtype(series)
            and not looks_like_yyyymmdd(series)
        ):
            continue
        ratio = _ratio_parsed(parse_date_series(series), series)
        if ratio >= 0.7:
            date_scores[column] = ratio + (0.5 if _name_matches(column, DATE_NAME_HINTS) else 0.0)
    if date_scores:
        roles.date = max(date_scores, key=lambda c: (date_scores[c], -columns.index(c)))

    # --- amount -----------------------------------------------------------
    numeric_candidates: dict[str, float] = {}
    for column in columns:
        if column == roles.date:
            continue
        parsed = parse_amount_series(frame[column])
        ratio = _ratio_parsed(parsed, frame[column])
        if ratio < 0.7:
            continue
        # Whole-number, positive, all-distinct columns are row ids rather than
        # money - but only judge that on enough values, and never on a column
        # that names itself as an amount or as one side of a debit/credit pair.
        finite = parsed.dropna()
        names_money = (
            _name_matches(column, AMOUNT_NAME_HINTS)
            or _name_matches(column, DEBIT_NAME_HINTS)
            or _name_matches(column, CREDIT_NAME_HINTS)
        )
        if not names_money and len(finite) >= 5:
            looks_like_id = (
                (finite == finite.round()).all()
                and (finite >= 0).all()
                and finite.nunique() == len(finite)
            )
            if looks_like_id:
                continue
        numeric_candidates[column] = ratio

    debit = next((c for c in numeric_candidates if _name_matches(c, DEBIT_NAME_HINTS)), None)
    credit = next((c for c in numeric_candidates if _name_matches(c, CREDIT_NAME_HINTS)), None)
    if debit and credit:
        roles.debit, roles.credit = debit, credit
    else:
        named = [c for c in numeric_candidates if _name_matches(c, AMOUNT_NAME_HINTS)]
        pool = named or list(numeric_candidates)
        if pool:
            # Prefer the column with the most decimal variety - that is money.
            def money_score(column: str) -> tuple[float, float]:
                values = parse_amount_series(frame[column]).dropna()
                fractional = float((values != values.round()).mean()) if len(values) else 0.0
                return (1.0 if column in named else 0.0, fractional)

            roles.amount = max(pool, key=money_score)

    # --- description / reference -----------------------------------------
    used = {roles.date, roles.amount, roles.debit, roles.credit} - {None}
    for column in columns:
        if column in used:
            continue
        series = frame[column]
        if pd.api.types.is_numeric_dtype(series) and column in numeric_candidates:
            continue
        if _name_matches(column, REFERENCE_NAME_HINTS) or _looks_like_identifier(series):
            roles.reference.append(column)
        elif _name_matches(column, DESCRIPTION_NAME_HINTS):
            roles.description.append(column)
        else:
            text = series.dropna().astype(str)
            if len(text) and text.str.len().mean() >= 3:
                roles.description.append(column)

    if not roles.description and roles.reference:
        roles.description = list(roles.reference)
    return roles


def _as_text(series: pd.Series) -> pd.Series:
    """Stringify a column, rendering every flavour of missing value as ""."""
    return series.map(lambda value: "" if pd.isna(value) else str(value)).astype(object)


def clean_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.lower().replace("_", " ")
    text = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text))
    return text.strip()


def informative_tokens(text: str) -> set[str]:
    """Words worth matching on: noise words and 1-character tokens dropped."""
    words = {word for word in _WORD_RE.findall(text) if len(word) > 1}
    meaningful = words - NOISE_TOKENS
    return meaningful or words


def extract_references(values: Sequence[object]) -> set[str]:
    """Pull invoice/cheque style codes out of text, normalised for comparison."""
    references: set[str] = set()
    for value in values:
        if value is None:
            continue
        for token in _REF_TOKEN_RE.findall(str(value)):
            normalised = re.sub(r"[^A-Za-z0-9]", "", token).upper().lstrip("0")
            if len(normalised) >= 3:
                references.add(normalised)
                # Index the bare number too: one system writes "INV-2001"
                # where the other writes just "2001".
                digits = re.sub(r"[^0-9]", "", normalised).lstrip("0")
                if len(digits) >= 3:
                    references.add(digits)
    return references


def normalize_table(
    frame: pd.DataFrame,
    name: str = "table",
    roles: ColumnRoles | None = None,
) -> NormalizedTable:
    """Reduce a raw sheet to the date / amount / text / reference fields."""
    frame = frame.reset_index(drop=True)
    roles = roles or detect_roles(frame)

    date_ambiguous = False
    if roles.date is not None:
        raw_dates = frame[roles.date]
        date_ambiguous = (
            has_numeric_dates(raw_dates) and infer_dayfirst(raw_dates) is None
        )
        date = parse_date_series(raw_dates)
    else:
        date = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")

    if roles.amount is not None:
        amount = parse_amount_series(frame[roles.amount])
    elif roles.debit is not None or roles.credit is not None:
        debit = (
            parse_amount_series(frame[roles.debit]).fillna(0.0)
            if roles.debit else pd.Series(0.0, index=frame.index)
        )
        credit = (
            parse_amount_series(frame[roles.credit]).fillna(0.0)
            if roles.credit else pd.Series(0.0, index=frame.index)
        )
        amount = credit.abs() - debit.abs()
    else:
        amount = pd.Series(np.nan, index=frame.index, dtype="float64")

    text_columns = roles.description or [
        c for c in frame.columns if c not in {roles.date, roles.amount, roles.debit, roles.credit}
    ]
    if text_columns:
        # Build the text column by column: a DataFrame-wide astype(str) leaves
        # NaN as a float in numeric columns and then fails to join.
        parts = [_as_text(frame[column]) for column in text_columns]
        joined = parts[0]
        for part in parts[1:]:
            joined = joined.str.cat(part, sep=" ")
    else:
        joined = pd.Series("", index=frame.index, dtype=object)
    text = joined.map(clean_text)

    reference_columns = roles.reference or []
    references = [
        extract_references(
            [frame.at[i, c] for c in reference_columns] + [joined.iat[i]]
        )
        for i in range(len(frame))
    ]

    return NormalizedTable(
        frame=frame,
        roles=roles,
        date=date,
        amount=amount,
        text=text,
        tokens=[informative_tokens(t) for t in text],
        references=references,
        name=name,
        date_ambiguous=date_ambiguous,
    )
