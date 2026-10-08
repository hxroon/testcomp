"""
Step 2 - build the business hierarchy from the Decmp sheet layout.

The workbook has no hierarchy columns, so the tree is inferred from layout:

    Credit                     <- header row (label only, a later "Credit Total" exists)
    INVESTMENT GRADE           <- header row
       IG CDA ... IG APAC      <- leaf rows (label + numbers)
    Investment Grade Total     <- closes INVESTMENT GRADE
       Credit Derivatives      <- leaf with no header ...
    Credit Derivatives Total   <- ... closed by a total: "implicit group" (flagged)
    Credit Total               <- closes Credit
    Spread Products Total      <- grand total (desk); stops the main block

Everything after the grand total (the second roll-up table, legends) is read
separately as a "summary block" and only used for cross-checks.
"""
import logging
from dataclasses import dataclass, field

from . import config
from .utils import (VERIFIED, INFERRED, UNVERIFIED, is_total_label, total_base,
                    norm_label, is_skip_label)

log = logging.getLogger(__name__)
NUMERIC_KEYS = ["revenue"] + config.DRIVER_KEYS + ["subtotal", "total"]


@dataclass
class Node:
    key: str
    label: str                      # display label (total label for groups)
    name: str                       # normalised base name used for matching
    kind: str                       # desk | group | leaf
    parent: str = None
    children: list = field(default_factory=list)
    depth: int = 0
    decmp_row: int = None           # leaf row, or total row for groups
    header_row: int = None
    header_label: str = ""
    values: dict = field(default_factory=dict)        # dollars, from Decmp
    hierarchy_basis: str = VERIFIED
    flags: list = field(default_factory=list)
    # filled in later
    commentary: dict = field(default_factory=dict)
    comments: list = field(default_factory=list)
    recon: list = field(default_factory=list)
    analytics: dict = field(default_factory=dict)
    row_id: str = ""

    def flag(self, level, message, basis=INFERRED):
        self.flags.append({"level": level, "basis": basis, "message": message})


class Tree:
    def __init__(self):
        self.nodes = {}
        self.root = None
        self.issues = []            # desk-level structural issues
        self.grand_total_row = None

    def add(self, node):
        if node.key in self.nodes:
            i = 2
            while "%s#%d" % (node.key, i) in self.nodes:
                i += 1
            node.key = "%s#%d" % (node.key, i)
        self.nodes[node.key] = node
        return node

    def attach(self, child, parent):
        child.parent = parent.key
        parent.children.append(child.key)

    def walk(self, key=None, depth=0):
        """Pre-order: parent first, then children (report order)."""
        key = key or self.root
        node = self.nodes[key]
        node.depth = depth
        yield node
        for ck in node.children:
            yield from self.walk(ck, depth + 1)

    def leaves(self, key):
        node = self.nodes[key]
        if node.kind == "leaf":
            return [node]
        out = []
        for ck in node.children:
            out.extend(self.leaves(ck))
        return out


def build_tree(rows, desk_title):
    """rows: RawRows of the Decmp sheet below the header. Returns Tree."""
    tree = Tree()
    desk_name = norm_label(desk_title) or "desk"
    root = tree.add(Node(key="desk", label=(desk_title or "Desk") + " Total", name=desk_name,
                         kind="desk", header_label=desk_title))
    tree.root = root.key
    total_bases = {total_base(r.label) for r in rows if r.label and is_total_label(r.label)}
    stack = [root]

    def trailing_leaves(group):
        out = []
        for ck in reversed(group.children):
            if tree.nodes[ck].kind != "leaf":
                break
            out.append(ck)
        return list(reversed(out))

    for r in rows:
        label = r.label
        if not label and not r.has_numbers:
            continue
        for p in r.problems:
            tree.issues.append({"level": "WARN", "basis": VERIFIED,
                                "message": "Decmp row %d: %s" % (r.excel_row, p)})
        if label and is_skip_label(label):
            log.debug("skip metadata row %d '%s'", r.excel_row, label)
            continue
        if not label:  # numbers without a name
            leaf = tree.add(Node(key="unlabelled-%d" % r.excel_row,
                                 label="(unlabelled row %d)" % r.excel_row,
                                 name="unlabelled row %d" % r.excel_row, kind="leaf",
                                 decmp_row=r.excel_row, values=dict(r.values)))
            leaf.flag("WARN", "Row %d has numbers but no business name" % r.excel_row, UNVERIFIED)
            tree.attach(leaf, stack[-1])
            continue

        if is_total_label(label):
            base = total_base(label)
            # Grand total: closes the desk and ends the main block.
            if base == desk_name or (not desk_title and len(stack) == 1 and not trailing_leaves(root)):
                for open_group in stack[1:]:
                    open_group.flag("FAIL", "Header '%s' was never closed by a Total row"
                                    % open_group.header_label, UNVERIFIED)
                root.values = dict(r.values)
                root.decmp_row = r.excel_row
                root.label = label
                tree.grand_total_row = r.excel_row
                break
            names = [g.name for g in stack]
            if base in names[1:]:
                # pop any unclosed groups above the matching one
                while stack[-1].name != base:
                    g = stack.pop()
                    g.flag("WARN", "Header '%s' not closed before '%s'" % (g.header_label, label),
                           UNVERIFIED)
                    tree.attach(g, stack[-1])
                group = stack.pop()
                group.values, group.decmp_row, group.label = dict(r.values), r.excel_row, label
                tree.attach(group, stack[-1])
                continue
            # No header row: the leaves just above form an implicit group.
            parent = stack[-1]
            group = tree.add(Node(key="grp-" + base, label=label, name=base, kind="group",
                                  decmp_row=r.excel_row, values=dict(r.values),
                                  header_label=label[: -len("total")].strip(),
                                  hierarchy_basis=INFERRED))
            kids = trailing_leaves(parent)
            for ck in kids:
                parent.children.remove(ck)
                tree.attach(tree.nodes[ck], group)
            if kids:
                group.flag("INFO", "No header row above '%s'; children inferred as the %d row(s) "
                           "directly above it" % (label, len(kids)))
            else:
                group.flag("INFO", "'%s' has no child rows; reported total used as-is" % label)
            tree.attach(group, parent)
            continue

        if not r.has_numbers:
            if norm_label(label) in total_bases:
                stack.append(tree.add(Node(key="grp-" + norm_label(label), label=label,
                                           name=norm_label(label), kind="group",
                                           header_row=r.excel_row, header_label=label)))
            else:
                log.info("Decmp row %d '%s' has no numbers and no matching Total - ignored",
                         r.excel_row, label)
            continue

        # Leaf row - check for duplicates under the same parent
        parent = stack[-1]
        dup = next((tree.nodes[ck] for ck in parent.children
                    if tree.nodes[ck].name == norm_label(label)), None)
        if dup is not None and dup.values == r.values:
            dup.flag("WARN", "Duplicate row %d ignored (same name and values as row %d)"
                     % (r.excel_row, dup.decmp_row), VERIFIED)
            continue
        leaf = tree.add(Node(key="leaf-" + norm_label(label), label=label, name=norm_label(label),
                             kind="leaf", decmp_row=r.excel_row, values=dict(r.values)))
        if dup is not None:
            leaf.label = "%s (row %d)" % (label, r.excel_row)
            leaf.flag("WARN", "Same name as row %d but different values - kept both"
                      % dup.decmp_row, VERIFIED)
        tree.attach(leaf, parent)
    else:
        tree.issues.append({"level": "FAIL", "basis": UNVERIFIED,
                            "message": "No grand total row ('%s Total') found on Decmp; desk "
                                       "values are computed from businesses" % desk_title})
        while len(stack) > 1:
            g = stack.pop()
            g.flag("FAIL", "Header '%s' was never closed by a Total row" % g.header_label,
                   UNVERIFIED)
            tree.attach(g, stack[-1])
        root.values = {k: sum((tree.nodes[c].values.get(k) or 0) for c in root.children)
                       for k in NUMERIC_KEYS}
        root.hierarchy_basis = INFERRED

    if not root.children:
        raise_msg = "No business rows were found under the Decmp header."
        from .utils import WorkbookFormatError
        raise WorkbookFormatError(raise_msg)
    list(tree.walk())  # sets depths
    return tree


def read_summary_block(rows, desk_title):
    """Rows of a secondary roll-up table -> {normalised label: RawRow}."""
    out = {}
    for r in rows:
        if not r.label or is_skip_label(r.label) or not r.has_numbers:
            continue
        out.setdefault(norm_label(r.label), r)
        if norm_label(r.label) in (norm_label(desk_title), norm_label(desk_title + " total")):
            break
    return out
