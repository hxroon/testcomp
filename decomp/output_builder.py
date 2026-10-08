"""
Step 6 - outputs.

facts.json      everything Python knows, with VERIFIED/INFERRED/UNVERIFIED labels
                (for audit, debugging and the HTML builder)
ai_input*.txt   compact, pre-formatted facts for the commentary agent - split
                into parts when it would not fit the agent's context budget
"""
import re
from datetime import datetime

from . import config
from .utils import VERIFIED, INFERRED, UNVERIFIED, fmt_k, fmt_pct

SHORT = config.DRIVER_SHORT
NAME_TO_SHORT = {config.DRIVER_NAMES[k]: SHORT[k] for k in config.DRIVER_KEYS}


# ------------------------------------------------------------ helpers ----
def actual_of(node):
    return node.commentary.get("actual", {}).get("value", node.values.get("revenue"))


def parse_report_date(date_text, filename):
    """Date from the sheet header ('Daily: May 12, 2026') and/or file name."""
    from_sheet = from_file = None
    m = re.search(r"([A-Za-z]+ \d{1,2}, \d{4})", date_text or "")
    if m:
        try:
            from_sheet = datetime.strptime(m.group(1), "%B %d, %Y").date()
        except ValueError:
            pass
    m = re.search(r"(20\d{2})(\d{2})(\d{2})", filename)
    if m:
        try:
            from_file = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except ValueError:
            pass
    if from_sheet and from_file and from_sheet != from_file:
        return {"date": str(from_sheet), "basis": UNVERIFIED,
                "note": "sheet says %s but file name says %s" % (from_sheet, from_file)}
    if from_sheet and from_file:
        return {"date": str(from_sheet), "basis": VERIFIED, "note": "sheet header and file name agree"}
    d = from_sheet or from_file
    return {"date": str(d) if d else None, "basis": INFERRED if d else UNVERIFIED,
            "note": "from %s only" % ("sheet header" if from_sheet else "file name") if d else "not found"}


def business_name(node):
    """'Securitization Total' -> 'Securitization' for parents; leaves unchanged."""
    if node.kind != "leaf" and re.search(r"\s+total$", node.label, re.I):
        return re.sub(r"\s+total$", "", node.label, flags=re.I)
    return node.label


def _material(d):
    """Driver worth mentioning: not ~zero and at least 1% of the gross movement."""
    return d["direction"] != "flat" and (d.get("gross_share_pct") or 0) >= 1.0 and \
        abs(d["dollars"]) >= config.ZERO_THRESHOLD


def assign_ids(tree):
    for i, node in enumerate(tree.walk(), 1):
        node.row_id = "R%02d" % i


# ------------------------------------------------- executive summary ----
def summary_facts(tree):
    nodes = list(tree.walk())
    desk = tree.nodes[tree.root]
    level1 = [n for n in nodes if n.depth == 1]
    leaves = [n for n in nodes if n.kind == "leaf"]

    def lst(items):
        return [{"name": business_name(n),
                 "row_id": n.row_id, "display": fmt_k(actual_of(n))} for n in items]

    pos_biz = sorted([n for n in level1 if (actual_of(n) or 0) > 0], key=lambda n: -actual_of(n))
    pos_leaf = sorted([n for n in leaves if (actual_of(n) or 0) > 0], key=lambda n: -actual_of(n))
    neg_leaf = sorted([n for n in leaves if (actual_of(n) or 0) < -config.ZERO_THRESHOLD],
                      key=lambda n: actual_of(n))
    neg_biz = sorted([n for n in level1 if (actual_of(n) or 0) < -config.ZERO_THRESHOLD],
                     key=lambda n: actual_of(n))

    drivers = []
    for d in desk.analytics["drivers_ranked"]:
        if not _material(d):
            continue
        key = next(k for k in config.DRIVER_KEYS if config.DRIVER_NAMES[k] == d["name"])
        sign = 1 if d["dollars"] >= 0 else -1
        lead = sorted([l for l in leaves if (l.values.get(key) or 0) * sign >= config.ZERO_THRESHOLD],
                      key=lambda l: -abs(l.values.get(key) or 0))[:3]
        drivers.append(dict(d, short=SHORT[key],
                            leading_lines=[{"name": l.label, "display": fmt_k(l.values.get(key))}
                                           for l in lead]))
    flows = [n for n in desk.analytics.get("named_from_children", []) if n.get("dollars")]
    seen, top_flows = set(), []
    for n in sorted(flows, key=lambda n: (n["type"] not in ("client", "client/issuer"),
                                          -abs(n["dollars"]))):
        if n["name"].lower() in seen:
            continue
        seen.add(n["name"].lower())
        top_flows.append({"name": n["name"], "type": n["type"], "display": n["display"],
                          "as_written": n.get("as_written"), "from_row": n["from_row"]})
        if len(top_flows) >= config.TOP_N_SUMMARY_FLOWS:
            break
    big_var = sorted([n for n in leaves if n.commentary.get("variance", {}).get("value") is not None],
                     key=lambda n: -abs(n.commentary["variance"]["value"]))[:3]
    largest_variances = [{"name": n.label, "display": fmt_k(n.commentary["variance"]["value"], signed=True)}
                         for n in big_var if abs(n.commentary["variance"]["value"]) > config.RECON_ABS_TOL]
    return {
        "largest_variances": largest_variances,
        "desk": {"actual": fmt_k(actual_of(desk)),
                 "estimate": fmt_k(desk.commentary.get("estimate", {}).get("value")),
                 "variance": fmt_k(desk.commentary.get("variance", {}).get("value"), signed=True)},
        "S1_top_positive_businesses": lst(pos_biz[:3]),
        "S1_top_positive_lines": lst(pos_leaf[:3]),
        "S2_S3_desk_drivers_ranked": drivers,
        "S4_named_flows": top_flows,
        "S5_negative_lines": lst(neg_leaf),
        "S5_negative_businesses": lst(neg_biz),
    }


# --------------------------------------------------------- facts.json ----
def node_record(tree, node):
    c = node.commentary
    a = node.analytics

    def cv(key):
        d = c.get(key, {})
        return {"value": d.get("value"), "display": fmt_k(d.get("value"), signed=(key == "variance")),
                "basis": d.get("basis"), "source": d.get("source")}

    return {
        "row_id": node.row_id, "business": node.label, "kind": node.kind, "depth": node.depth,
        "parent_business": tree.nodes[node.parent].label if node.parent else None,
        "parent_row_id": tree.nodes[node.parent].row_id if node.parent else None,
        "children_row_ids": [tree.nodes[k].row_id for k in node.children],
        "hierarchy_basis": node.hierarchy_basis,
        "source_rows": {"decmp": node.decmp_row, "decmp_header": node.header_row,
                        "commentary": c.get("row")},
        "actual": cv("actual"), "estimate": cv("estimate"), "variance": cv("variance"),
        "decomp": {k: {"value": node.values.get(k), "display": fmt_k(node.values.get(k))}
                   for k in ["revenue"] + config.DRIVER_KEYS + ["subtotal", "total"]},
        "analyst_comment": {
            "fragments": [{"raw": f["raw"], "cell": f["cell"], "basis": f["basis"],
                           "note": f["note"]} for f in node.comments],
            "is_empty": not node.comments,
        },
        "ave_comment": c.get("ave_comment", ""),
        "top_children": a.get("children_ranked", [])[:config.TOP_N_CHILDREN],
        "top_drivers": a.get("drivers_ranked", [])[:config.TOP_N_DRIVERS],
        "all_children": a.get("children_ranked", []),
        "all_drivers": a.get("drivers_ranked", []),
        "driver_leaders": a.get("driver_leaders", {}),
        "driver_split": a.get("driver_split"),
        "variance_vs_estimate": a.get("variance_vs_estimate"),
        "children_detail": [_child_detail(tree, tree.nodes[k]) for k in node.children],
        "named_drivers": a.get("named_drivers", []),
        "named_from_children": a.get("named_from_children", [])[:8],
        "comment_amounts": a.get("comment_amounts", []),
        "reconciliation": node.recon,
        "reconciliation_status": _overall(node.recon),
        "confidence": a.get("confidence"),
        "flags": node.flags,
    }


def _child_detail(tree, child):
    c = child.commentary
    main = next((d for d in child.analytics.get("drivers_ranked", []) if _material(d)), None)
    return {
        "row_id": child.row_id, "name": child.label,
        "actual": {"display": fmt_k(actual_of(child))},
        "estimate": {"display": fmt_k(c.get("estimate", {}).get("value"))},
        "variance": {"display": fmt_k(c.get("variance", {}).get("value"), signed=True)},
        "main_driver": ({"name": main["name"], "display": main["display"]} if main else None),
    }


def _overall(checks):
    s = [c["status"] for c in checks]
    for level in ("FAIL", "WARN", "PASS"):
        if level in s:
            return level
    return "NOT_APPLICABLE"


def build_facts(tree, meta):
    assign_ids(tree)
    rows = [node_record(tree, n) for n in tree.walk()]
    return {"meta": meta, "issues": tree.issues, "executive_summary_facts": summary_facts(tree),
            "rows": rows}


# ------------------------------------------------------- AI input text ----
def _flat(text):
    """One-line version of an analyst comment (words unchanged)."""
    t = re.sub(r"_x000[dD]_|\r|\n", " | ", str(text))
    t = re.sub(r"(\s*\|\s*)+", " | ", t)
    return t.strip(" |")


def _drivers_text(r):
    drv = [d for d in r["all_drivers"] if _material(d)][:config.TOP_N_DRIVERS + 1]
    return "; ".join("%s %s (%s of gross)" % (NAME_TO_SHORT[d["name"]], d["display"],
                                              fmt_pct(d["gross_share_pct"])) for d in drv)


def _row_block(r, by_id):
    kind = {"desk": "DESK TOTAL", "group": "PARENT", "leaf": "LINE"}[r["kind"]]
    head = "%s | %s | %s" % (r["row_id"], r["business"], kind)
    if r["parent_business"]:
        head += " | inside %s" % r["parent_business"]
    out = [head]

    def val(d):
        mark = "~" if d["basis"] == INFERRED else ("?" if d["basis"] == UNVERIFIED else "")
        return mark + d["display"]

    ve = r["variance_vs_estimate"] or {}
    vtxt = ve.get("direction", "")
    if ve.get("pct") is not None and vtxt not in ("unavailable", "in line"):
        vtxt += " by %s" % fmt_pct(abs(ve["pct"]))
    out.append("PY numbers: Actual %s | Estimate %s | Variance %s (%s)" % (
        val(r["actual"]), val(r["estimate"]), val(r["variance"]), vtxt))
    drivers = _drivers_text(r)
    if drivers:
        out.append("PY drivers (largest first): " + drivers)
    sp = r["driver_split"]
    if sp and sp["gains"] and sp["losses"]:
        out.append("PY offset: gains %s = %s | losses %s = %s" % (
            " + ".join("%s %s" % (NAME_TO_SHORT[x["name"]], x["display"]) for x in sp["gains"]),
            sp["gains_total"]["display"],
            " + ".join("%s %s" % (NAME_TO_SHORT[x["name"]], x["display"]) for x in sp["losses"]),
            sp["losses_total"]["display"]))
    if r["children_detail"]:
        kids = sorted(r["children_detail"], key=lambda k: -abs(_num(k["actual"]["display"])))
        out.append("PY children (largest first): " + " || ".join(
            "%s: A %s, E %s, V %s%s" % (
                k["name"], k["actual"]["display"], k["estimate"]["display"], k["variance"]["display"],
                (", main driver %s %s" % (NAME_TO_SHORT[k["main_driver"]["name"]], k["main_driver"]["display"]))
                if k["main_driver"] else "") for k in kids))
        tc = r["top_children"]
        if any(abs(k["contribution_pct"] or 0) > 150 or k["contribution_pct"] is None for k in tc):
            out.append("PY note: children offset each other; do not quote % of the parent total")
        else:
            out.append("PY share of parent: " + "; ".join("%s %s" % (k["name"], fmt_pct(k["contribution_pct"]))
                                                           for k in tc))
    if r["driver_leaders"]:
        bits = []
        for d in [d for d in r["all_drivers"] if _material(d)][:config.TOP_N_DRIVERS]:
            key = next(k for k in config.DRIVER_KEYS if config.DRIVER_NAMES[k] == d["name"])
            info = r["driver_leaders"].get(key)
            if not info or not info["leaders"]:
                continue
            txt = "%s led by %s" % (SHORT[key], ", ".join("%s %s" % (x["name"], x["display"])
                                                          for x in info["leaders"]))
            if info["offsets"]:
                txt += ", offset by %s %s" % (info["offsets"][0]["name"], info["offsets"][0]["display"])
            bits.append(txt)
        if bits:
            out.append("PY who drove each driver: " + "; ".join(bits))
    frags = r["analyst_comment"]["fragments"]
    if frags:
        txt = " // ".join(_flat(f["raw"]) for f in frags)
        lim = config.MAX_COMMENT_CHARS_IN_AI_INPUT
        if lim and len(txt) > lim:
            txt = txt[:lim].rsplit(" ", 1)[0] + " ..."
        out.append('ANALYST SAID (verbatim, unverified by Python): "%s"' % txt)
    named = r["named_drivers"] if r["kind"] == "leaf" else r["named_from_children"]
    named = [n for n in named if n.get("name")][:config.TOP_N_NAMED_ITEMS]
    if named:
        out.append("ANALYST-NAMED (pattern-extracted; amounts as the analyst wrote them): " + "; ".join(
            "%s%s%s" % (n["name"], (" " + n["as_written"]) if n.get("as_written") else "",
                        (" (in %s)" % n["from_row"]) if n.get("from_row") else "") for n in named))
    notes = [f["message"] for f in r["flags"] if f["level"] in ("WARN", "FAIL")]
    for c in [c for c in r["reconciliation"] if c["status"] in ("WARN", "FAIL")][:2]:
        notes.append("%s %s: difference %s" % (c["status"], c["check"], fmt_k(c.get("difference"))))
    if notes:
        out.append("FLAGS: " + "; ".join(notes[:3]))
    out.append("Confidence: %s" % r["confidence"])
    return "\n".join(out)


def _num(display):
    m = re.search(r"([\d,]+\.\d)", display or "")
    if not m:
        return 0.0
    v = float(m.group(1).replace(",", ""))
    return -v if "(" in display else v


def _header(facts):
    m = facts["meta"]
    return "\n".join([
        "### P&L FACTS | %s | Report date %s | values in C$ thousands, already formatted" % (
            m["desk"], m["report_date"]["date"]),
        "How to read this file:",
        "- PY = calculated by Python from the workbook and reconciled: safe to state as fact. Copy the figures exactly.",
        "- ANALYST SAID = the trader/analyst's own words: attribute it (\"the analyst notes\"), do not present it as verified.",
        "- ANALYST-NAMED = clients/books/desks Python spotted in analyst text. Quote names exactly as written.",
        "- A=Actual, E=Trader Estimate, V=Variance (A minus E). ~ = rolled up by Python; ? = not available.",
        "- NTA=New Trading Activity, MTM=Portfolio Revaluation, Fees=Origination Fees/Commissions, Carry=Carry/Theta.",
        "- 'of gross' = share of the total absolute driver movement. Never recalculate anything.",
    ])


def _summary_block(facts):
    s = facts["executive_summary_facts"]
    j = lambda items: "; ".join("%s %s" % (i["name"], i["display"]) for i in items) or "none"
    drv = []
    for d in s["S2_S3_desk_drivers_ranked"]:
        lead = ", ".join("%s %s" % (x["name"], x["display"]) for x in d["leading_lines"])
        drv.append("%s %s (%s of desk)%s" % (d["short"], d["display"], fmt_pct(d["contribution_pct"]),
                                             " led by " + lead if lead else ""))
    flows = "; ".join("%s%s (%s, in %s)" % (f["name"], (" " + f["as_written"]) if f.get("as_written") else "",
                                            f["type"], f["from_row"])
                      for f in s["S4_named_flows"]) or "none named in analyst comments"
    vmiss = "; ".join("%s %s" % (v["name"], v["display"]) for v in s.get("largest_variances", [])) or "none"
    return "\n".join([
        "== DESK-LEVEL FACTS (for [S1]-[S5]) ==",
        "Desk: Actual %s | Estimate %s | Variance %s" % (s["desk"]["actual"], s["desk"]["estimate"], s["desk"]["variance"]),
        "S1 top positive businesses: %s | top positive lines: %s" % (j(s["S1_top_positive_businesses"]),
                                                                   j(s["S1_top_positive_lines"])),
        "S2/S3 desk drivers ranked: " + " || ".join(drv),
        "S4 named flows (ANALYST-NAMED, amounts as written): " + flows,
        "S5 negative businesses: %s | negative lines: %s" % (j(s["S5_negative_businesses"]),
                                                              j(s["S5_negative_lines"])),
        "Largest Actual-vs-Estimate misses (lines): " + vmiss,
    ])


def build_ai_inputs(facts):
    """Return [(filename, text)], split into parts that fit the agent's context.

    Part 1 = how-to-read legend + desk-level facts + the desk row. Every later
    part holds whole businesses (never half a parent), each row self-contained.
    """
    by_id = {r["row_id"]: r for r in facts["rows"]}
    header, summary = _header(facts), _summary_block(facts)
    tokens = lambda t: len(t) // 4
    blocks = [(r, _row_block(r, by_id)) for r in facts["rows"]]

    def tail(first):
        return ("Write [S1]-[S5], then one [Rnn] paragraph for EVERY row above, in order." if first else
                "Write one [Rnn] paragraph for EVERY row above, in order. No [S] lines in this part.")

    full = "\n".join([header, "", summary, "", "== ROWS =="] + ["\n".join(["", b]) for _, b in blocks] +
                     ["", tail(True)])
    if tokens(full) <= config.AI_INPUT_TOKEN_BUDGET:
        return [("ai_input.txt", full)]

    budget = config.AI_INPUT_TOKEN_BUDGET - tokens(header) - 80
    # boundaries: a new part may start at any depth-1 business (or depth-2 group if too big)
    parts, current, cur_tok = [], [], tokens(summary)
    for r, b in blocks:
        t = tokens(b)
        boundary = r["depth"] <= 1 or (r["depth"] == 2 and r["kind"] == "group")
        if current and boundary and cur_tok + t > budget:
            parts.append(current)
            current, cur_tok = [], 0
        elif current and cur_tok + t > budget * 1.35 and r["depth"] >= 2:
            parts.append(current)            # a single group is too big: split at the next row
            current, cur_tok = [], 0
        current.append(b)
        cur_tok += t
    if current:
        parts.append(current)
    out, n = [], len(parts)
    for i, body in enumerate(parts, 1):
        lines = [header + " | PART %d of %d" % (i, n), ""]
        if i == 1:
            lines += [summary, ""]
        lines += ["== ROWS =="] + ["\n".join(["", b]) for b in body] + ["", tail(i == 1)]
        out.append(("ai_input_part%d.txt" % i, "\n".join(lines)))
    return out
