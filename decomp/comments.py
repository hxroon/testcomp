"""
Step 3 - analyst comments.

* The original text is kept byte-for-byte in `raw` (never edited).
* `display` only turns line breaks (incl. Excel's '_x000D_' artefact) into real
  line breaks so the HTML shows them; no words are changed.
* Amounts like '+0.4mm', '(0.3)mm', '-5K', '+1824K' are converted to dollars.
* Named drivers (clients, issuers, books, desks) are pattern-matched.

Everything extracted here is INFERRED: it is what the analyst wrote, read by a
pattern, and is not reconciled to the decomposition numbers.
"""
import re

from . import config
from .utils import INFERRED, fmt_k

_LINEBREAK_ARTEFACTS = re.compile(r"_x000[dDaA]_|\r\n|\r|\x0b|\u2028|\u2029")

_UNIT = {"mm": 1e6, "mn": 1e6, "m": 1e6, "bn": 1e9, "b": 1e9, "k": 1e3}
_AMOUNT = re.compile(
    # start of an amount: not glued to a word like 'cs01'/'pv01', but allow
    # 'Corporate(0.3)mm' and 'CAPITAL+86K' (letter directly before '(' or sign)
    r"(?:(?<=[A-Za-z])(?=[(+\-\u2212\u2013])|(?<![A-Za-z0-9.]))"
    r"(?P<sign>[+\-\u2212\u2013])?\s*"
    r"(?P<open>\()?\s*"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<close>\))?\s*"
    r"(?P<unit>mm|MM|Mm|mn|MN|bn|BN|[kK]|[mM])(?![A-Za-z])"
)
_CLAUSE_SPLIT = re.compile(r"[\n;]|,\s|(?<=[a-z])\.\s|:\s?(?=[A-Z+\-(])")


def display_text(raw):
    """Line-break normalisation only - safe to show as 'verbatim'."""
    if raw is None:
        return ""
    t = _LINEBREAK_ARTEFACTS.sub("\n", str(raw))
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def is_empty_comment(raw):
    t = display_text(raw).lower()
    return t in ("", "(no comment)", "no comment", "n/a", "-")


def extract_amounts(text):
    """All amounts with units, converted to dollars, with the clause around them."""
    text = display_text(text)
    out = []
    for m in _AMOUNT.finditer(text):
        value = float(m.group("num").replace(",", "")) * _UNIT[m.group("unit").lower()]
        negative = (m.group("sign") in ("-", "\u2212", "\u2013")) or (m.group("open") and m.group("close"))
        if bool(m.group("open")) != bool(m.group("close")):
            continue          # unbalanced bracket, e.g. '401(K)' or 'x)0.3mm'
        if negative:
            value = -value
        start = max(0, text.rfind("\n", 0, m.start()) + 1)
        end_nl = text.find("\n", m.end())
        line = text[start: end_nl if end_nl != -1 else len(text)]
        context = _clause(line, m.start() - start, m.end() - start)
        out.append({
            "as_written": m.group(0).strip(),
            "dollars": value,
            "display": fmt_k(value),
            "context": context,
            "basis": INFERRED,
        })
    return out


def _clause(line, s, e):
    """Text around an amount: back to the previous ',' or ';' (max 45 chars),
    forward to the next ',' ';' or ': ' (max 45 chars)."""
    cuts = [line.rfind(ch, 0, s) for ch in (",", ";")]
    left = max(cuts)
    left = left + 1 if left != -1 else 0
    if s - left > 45:
        left = line.rfind(" ", 0, s - 40) + 1
    rights = [i for i in (line.find(",", e), line.find(";", e), line.find(": ", e)) if i != -1]
    right = min(rights) if rights else len(line)
    if right - e > 45:
        sp = line.find(" ", e + 40)
        right = sp if sp != -1 else len(line)
    return line[left:right].strip(" ,;:")


_ENTITY = None


def _entity_regex():
    global _ENTITY
    if _ENTITY is None:
        suffix = "|".join(config.ENTITY_SUFFIXES)
        _ENTITY = re.compile(
            r"(?<![A-Za-z0-9.])((?:[A-Z][A-Z0-9&'.\-]*\s+){1,6}(?:%s))\b\.?" % suffix)
    return _ENTITY


_CLIENT = re.compile(r"Clients?\s*:\s*([A-Z0-9][A-Z0-9 &'.\-]*[A-Z0-9])", re.I)
_BOOK_CODE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]+_[A-Za-z0-9_]+|[A-Z]{2,}-[A-Z]{2,})(?![A-Za-z0-9])")


def extract_named(text):
    """Return list of {'name', 'type', 'dollars', 'display', 'context'}."""
    text = display_text(text)
    found = {}

    def add(name, kind):
        name = re.sub(r"\s+", " ", name).strip(" .,:;\"'")
        if len(name) < 3 or name.upper() in ("MTM", "NTA", "MM", "FX"):
            return
        key = name.lower()
        if key not in found:
            found[key] = {"name": name, "type": kind, "basis": INFERRED}

    for m in _CLIENT.finditer(text):
        add(re.split(r"\s*[+\-\u2212(]\s*\d", m.group(1))[0], "client")
    for m in _entity_regex().finditer(text):
        add(m.group(1), "client/issuer")
    for m in _BOOK_CODE.finditer(text):
        add(m.group(1), "book/strategy")
    for term in config.KNOWN_DRIVER_TERMS:
        if re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(term), text, re.I):
            add(term, "desk/driver")

    amounts = extract_amounts(text)
    # Link a name to an amount only when they sit right next to each other:
    #   "-2.4mm Healthcare_MV", "+0.3MM from AP CORE..", "+1824K (Client:PK..)"
    #   "Upfront fee +1824K", "Hedging Pod: +0.2 mm", "DCM fee of +86K"
    # Otherwise no amount is attached (better none than a wrong one).
    before_gap = re.compile(r'^\s*(?:on|from|in|to)?\s*(?:\(\s*clients?\s*:\s*)?"?\s*$', re.I)
    after_gap = re.compile(r'^"?\s*(?::|of|was|=|at)?\s*$', re.I)
    for item in found.values():
        name_l = item["name"].lower()
        for line in text.split("\n"):
            pos = line.lower().find(name_l)
            if pos == -1:
                continue
            end = pos + len(name_l)
            link = None
            for m in _AMOUNT.finditer(line):
                if bool(m.group("open")) != bool(m.group("close")):
                    continue
                if m.end() <= pos and before_gap.match(line[m.end():pos]):
                    link = m
                elif m.start() >= end and after_gap.match(line[end:m.start()]) and link is None:
                    link = m
            if link:
                match = next((a for a in amounts if a["as_written"] == link.group(0).strip()), None)
                if match:
                    item.update({"dollars": match["dollars"], "display": match["display"],
                                 "as_written": match["as_written"]})
                break
    # clients first, then by size
    order = {"client": 0, "client/issuer": 1, "book/strategy": 2, "desk/driver": 3}
    return sorted(found.values(), key=lambda d: (order[d["type"]], -abs(d.get("dollars") or 0)))


def headline_check(text, actual_dollars, label):
    """If the comment opens with an amount, compare it with the row's Actual.

    Returns a flag dict or None. Informational only: comments often describe a
    component (e.g. 'Total CLO +7K: Fee Accrual') rather than the whole row.
    """
    amounts = extract_amounts(text)
    if not amounts or actual_dollars is None:
        return None
    first = amounts[0]
    if display_text(text).find(first["as_written"]) > 45:
        return None
    num = re.search(r"\d+(?:\.(\d+))?", first["as_written"])
    decimals = len(num.group(1) or "") if num else 0
    unit = first["dollars"] / float(num.group(0)) if num and float(num.group(0)) else 1
    precision = abs(unit) * (10 ** -decimals) / 2      # half of the last stated digit
    if abs(first["dollars"] - actual_dollars) <= precision + 1000:
        return None
    return {"level": "INFO", "basis": INFERRED,
            "message": "Analyst comment opens with %s but %s Actual is %s - comment may describe "
                       "only part of the row or be stale" % (first["as_written"], label,
                                                            fmt_k(actual_dollars))}
