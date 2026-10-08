"""
Step 5 - deterministic analytics for every node:

* reconciliation: drivers -> TOTAL, TOTAL -> Revenues, Sub-Total -> NTA+MTM,
  children -> parent (revenue and each driver), Commentary Actual -> Decmp,
  Variance -> Actual - Estimate, summary tables -> detail totals
* ranking of children and drivers by ABSOLUTE size (sign kept)
* contribution % (signed share of the parent) and share of gross movement
* which children lead each driver (for "led by IG USA" style commentary)
* named drivers pulled up from children's comments
* an overall confidence per row
"""
from . import config
from .comments import extract_amounts, extract_named, headline_check, display_text
from .utils import (VERIFIED, INFERRED, UNVERIFIED, reconcile, safe_pct, fmt_k, norm_label)

DRIVERS = config.DRIVER_KEYS


def _driver_values(node):
    return {k: node.values.get(k) for k in DRIVERS}


def node_checks(tree, node, decmp_summary, comm_summary):
    v = node.values
    checks = []
    drv = [v.get(k) for k in DRIVERS]
    if v.get("total") is not None and any(x is not None for x in drv):
        checks.append(reconcile("drivers_sum_vs_decomp_total", v["total"],
                                sum(x or 0 for x in drv), "decomp_total", "drivers_sum"))
    if v.get("revenue") is not None and v.get("total") is not None:
        checks.append(reconcile("decomp_total_vs_revenue", v["revenue"], v["total"],
                                "revenue", "decomp_total"))
    if v.get("subtotal") is not None:
        checks.append(reconcile("subtotal_vs_nta_plus_mtm", v["subtotal"],
                                (v.get("nta") or 0) + (v.get("reval") or 0), "subtotal", "nta_plus_mtm"))
    if node.children:
        for key in ["revenue"] + DRIVERS:
            if v.get(key) is None:
                continue
            kids = [tree.nodes[c].values.get(key) for c in node.children]
            chk = reconcile("children_sum_vs_parent:%s" % key, v[key], sum(k or 0 for k in kids),
                            "parent_total", "children_sum")
            if key == "revenue" or chk["status"] != "PASS":
                checks.append(chk)
    c = node.commentary
    act = c.get("actual", {}).get("value")
    if c.get("row") is not None and act is not None:
        checks.append(reconcile("commentary_actual_vs_decmp_revenue", v.get("revenue"), act,
                                "decmp_revenue", "commentary_actual"))
    est = c.get("estimate", {}).get("value")
    var = c.get("variance", {}).get("value")
    if c.get("row") is not None and None not in (act, est, var):
        checks.append(reconcile("variance_vs_actual_minus_estimate", act - est, var,
                                "actual_minus_estimate", "reported_variance"))
    for name, table in (("decmp_summary_table", decmp_summary), ("commentary_summary_table", comm_summary)):
        sr = table.get(node.name) or table.get(norm_label(node.header_label))
        if sr is None or node.kind == "leaf":
            continue
        key = "revenue" if "revenue" in sr.values else "actual"
        checks.append(reconcile("%s_row_%d_vs_detail" % (name, sr.excel_row),
                                v.get("revenue"), sr.values.get(key), "detail_total", "summary_table"))
    return checks


def rank(items, whole):
    """items: [(name, dollars)] -> ranked list of dicts (abs size, sign kept)."""
    present = [(n, x) for n, x in items if x is not None]
    gross = sum(abs(x) for _, x in present)
    out = []
    for i, (n, x) in enumerate(sorted(present, key=lambda t: -abs(t[1])), 1):
        out.append({"rank": i, "name": n, "dollars": round(x, 2), "display": fmt_k(x),
                    "direction": "positive" if x > 0 else ("negative" if x < 0 else "flat"),
                    "contribution_pct": safe_pct(x, whole),
                    "gross_share_pct": safe_pct(abs(x), gross) if gross else None})
    return out


def driver_leaders(tree, node):
    """For each driver of a parent: children contributing most in the SAME direction."""
    out = {}
    for k in DRIVERS:
        total = node.values.get(k)
        if not node.children or total is None or abs(total) < config.ZERO_THRESHOLD:
            continue
        same = [(tree.nodes[c].label, tree.nodes[c].values.get(k)) for c in node.children]
        same = [(n, x) for n, x in same if x is not None and x * total > 0]
        same.sort(key=lambda t: -abs(t[1]))
        opposite = [(tree.nodes[c].label, tree.nodes[c].values.get(k)) for c in node.children]
        opposite = [(n, x) for n, x in opposite if x is not None and x * total < 0
                    and abs(x) >= config.ZERO_THRESHOLD]
        opposite.sort(key=lambda t: -abs(t[1]))
        out[k] = {"leaders": [{"name": n, "display": fmt_k(x)} for n, x in same[:2]],
                  "offsets": [{"name": n, "display": fmt_k(x)} for n, x in opposite[:1]]}
    return out


def driver_split(ranked):
    """Gains vs losses among the drivers, so 'offsetting' is stated by Python."""
    gains = [d for d in ranked if d["dollars"] >= config.ZERO_THRESHOLD]
    losses = [d for d in ranked if d["dollars"] <= -config.ZERO_THRESHOLD]
    return {
        "gains": [{"name": d["name"], "display": d["display"]} for d in gains],
        "gains_total": {"display": fmt_k(sum(d["dollars"] for d in gains))} if gains else None,
        "losses": [{"name": d["name"], "display": d["display"]} for d in losses],
        "losses_total": {"display": fmt_k(sum(d["dollars"] for d in losses))} if losses else None,
    }


def variance_vs_estimate(node):
    """Actual vs Trader Estimate in words + percent (Python decides, AI repeats)."""
    c = node.commentary
    est = c.get("estimate", {}).get("value")
    var = c.get("variance", {}).get("value")
    if est is None or var is None:
        return {"direction": "unavailable", "pct": None}
    if abs(var) <= config.RECON_ABS_TOL:
        return {"direction": "in line", "pct": safe_pct(var, abs(est)) if abs(est) >= config.ZERO_THRESHOLD else None}
    pct = safe_pct(var, abs(est)) if abs(est) >= config.ZERO_THRESHOLD else None
    return {"direction": "above estimate" if var > 0 else "below estimate", "pct": pct}


def confidence(node):
    statuses = [c["status"] for c in node.recon]
    bases = [f["basis"] for f in node.flags if f["level"] != "INFO"] + [node.hierarchy_basis]
    levels = [f["level"] for f in node.flags]
    if "FAIL" in statuses or "FAIL" in levels:
        return "LOW"
    if "WARN" in statuses or "WARN" in levels or UNVERIFIED in bases:
        return "MEDIUM"
    if INFERRED in bases or node.commentary.get("estimate", {}).get("basis") == INFERRED:
        return "MEDIUM"
    return "HIGH"


def analyse(tree, decmp_summary, comm_summary):
    for node in reversed(list(tree.walk())):        # children before parents
        node.recon.extend(node_checks(tree, node, decmp_summary, comm_summary))
        actual = node.commentary.get("actual", {}).get("value", node.values.get("revenue"))
        a = node.analytics
        a["drivers_ranked"] = rank([(config.DRIVER_NAMES[k], node.values.get(k)) for k in DRIVERS],
                                   node.values.get("total"))
        a["children_ranked"] = rank([(tree.nodes[c].label, tree.nodes[c].commentary.get("actual", {})
                                      .get("value", tree.nodes[c].values.get("revenue")))
                                     for c in node.children], actual)
        a["driver_split"] = driver_split(a["drivers_ranked"])
        a["variance_vs_estimate"] = variance_vs_estimate(node)
        if node.children:
            a["driver_leaders"] = driver_leaders(tree, node)
        if node.kind == "group" and not node.children:
            node.flag("INFO", "No child rows under this business; commentary relies on its own "
                      "decomposition only", VERIFIED)
        # Comments: amounts + names for this row
        amounts, names = [], []
        for frag in node.comments:
            amounts += extract_amounts(frag["raw"])
            names += extract_named(frag["raw"])
            flag = headline_check(frag["raw"], actual, node.label) if frag["basis"] == VERIFIED else None
            if flag:
                node.flags.append(flag)
        a["comment_amounts"] = amounts
        a["named_drivers"] = names
        # Parents: elevate named drivers from descendants (largest first)
        if node.children:
            pooled = []
            for leaf in tree.leaves(node.key):
                for n in leaf.analytics.get("named_drivers", []):
                    pooled.append(dict(n, from_row=leaf.label))
            pooled.sort(key=lambda d: (d["type"] not in ("client", "client/issuer"),
                                       -abs(d.get("dollars") or 0)))
            a["named_from_children"] = pooled
        a["zero_actual"] = actual is not None and abs(actual) < config.ZERO_THRESHOLD
        if a["zero_actual"]:
            node.flag("INFO", "Actual is ~zero; contribution percentages not meaningful", VERIFIED)
        node.analytics["confidence"] = confidence(node)
