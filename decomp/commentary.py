"""
Step 4 - read the Commentary sheet and attach it to the Decmp tree by LABEL.

Row positions differ between the two sheets (e.g. Spread Products Total is
row 40 on Decmp and row 61 on Commentary), and the Commentary sheet has its
own quirks, which are handled here:

* tall/merged comment cells -> only the top-left cell holds the text
* rows with a label + comment but no numbers (e.g. 'Securitization CDA')
  -> comment attached to the nearest business row above, flagged INFERRED
* duplicate labels (e.g. two 'Securitization Finance' rows) -> the row with
  numbers is the business line, the other contributes its comment only
* missing total rows (e.g. no 'Credit Total') -> Actual comes from Decmp,
  Estimate is rolled up from children (INFERRED) and checked against the
  Commentary summary table when one exists
"""
import logging
from dataclasses import dataclass, field

from .utils import (VERIFIED, INFERRED, UNVERIFIED, clean_text, is_skip_label,
                    is_total_label, norm_label, total_base, reconcile)
from .comments import display_text, is_empty_comment

log = logging.getLogger(__name__)


@dataclass
class CommentaryEntry:
    excel_row: int
    label: str
    norm: str
    values: dict
    comments: list = field(default_factory=list)   # [{'raw', 'cell', 'basis', 'note'}]
    ave_comment: str = ""
    closing_base: str = ""
    used: bool = False


def parse_commentary(rows, desk_title, comment_col_letter="F"):
    """rows: RawRows of the Commentary sheet main block. Returns (entries, issues)."""
    entries, issues = [], []
    grand = {norm_label(desk_title + " total")}
    pending_orphan = None
    for r in rows:
        raw_comment = r.texts.get("decomp_comment", "")
        ave = r.texts.get("ave_comment", "")
        label = r.label
        for p in r.problems:
            issues.append({"level": "WARN", "basis": VERIFIED,
                           "message": "Commentary row %d: %s" % (r.excel_row, p)})
        if label and is_skip_label(label):
            continue
        if r.has_numbers and not label:
            # numbers without a name: usually a merged-cell misalignment where the
            # label sits one row lower. Hold it and pair with the next label row.
            if pending_orphan is not None:
                issues.append({"level": "WARN", "basis": UNVERIFIED,
                               "message": "Commentary row %d has numbers but no label and could "
                                          "not be paired; ignored" % pending_orphan.excel_row})
            pending_orphan = r
            continue
        comment_row = r.excel_row
        if label and not r.has_numbers and pending_orphan is not None and not is_total_label(label):
            issues.append({"level": "INFO", "basis": INFERRED,
                           "message": "Commentary row %d numbers paired with label '%s' in row %d "
                                      "(merged/misaligned cells)" % (pending_orphan.excel_row, label,
                                                                     r.excel_row)})
            r.values = pending_orphan.values
            if is_empty_comment(raw_comment):
                raw_comment = pending_orphan.texts.get("decomp_comment", "")
                comment_row = pending_orphan.excel_row
            if not ave.strip():
                ave = pending_orphan.texts.get("ave_comment", "")
            pending_orphan = None
        elif pending_orphan is not None and (label or r.has_numbers):
            issues.append({"level": "WARN", "basis": UNVERIFIED,
                           "message": "Commentary row %d has numbers but no label and could not be "
                                      "paired; ignored" % pending_orphan.excel_row})
            pending_orphan = None
        if r.has_numbers:
            e = CommentaryEntry(r.excel_row, label, norm_label(label), dict(r.values),
                                ave_comment=display_text(ave))
            if not is_empty_comment(raw_comment):
                e.comments.append({"raw": raw_comment, "cell": "%s%d" % (comment_col_letter, comment_row),
                                   "basis": VERIFIED, "note": ""})
            entries.append(e)
            if e.norm in grand:
                break
            continue
        # no numbers: a section header, or a comment-only line
        if not is_empty_comment(raw_comment) or ave.strip():
            target = next((x for x in reversed(entries) if not is_total_label(x.label)), None)
            if target is None:
                issues.append({"level": "WARN", "basis": UNVERIFIED,
                               "message": "Comment in row %d ('%s') has no business row above it; "
                                          "not used" % (r.excel_row, label)})
                continue
            if not is_empty_comment(raw_comment):
                target.comments.append({
                    "raw": raw_comment, "cell": "%s%d" % (comment_col_letter, r.excel_row),
                    "basis": INFERRED,
                    "note": "from row %d%s, attached to '%s' (row %d)" % (
                        r.excel_row, " '%s'" % label if label else "", target.label, target.excel_row)})
            if ave.strip():
                target.ave_comment = (target.ave_comment + "\n" + display_text(ave)).strip()
    # which total closes each entry (used to disambiguate duplicate names)
    closing = ""
    for e in reversed(entries):
        if is_total_label(e.label):
            closing = total_base(e.label)
        e.closing_base = closing
    return entries, issues


def _find(entries, node, parent_name):
    target = norm_label(node.label if node.kind != "leaf" else node.label.split(" (row ")[0])
    cands = [e for e in entries if e.norm == target and not e.used]
    if len(cands) > 1:
        scoped = [e for e in cands if e.closing_base == parent_name or e.closing_base == node.name]
        cands = scoped or cands
    return cands[0] if cands else None


def attach_commentary(tree, entries, summary_rows, issues):
    """Fill node.commentary / node.comments; roll up missing parents."""
    for node in tree.walk():
        parent_name = tree.nodes[node.parent].name if node.parent else ""
        e = _find(entries, node, parent_name)
        c = node.commentary
        if e:
            e.used = True
            for key in ("actual", "estimate", "variance"):
                c[key] = {"value": e.values.get(key), "basis": VERIFIED if e.values.get(key) is not None else UNVERIFIED,
                          "source": "Commentary row %d" % e.excel_row}
            node.comments = e.comments
            c["ave_comment"] = e.ave_comment
            c["row"] = e.excel_row
        else:
            c["row"] = None
            c["ave_comment"] = ""
            c["actual"] = {"value": node.values.get("revenue"), "basis": VERIFIED,
                           "source": "Decmp Revenues (no matching Commentary row)"}
            c["estimate"] = {"value": None, "basis": UNVERIFIED, "source": "not found"}
            c["variance"] = {"value": None, "basis": UNVERIFIED, "source": "not found"}
            if node.kind == "leaf":
                node.flag("WARN", "No matching row on the Commentary sheet; Estimate unavailable",
                          UNVERIFIED)
    # Post-order roll-up for parents that had no Commentary row
    for node in reversed(list(tree.walk())):
        c = node.commentary
        if node.kind == "leaf" or c.get("row") is not None:
            continue
        kids = [tree.nodes[k].commentary for k in node.children]
        if kids and all(k["estimate"]["value"] is not None for k in kids):
            est = sum(k["estimate"]["value"] for k in kids)
            c["estimate"] = {"value": est, "basis": INFERRED,
                             "source": "sum of %d children (no Commentary total row)" % len(kids)}
            act = c["actual"]["value"]
            if act is not None:
                c["variance"] = {"value": act - est, "basis": INFERRED, "source": "Actual - Estimate"}
            sr = summary_rows.get(node.name) or summary_rows.get(norm_label(node.header_label))
            if sr is not None and sr.values.get("estimate") is not None:
                chk = reconcile("estimate_rollup_vs_commentary_summary", sr.values["estimate"], est,
                                "summary_table", "children_sum")
                node.recon.append(chk)
                if chk["status"] == "PASS":
                    c["estimate"]["basis"] = VERIFIED
                    c["estimate"]["source"] += "; confirmed by Commentary summary row %d" % sr.excel_row
                    c["variance"]["basis"] = VERIFIED
            node.flag("INFO", "No '%s' row on the Commentary sheet; Estimate/Variance rolled up "
                      "from children" % node.label, c["estimate"]["basis"])
        elif node.kind != "desk":
            node.flag("WARN", "No Commentary row and children incomplete; Estimate unavailable",
                      UNVERIFIED)
    for e in entries:
        if not e.used:
            issues.append({"level": "WARN", "basis": UNVERIFIED,
                           "message": "Commentary row %d '%s' did not match any Decmp business; "
                                      "check spelling or add to LABEL_ALIASES" % (e.excel_row, e.label)})
