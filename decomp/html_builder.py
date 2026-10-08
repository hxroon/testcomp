"""
Step 7 - build the HTML report.

Python owns: layout, numbers, the verbatim analyst comments, colours.
The AI owns: the text in the "AI Agent Comment" column and the 5 summary lines.

The AI reply is plain text, one tagged line per item:
    [S1] Securitization (C$ 2,285.0), ... were the largest revenue contributors.
    [R07] C$ 511.0 portfolio revaluations was the largest contributor ...
A JSON reply {"summary": {"S1": ...}, "rows": {"R07": ...}} is also accepted.

Before rendering, every C$ figure the AI wrote is checked against the figures
Python produced. Unknown figures are listed in ai_check.txt (and the report's
data-checks panel) - they are not silently trusted.
"""
import html
import json
import re
from datetime import date

from . import config
from .comments import display_text

_TAG = re.compile(r"^\s*[*_`>#\-\s]*\[?(S[1-5]|R\d{2,3})\]?\s*[:.)\-]?\s*[*_]*\s*(.*)$")
_SECTION_PREFIX = re.compile(r"^(%s)\s*:\s*" % "|".join(re.escape(n) for _, n in config.SUMMARY_SECTIONS), re.I)


# --------------------------------------------------------- AI reply ----
def parse_ai_reply(text):
    """Return {'S1': '...', 'R07': '...'} from the agent's reply."""
    text = (text or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*|```\s*$", "", text, flags=re.M).strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
            out = {}
            out.update({k.upper(): str(v) for k, v in data.get("summary", {}).items()})
            out.update({k.upper(): str(v) for k, v in data.get("rows", {}).items()})
            return out
        except (ValueError, AttributeError):
            pass
    out, current = {}, None
    for line in text.splitlines():
        m = _TAG.match(line)
        if m:
            current = m.group(1).upper()
            out[current] = m.group(2).strip()
        elif current and line.strip():
            out[current] += " " + line.strip()
    for k, v in out.items():
        out[k] = _SECTION_PREFIX.sub("", v.strip().strip("*").strip())
    return out


def fix_number_format(text):
    """'C$ -209.0' / '-C$ 209' / 'C$ \u2013209' -> '(C$ 209.0)'; add '.0' where missing."""
    t = re.sub(r"[\-\u2212\u2013]\s*C\$\s*([\d,]+(?:\.\d+)?)", r"(C$ \1)", text)
    t = re.sub(r"C\$\s*[\-\u2212\u2013]\s*([\d,]+(?:\.\d+)?)", r"(C$ \1)", t)
    t = re.sub(r"\(\((C\$ [\d,.]+)\)\)", r"(\1)", t)
    t = re.sub(r"C\$\s*(\d[\d,]*)(?![\d,]*(?:\.\d|\s*(?:mm|MM|[kKmM])\b))(?=[^\d,]|$)",
               lambda m: "C$ %s%s" % (m.group(1).rstrip(","), config.DISPLAY_DECIMALS_SUFFIX), t)
    return t


def _allowed_figures(facts):
    allowed = set()

    def add(display):
        m = re.search(r"([\d,]+\.\d)", display or "")
        if m:
            allowed.add(m.group(1))

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "display" and isinstance(v, str):
                    add(v)
                else:
                    walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(facts)
    return allowed


def audit_ai_text(facts, replies):
    """List AI figures not present in the Python facts, plus missing/extra IDs."""
    allowed = _allowed_figures(facts)
    ids = {r["row_id"] for r in facts["rows"]}
    problems = []
    for key, text in replies.items():
        for m in re.finditer(r"C\$\s*([\d,]+\.\d)", text):
            if m.group(1) not in allowed:
                problems.append("[%s] figure C$ %s is not in the Python facts" % (key, m.group(1)))
    missing = sorted(ids - set(replies))
    extra = sorted(k for k in replies if k.startswith("R") and k not in ids)
    missing_s = [s for s, _ in config.SUMMARY_SECTIONS if s not in replies]
    if missing:
        problems.append("No AI comment for rows: %s" % ", ".join(missing))
    if missing_s:
        problems.append("No AI text for summary sections: %s" % ", ".join(missing_s))
    if extra:
        problems.append("AI wrote unknown row ids (ignored): %s" % ", ".join(extra))
    return problems


# ------------------------------------------------------------ render ----
CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI','SF Pro Display','Helvetica Neue',Arial,sans-serif;background-color:#EFF6FF;color:#334155;font-size:12px;line-height:1.5}
.header{background-color:#0B1D3A;color:white;padding:24px 40px;margin-bottom:40px}
.header h1{font-size:22px;font-weight:700;margin-bottom:4px}
.header p{font-size:12px;color:#93C5FD}
.container{max-width:1400px;margin:0 auto;padding:0 40px}
.card{background-color:#FFFFFF;border-radius:10px;padding:14px 16px;box-shadow:0 1px 3px rgba(11,29,58,0.06);margin-bottom:24px;border:1px solid #E2E8F0}
.section-title{font-size:15px;font-weight:700;color:#0B1D3A;margin-bottom:12px}
.summary-section{margin-bottom:12px;line-height:1.6}
.summary-section strong{font-weight:600;color:#0B1D3A}
table{width:100%;border-collapse:collapse;background-color:#FFFFFF;border-radius:10px;box-shadow:0 1px 3px rgba(11,29,58,0.06)}
th{background-color:#0B1D3A;color:white;padding:10px 16px;text-align:left;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px}
td{padding:12px 16px;border-bottom:1px solid #E2E8F0;font-size:11px;color:#334155;vertical-align:top}
tr.parent td{background-color:#F5F9FF;font-weight:700;color:#0B1D3A}
tr.desk td{background-color:#E6EEFA;font-weight:700;color:#0B1D3A;border-bottom:2px solid #0B1D3A}
td.num,tr.parent td.num,tr.desk td.num{text-align:right;font-family:Consolas,'Courier New',monospace;font-variant-numeric:tabular-nums;white-space:nowrap}
tr td.pos{color:#15803D} tr td.neg{color:#B91C1C} tr td.zero{color:#94A3B8}
td.comment{font-weight:400;color:#334155}
td.empty{color:#94A3B8;font-style:italic;font-weight:400}
td.pending{color:#B45309;font-style:italic;font-weight:400}
.badge{display:inline-block;margin-left:6px;padding:0 5px;border-radius:3px;font-size:9px;font-weight:600;background:#FEF3C7;color:#92400E}
details{margin-top:8px} summary{cursor:pointer;color:#0B1D3A;font-weight:600}
ul.checks{margin:8px 0 0 18px} ul.checks li{margin-bottom:4px}
.footer{text-align:center;font-size:10px;color:#94A3B8;padding:24px 40px;margin-top:40px}
@media (max-width:768px){.header,.container,.footer{padding-left:16px;padding-right:16px}.card{padding:12px 14px}th,td{padding:10px 12px;font-size:10px}}
"""


def _e(text):
    return html.escape(text or "", quote=True)


def _comment_html(text):
    return _e(display_text(text)).replace("\n", "<br>")


def _num_class(value):
    if value is None:
        return "num"
    k = round(value / 1000.0)
    return "num " + ("pos" if k > 0 else "neg" if k < 0 else "zero")


def render_html(facts, replies, problems):
    meta = facts["meta"]
    secs = []
    for sid, name in config.SUMMARY_SECTIONS:
        txt = replies.get(sid)
        body = _e(fix_number_format(txt)) if txt else '<span style="color:#B45309"><em>%s</em></span>' % _e(config.AI_PENDING_TEXT)
        secs.append('<div class="summary-section"><strong>%s:</strong> %s</div>' % (_e(name), body))

    trs = []
    for r in facts["rows"]:
        cls = {"desk": "desk", "group": "parent", "leaf": "child"}[r["kind"]]
        indent = 16 + 18 * r["depth"]
        badge = ""
        if r["confidence"] == "LOW" or r["reconciliation_status"] == "FAIL":
            tip = "; ".join([f["message"] for f in r["flags"] if f["level"] in ("WARN", "FAIL")] +
                            ["%s %s" % (c["status"], c["check"]) for c in r["reconciliation"]
                             if c["status"] in ("WARN", "FAIL")])
            badge = '<span class="badge" title="%s">CHECK</span>' % _e(tip)
        frags = r["analyst_comment"]["fragments"]
        if frags:
            note = "; ".join(f["note"] for f in frags if f["note"])
            decomp = '<td class="comment"%s>%s</td>' % (
                ' title="%s"' % _e(note) if note else "",
                "<br>".join(_comment_html(f["raw"]) for f in frags))
        else:
            decomp = '<td class="empty">%s</td>' % _e(config.NO_COMMENT_TEXT)
        ai = replies.get(r["row_id"])
        ai_td = ('<td class="comment">%s</td>' % _e(fix_number_format(ai)) if ai
                 else '<td class="pending">%s</td>' % _e(config.AI_PENDING_TEXT))
        trs.append(
            '<tr class="%s" id="%s"><td style="padding-left:%dpx">%s%s</td>'
            '<td class="num">%s</td><td class="num">%s</td><td class="%s">%s</td>%s%s</tr>' % (
                cls, r["row_id"], indent, _e(r["business"]), badge,
                _e(r["actual"]["display"]), _e(r["estimate"]["display"]),
                _num_class(r["variance"]["value"]), _e(r["variance"]["display"]), decomp, ai_td))

    checks = []
    for r in facts["rows"]:
        for c in r["reconciliation"]:
            if c["status"] in ("WARN", "FAIL"):
                checks.append("%s %s - %s: difference C$ %s (tolerance C$ %s)" % (
                    c["status"], r["business"], c["check"], "{:,.0f}".format(c.get("difference") or 0),
                    "{:,.0f}".format(c.get("tolerance") or 0)))
    checks += ["%s %s" % (i["level"], i["message"]) for i in facts["issues"]]
    checks += ["AI %s" % p for p in problems]
    checks_html = ("<p>All reconciliation checks passed.</p>" if not checks else
                   "<ul class=\"checks\">%s</ul>" % "".join("<li>%s</li>" % _e(c) for c in checks))

    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div class="header"><h1>{desk} {title}</h1><p>{subtitle} &middot; Report date {rdate} &middot; All values in C$ 000's</p></div>
<div class="container">
<div class="card"><h2 class="section-title">Executive Summary</h2>
{sections}
</div>
<table>
<thead><tr><th>Business</th><th>Actual (C$)</th><th>Estimate (C$)</th><th>Variance (C$)</th><th>Decomp Commentary</th><th>AI Agent Commentary</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
<div class="card" style="margin-top:24px"><details{open_}><summary>Data checks ({n_checks})</summary>{checks}</details>
<p style="margin-top:8px;color:#94A3B8">Numbers, hierarchy and analyst comments are produced by Python directly from the workbook; only the AI Agent Commentary and Executive Summary text are AI-written.</p></div>
</div>
<div class="footer"><p>End of report | All values in C$ thousands (C$ 000's) | Variance coloured by sign: green (positive), red (negative), grey (zero)</p>
<p>Prepared by {agent} | Source {src} | Report generated {today}</p></div>
</body>
</html>
""".format(title=_e(config.REPORT_TITLE), css=CSS, desk=_e(meta["desk"]),
           subtitle=_e(config.REPORT_SUBTITLE), rdate=_e(meta["report_date"]["date"] or "n/a"),
           sections="\n".join(secs), rows="\n".join(trs), checks=checks_html,
           n_checks=len(checks), open_=" open" if checks else "",
           agent=_e(config.AGENT_VERSION), src=_e(meta["source_file"]),
           today=date.today().strftime("%B %d, %Y"))
