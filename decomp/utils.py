"""Small, well-tested helpers used everywhere."""
import re
from decimal import Decimal, ROUND_HALF_UP

from . import config

# Basis labels attached to every important fact
VERIFIED = "VERIFIED"      # read directly from a workbook cell
INFERRED = "INFERRED"      # derived by Python (rollup, layout rule, pattern match)
UNVERIFIED = "UNVERIFIED"  # missing / could not be confirmed


class WorkbookFormatError(Exception):
    """Raised when the workbook cannot be processed safely."""


# ---------------------------------------------------------------- text ----
def clean_text(value):
    """Return a stripped string, or '' for None."""
    if value is None:
        return ""
    return str(value).strip()


def norm_label(text):
    """Normalise a label for matching: lower case, '_' -> ' ', single spaces."""
    t = clean_text(text).lower().replace("_", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return config.LABEL_ALIASES.get(t, t)


def is_total_label(label):
    return bool(re.search(config.TOTAL_SUFFIX_REGEX, clean_text(label), re.I))


def total_base(label):
    """'Investment Grade Total' -> 'investment grade' (normalised)."""
    return norm_label(re.sub(config.TOTAL_SUFFIX_REGEX, "", clean_text(label), flags=re.I))


def is_skip_label(label):
    n = norm_label(label)
    return any(re.search(rx, n) for rx in config.SKIP_LABEL_REGEXES)


# ------------------------------------------------------------- numbers ----
def to_number(value):
    """Convert a cell value to float.

    Returns (number_or_None, problem_or_None). Handles Excel accounting text
    such as '(1,234)', '-', '1,234', ' 12 '. A dash means zero.
    """
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, "boolean in numeric column"
    if isinstance(value, (int, float)):
        return float(value), None
    text = clean_text(value)
    if text == "":
        return None, None
    if text in {"-", "\u2013", "\u2014"}:
        return 0.0, None
    neg = text.startswith("(") and text.endswith(")")
    t = text.strip("()").replace(",", "").replace("C$", "").replace("$", "").strip()
    try:
        num = float(t)
        return (-num if neg else num), None
    except ValueError:
        return None, "text '%s' in numeric column" % text[:30]


def round_half_up(x, places=0):
    q = Decimal(1).scaleb(-places)
    return float(Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP))


def to_k(dollars):
    """Dollars -> thousands rounded to whole thousands (house style)."""
    if dollars is None:
        return None
    return round_half_up(dollars / 1000.0, 0)


def fmt_k(dollars, signed=False):
    """Accounting format in thousands.

    1234567 -> 'C$ 1,235.0'   -1234567 -> '(C$ 1,235.0)'   None -> 'n/a'
    signed=True puts '+' on positives (used for variances).
    Tiny negatives that round to zero print as 'C$ 0.0' (no brackets).
    """
    if dollars is None:
        return "n/a"
    k = to_k(dollars)
    if k == 0:
        return "%s 0%s" % (config.CURRENCY, config.DISPLAY_DECIMALS_SUFFIX)
    body = "%s %s%s" % (config.CURRENCY, "{:,.0f}".format(abs(k)),
                        config.DISPLAY_DECIMALS_SUFFIX)
    if k < 0:
        return "(%s)" % body
    return ("+" + body) if signed else body


def fmt_pct(p):
    return "n/a" if p is None else "%.1f%%" % p


def safe_pct(part, whole):
    """Signed percentage of whole; None if whole is (near) zero or missing."""
    if part is None or whole is None or abs(whole) < config.ZERO_THRESHOLD:
        return None
    return round(part / whole * 100.0, 2)


# ------------------------------------------------------- reconciliation ----
def reconcile(name, reference, compared, ref_label="reference", cmp_label="compared"):
    """Compare two dollar amounts with absolute + percentage tolerance."""
    if reference is None or compared is None:
        return {"check": name, "status": "NOT_APPLICABLE",
                "reason": "missing value", ref_label: reference, cmp_label: compared}
    diff = compared - reference
    tol = max(config.RECON_ABS_TOL, config.RECON_PCT_TOL * abs(reference))
    if abs(diff) <= tol:
        status = "PASS"
    elif abs(diff) <= tol * config.RECON_WARN_MULTIPLIER:
        status = "WARN"
    else:
        status = "FAIL"
    return {
        "check": name, "status": status,
        ref_label: round(reference, 2), cmp_label: round(compared, 2),
        "difference": round(diff, 2),
        "difference_pct": safe_pct(diff, reference),
        "tolerance": round(tol, 2),
    }
