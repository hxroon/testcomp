"""
Run all tests from the project folder:
    python -m unittest discover -s tests -v
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from decomp import config                                           # noqa: E402
from decomp.utils import (fmt_k, to_number, reconcile, safe_pct,     # noqa: E402
                          WorkbookFormatError)
from decomp.workbook_reader import RawRow                           # noqa: E402
from decomp.hierarchy import build_tree                             # noqa: E402
from decomp.calculations import rank                                # noqa: E402
from decomp.comments import extract_amounts, extract_named, display_text  # noqa: E402
from decomp.html_builder import parse_ai_reply, fix_number_format, audit_ai_text  # noqa: E402
from decomp.output_builder import build_ai_inputs                   # noqa: E402
from decomp.pipeline import preprocess                              # noqa: E402
import make_sample_workbook as sample                               # noqa: E402


def run(mutate=None):
    """Build a sample workbook (optionally broken on purpose) and preprocess it."""
    tmp = Path(tempfile.mkdtemp())
    path = sample.build(tmp / "Daily_SpreadDecompTEReport_20260512.xlsx", mutate)
    facts, inputs = preprocess(path, tmp / "out")
    return facts, tmp


def row(facts, name):
    return next(r for r in facts["rows"] if r["business"] == name)


# ------------------------------------------------------------ helpers ----
class TestFormatting(unittest.TestCase):
    def test_accounting_format(self):
        self.assertEqual(fmt_k(2_724_300), "C$ 2,724.0")
        self.assertEqual(fmt_k(-1_612_400), "(C$ 1,612.0)")
        self.assertEqual(fmt_k(-420_000), "(C$ 420.0)")
        self.assertEqual(fmt_k(-300), "C$ 0.0")          # rounds to zero: no brackets
        self.assertEqual(fmt_k(27_000, signed=True), "+C$ 27.0")
        self.assertEqual(fmt_k(None), "n/a")
        self.assertEqual(fmt_k(1_500), "C$ 2.0")          # half rounds up, not to even

    def test_to_number(self):
        self.assertEqual(to_number("(1,234)"), (-1234.0, None))
        self.assertEqual(to_number("-"), (0.0, None))
        self.assertEqual(to_number(None), (None, None))
        value, problem = to_number("n/a")
        self.assertIsNone(value)
        self.assertIn("n/a", problem)


class TestReconciliation(unittest.TestCase):
    def test_statuses(self):
        self.assertEqual(reconcile("x", 1_000_000, 1_000_800)["status"], "PASS")   # within C$1K
        self.assertEqual(reconcile("x", 100_000, 103_000)["status"], "WARN")       # 3K <= 5K
        r = reconcile("x", 100_000, 150_000)
        self.assertEqual(r["status"], "FAIL")
        self.assertEqual(r["difference"], 50_000)
        self.assertEqual(r["difference_pct"], 50.0)
        self.assertEqual(reconcile("x", None, 5)["status"], "NOT_APPLICABLE")

    def test_divide_by_zero(self):
        self.assertIsNone(safe_pct(100_000, 0))
        self.assertIsNone(safe_pct(100_000, 200))          # below ZERO_THRESHOLD
        self.assertEqual(safe_pct(50, 200_000), 0.03)


class TestRanking(unittest.TestCase):
    def test_absolute_ranking_keeps_sign(self):
        out = rank([("A", 300_000), ("B", -900_000), ("C", 50_000)], -550_000)
        self.assertEqual([o["name"] for o in out], ["B", "A", "C"])
        self.assertEqual(out[0]["display"], "(C$ 900.0)")
        self.assertEqual(out[0]["contribution_pct"], 163.64)       # signed share of parent
        self.assertEqual(out[0]["gross_share_pct"], 72.0)          # share of gross movement

    def test_zero_parent(self):
        out = rank([("A", 100_000), ("B", -100_000)], 0)
        self.assertIsNone(out[0]["contribution_pct"])
        self.assertEqual(out[0]["gross_share_pct"], 50.0)


# ---------------------------------------------------------- hierarchy ----
def rr(r, label, rev=None):
    v = None if rev is None else {"revenue": rev, "total": rev, "nta": rev, "reval": 0,
                                  "orig": 0, "carry": 0, "other": 0, "subtotal": rev}
    return RawRow("Decmp", r, label, values=v or {k: None for k in ["revenue", "total"]})


class TestHierarchy(unittest.TestCase):
    def test_nested_and_implicit_groups(self):
        rows = [rr(1, "Credit"), rr(2, "INVESTMENT GRADE"), rr(3, "IG A", 100), rr(4, "IG B", -40),
                rr(5, "Investment Grade Total", 60), rr(6, "Credit Derivatives", 5),
                rr(7, "Credit Derivatives Total", 5), rr(8, "Credit Total", 65),
                rr(9, "Desk Total", 65), rr(10, "Credit", 65)]   # row 10 = summary table, ignored
        t = build_tree(rows, "Desk")
        credit = t.nodes["grp-credit"]
        self.assertEqual([t.nodes[k].label for k in credit.children],
                         ["Investment Grade Total", "Credit Derivatives Total"])
        cd = t.nodes["grp-credit derivatives"]
        self.assertEqual(cd.hierarchy_basis, "INFERRED")
        self.assertEqual(t.grand_total_row, 9)

    def test_duplicate_and_unlabelled_rows(self):
        rows = [rr(1, "BIZ"), rr(2, "A", 10), rr(3, "A", 10), rr(4, "", 7), rr(5, "BIZ Total", 17),
                rr(6, "Desk Total", 17)]
        t = build_tree(rows, "Desk")
        biz = t.nodes["grp-biz"]
        labels = [t.nodes[k].label for k in biz.children]
        self.assertEqual(labels, ["A", "(unlabelled row 4)"])     # exact duplicate dropped
        self.assertTrue(any("Duplicate" in f["message"] for f in t.nodes["leaf-a"].flags))

    def test_unclosed_header_and_missing_grand_total(self):
        rows = [rr(1, "BIZ"), rr(2, "A", 10), rr(3, "BIZ Total", 10), rr(4, "OTHER"), rr(5, "B", 3),
                rr(6, "OTHER Total", 3)]
        t = build_tree(rows, "Desk")
        self.assertTrue(any(i["level"] == "FAIL" for i in t.issues))   # no grand total
        self.assertEqual(t.nodes["desk"].values["revenue"], 13)        # computed instead


# ----------------------------------------------------------- comments ----
class TestComments(unittest.TestCase):
    def test_amount_units(self):
        a = extract_amounts("Distressed -1.6mm, NTA (0.3)mm, fee +86K, 401(K) reval, cs01 +0.6mm")
        self.assertEqual([x["dollars"] for x in a], [-1_600_000, -300_000, 86_000, 600_000])

    def test_names(self):
        n = {x["name"]: x for x in extract_named(
            "-0.1MM MALLINCKRODT INTL FIN SA, Upfront fee +1824K (Client:PK ALIFT WH 1), -2.4mm Healthcare_MV")}
        self.assertEqual(n["PK ALIFT WH 1"]["type"], "client")
        self.assertEqual(n["PK ALIFT WH 1"]["dollars"], 1_824_000)
        self.assertEqual(n["MALLINCKRODT INTL FIN SA"]["dollars"], -100_000)
        self.assertEqual(n["Healthcare_MV"]["dollars"], -2_400_000)

    def test_verbatim_display_only_changes_line_breaks(self):
        raw = "MTM -1.5mm_x000D_-2.4mm Healthcare_MV"
        self.assertEqual(display_text(raw), "MTM -1.5mm\n-2.4mm Healthcare_MV")


# ---------------------------------------------------------- AI output ----
class TestAIReply(unittest.TestCase):
    def test_parse_and_fix(self):
        reply = "```\n**[S1]** Top contributors: A (C$ 5.0)\n[R01] Loss of C$ -209.0 from\ncarry.\n```"
        out = parse_ai_reply(reply)
        self.assertEqual(out["S1"], "A (C$ 5.0)")                 # duplicated label removed
        self.assertEqual(out["R01"], "Loss of C$ -209.0 from carry.")
        self.assertEqual(fix_number_format(out["R01"]), "Loss of (C$ 209.0) from carry.")
        self.assertEqual(fix_number_format("-C$ 1,612"), "(C$ 1,612.0)")
        self.assertEqual(fix_number_format("C$ 86"), "C$ 86.0")

    def test_json_reply(self):
        out = parse_ai_reply('{"summary": {"S1": "x"}, "rows": {"R02": "y"}}')
        self.assertEqual(out, {"S1": "x", "R02": "y"})


# -------------------------------------------------------- end to end ----
class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.facts, cls.tmp = run()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_meta(self):
        m = self.facts["meta"]
        self.assertEqual(m["desk"], "Spread Products")
        self.assertEqual(m["units"]["stored_as"], "dollars")
        self.assertEqual(m["units"]["basis"], "VERIFIED")
        self.assertEqual(m["report_date"], {"date": "2026-05-12", "basis": "VERIFIED",
                                            "note": "sheet header and file name agree"})

    def test_hierarchy_rollup(self):
        desk = self.facts["rows"][0]
        self.assertEqual(desk["business"], "Spread Products Total")
        self.assertEqual(len(desk["children_row_ids"]), 5)
        credit = row(self.facts, "Credit Total")
        self.assertEqual([c["name"] for c in credit["all_children"]],
                         ["Leveraged Credit Total", "Investment Grade Total", "Credit Derivatives Total"])
        self.assertEqual(credit["actual"]["display"], "(C$ 755.0)")

    def test_all_reconcile(self):
        bad = [(r["business"], c["check"]) for r in self.facts["rows"] for c in r["reconciliation"]
               if c["status"] != "PASS"]
        self.assertEqual(bad, [])

    def test_missing_commentary_total_rolled_up_and_confirmed(self):
        credit = row(self.facts, "Credit Total")
        self.assertEqual(credit["estimate"]["display"], "(C$ 717.0)")
        self.assertEqual(credit["estimate"]["basis"], "VERIFIED")   # confirmed by summary table
        self.assertIn("children", credit["estimate"]["source"])

    def test_cross_sheet_quirks(self):
        lf = row(self.facts, "Loan Financing")                       # numbers/label misaligned
        self.assertEqual(lf["estimate"]["display"], "C$ 210.0")
        self.assertIn("Total TLF", lf["analyst_comment"]["fragments"][0]["raw"])
        sf = row(self.facts, "Securitization Finance")               # comment-only rows below it
        frags = sf["analyst_comment"]["fragments"]
        self.assertEqual(len(frags), 2)
        self.assertEqual(frags[1]["basis"], "INFERRED")
        lce = row(self.facts, "Leveraged Credit EUR")                # 'Eur' on the other sheet
        self.assertEqual(lce["estimate"]["display"], "(C$ 178.0)")

    def test_comments_preserved_exactly(self):
        d = row(self.facts, "Distressed")
        self.assertEqual(d["analyst_comment"]["fragments"][0]["raw"], sample.COMMENTS["Distressed"])

    def test_drivers_ranked_by_absolute_value(self):
        d = row(self.facts, "Distressed")
        self.assertEqual(d["top_drivers"][0]["name"], "Portfolio Revaluation (MTM)")
        self.assertEqual(d["top_drivers"][0]["display"], "(C$ 1,600.0)")

    def test_summary_facts(self):
        s = self.facts["executive_summary_facts"]
        self.assertEqual(s["S1_top_positive_businesses"][0]["name"], "Securitization")
        self.assertEqual(s["S5_negative_lines"][0]["name"], "Distressed")

    def test_ai_input_fits_budget(self):
        parts = build_ai_inputs(self.facts)
        self.assertGreater(len(parts), 1)                      # rich input needs several parts
        for _, text in parts:
            self.assertLessEqual(len(text) // 4, config.AI_INPUT_TOKEN_BUDGET * 1.3)

    def test_every_row_in_exactly_one_part(self):
        parts = build_ai_inputs(self.facts)
        joined = "\n".join(t for _, t in parts)
        for r in self.facts["rows"]:
            self.assertEqual(joined.count("\n%s | " % r["row_id"]) + joined.startswith(r["row_id"] + " | "), 1)
        self.assertIn("DESK-LEVEL FACTS", parts[0][1])
        self.assertNotIn("DESK-LEVEL FACTS", parts[1][1])

    def test_full_analyst_comment_is_not_truncated(self):
        text = "\n".join(t for _, t in build_ai_inputs(self.facts))
        self.assertIn("-0.2MM RACKSPACE FIN LLC", text)          # last words of the long Distressed comment
        self.assertIn("ANALYST SAID", text)

    def test_parent_block_is_self_contained(self):
        text = "\n".join(t for _, t in build_ai_inputs(self.facts))
        block = text.split("R03 | Investment Grade Total")[1].split("\nR04 |")[0]
        for name in ("IG EUR", "IG CDA", "IG USA", "IG APAC"):
            self.assertIn(name + ": A ", block)                   # every child with A/E/V
        self.assertIn("PY who drove each driver", block)
        self.assertIn("children offset each other", block)        # % of a small net total suppressed

    def test_offset_split_matches_drivers(self):
        d = row(self.facts, "Distressed")
        sp = d["driver_split"]
        self.assertEqual([x["name"] for x in sp["losses"]][0], "Portfolio Revaluation (MTM)")
        self.assertTrue(sp["losses_total"]["display"].startswith("(C$ 1,6"))
        self.assertEqual(d["variance_vs_estimate"]["direction"], "below estimate")
        self.assertEqual(row(self.facts, "Spread Management Total")["variance_vs_estimate"]["direction"], "below estimate")

    def test_example_commentary_passes_figure_audit(self):
        reply = parse_ai_reply((ROOT / "prompts" / "example_commentary.txt").read_text(encoding="utf-8"))
        bad = [p for p in audit_ai_text(self.facts, reply) if "not in the Python facts" in p]
        self.assertEqual(bad, [])

    def test_ai_input_chunking(self):
        old = config.AI_INPUT_TOKEN_BUDGET
        config.AI_INPUT_TOKEN_BUDGET = 1200
        try:
            parts = build_ai_inputs(self.facts)
        finally:
            config.AI_INPUT_TOKEN_BUDGET = old
        self.assertGreater(len(parts), 1)
        self.assertIn("DESK-LEVEL FACTS", parts[0][1])
        all_ids = "".join(t for _, t in parts)
        for r in self.facts["rows"]:
            self.assertIn(r["row_id"] + " | ", all_ids)

    def test_audit_catches_invented_numbers(self):
        problems = audit_ai_text(self.facts, {"S1": "x", "R01": "Revenue of C$ 2,726.0 and C$ 123.0"})
        self.assertTrue(any("C$ 123.0" in p for p in problems))
        self.assertFalse(any("2,726.0" in p for p in problems))


# ---------------------------------------------------- broken workbooks ----
class TestBrokenWorkbooks(unittest.TestCase):
    def test_non_reconciling_total_is_flagged(self):
        def break_total(wb):
            wb["Spread Decmp"]["C11"] = wb["Spread Decmp"]["C11"].value + 50_000   # IG Total revenue
        facts, tmp = run(break_total)
        ig = row(facts, "Investment Grade Total")
        self.assertEqual(ig["reconciliation_status"], "FAIL")
        self.assertEqual(ig["confidence"], "LOW")
        self.assertTrue(any(c["check"] == "children_sum_vs_parent:revenue" and c["status"] == "FAIL"
                            for c in ig["reconciliation"]))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_text_in_numeric_column(self):
        def text_cell(wb):
            wb["Spread Decmp"]["H10"] = "n/a"           # IG APAC carry
        facts, tmp = run(text_cell)
        self.assertTrue(any("n/a" in i["message"] for i in facts["issues"]))
        self.assertNotEqual(row(facts, "IG APAC")["reconciliation_status"], "PASS")
        shutil.rmtree(tmp, ignore_errors=True)

    def test_values_stored_in_thousands(self):
        def to_thousands(wb):
            for name in ("Spread Decmp", "Spread Commentary"):
                for r in wb[name].iter_rows():
                    for c in r:
                        if isinstance(c.value, (int, float)):
                            c.value = c.value / 1000.0
                            c.number_format = "#,##0;(#,##0)"
        facts, tmp = run(to_thousands)
        self.assertEqual(facts["meta"]["units"]["stored_as"], "thousands")
        self.assertEqual(row(facts, "Distressed")["actual"]["display"], "(C$ 1,613.0)")
        shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_sheet(self):
        def drop(wb):
            del wb["Spread Commentary"]
        with self.assertRaises(WorkbookFormatError):
            run(drop)

    def test_missing_column(self):
        def rename(wb):
            wb["Spread Decmp"]["H4"] = "Something else"
        with self.assertRaises(WorkbookFormatError) as ctx:
            run(rename)
        self.assertIn("carry", str(ctx.exception))

    def test_not_an_excel_file(self):
        tmp = Path(tempfile.mkdtemp())
        bad = tmp / "bad.xlsx"
        bad.write_text("not a workbook")
        with self.assertRaises(WorkbookFormatError):
            preprocess(bad, tmp / "out")
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
