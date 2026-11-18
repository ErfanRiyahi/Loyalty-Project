"""One lossless identifier policy for scoring, temporal features and churn history."""
from decimal import Decimal, InvalidOperation
import pandas as pd

VERSION = "msisdn-v2"
POLICY_DESCRIPTION = "شماره‌های موبایل ایران با قالب 98 و بدون صفر ابتدایی یکسان می‌شوند؛ شناسه‌های غیرتلفنی و ناشناس‌سازی‌شده حفظ می‌شوند."
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _integer_text(value):
    # Decimal avoids rounding long identifiers through binary floating point.
    try:
        number = Decimal(value)
        return format(number, "f").split(".")[0] if number.is_finite() and 9 <= number.adjusted() <= 13 and number == number.to_integral_value() else value
    except (InvalidOperation, ValueError):
        return value


def normalize_identifiers(values):
    """Canonicalize recognized Iranian mobile numbers; preserve opaque IDs as text.

    Unknown formats keep their original text (apart from surrounding whitespace).
    Numeric .0/scientific spelling is interpreted only when it resolves to a mobile.
    """
    text = values.astype("string").str.strip()
    result = text.mask(text.eq(""))
    candidate = text.str.translate(_DIGITS)
    numeric_spelling = candidate.str.fullmatch(r"\+?\d+\.0+|\+?\d+(?:\.\d+)?[eE][+\-]?\d+", na=False)
    if numeric_spelling.any():
        spellings = candidate.loc[numeric_spelling]
        lookup = {value: _integer_text(value) for value in spellings.unique()}
        candidate.loc[numeric_spelling] = spellings.map(lookup)
    candidate = candidate.str.replace(r"[\s()\-]", "", regex=True)
    national = candidate.str.fullmatch(r"9\d{9}", na=False)
    local = candidate.str.fullmatch(r"09\d{9}", na=False)
    canonical = candidate.str.fullmatch(r"989\d{9}", na=False)
    plus = candidate.str.fullmatch(r"\+989\d{9}", na=False)
    international = candidate.str.fullmatch(r"00989\d{9}", na=False)
    result.loc[national] = "98" + candidate.loc[national]
    result.loc[local] = "98" + candidate.loc[local].str[1:]
    result.loc[canonical] = candidate.loc[canonical]
    result.loc[plus] = candidate.loc[plus].str[1:]
    result.loc[international] = candidate.loc[international].str[2:]
    return result
