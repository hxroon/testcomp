"""
Build a SYNTHETIC workbook that copies the layout of
Daily_SpreadDecompTEReport_20260512.xlsx as seen in the screenshots:

* 'Spread CoverPage' (just 'RBC'), 'Spread Decmp', 'Spread Commentary'
* values hardcoded in DOLLARS with a thousands display format
* different row positions on the two sheets, no 'Credit Total' and no
  'INVESTMENT GRADE' header on Commentary, a numbers/label misaligned row
  (Loan Financing), comment-only rows (Securitization CDA, a second
  Securitization Finance), summary tables and the (A)-(J) legend

Numbers are approximations of the screenshot; this file is for testing only.
Run directly to (re)create sample_data/Daily_SpreadDecompTEReport_20260512.xlsx
"""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

FMT = '#,##0,;(#,##0,);"-"'
NAVY = PatternFill("solid", fgColor="0B1D3A")
GREY = PatternFill("solid", fgColor="D9D9D9")
WHITE_BOLD = Font(name="Calibri", bold=True, color="FFFFFF")
BOLD = Font(name="Calibri", bold=True)

# leaf: (label, NTA, MTM, Fees, Carry, Other) in thousands
STRUCTURE = [
    ("Credit", [
        ("INVESTMENT GRADE", "Investment Grade Total", [
            ("IG CDA", -328.4, -3.2, 22.1, 42.6, 0.0),
            ("IG USA", 193.2, -442.3, -9.1, -3.4, -0.3),
            ("IG EUR", 136.0, 511.2, 85.3, -83.1, -0.2),
            ("IG APAC", 0.0, 6.1, 0.0, -5.2, 0.0)]),
        ("LEVERAGED CREDIT", "Leveraged Credit Total", [
            ("High Yield", 19.2, 275.3, -14.2, 1.1, 0.2),
            ("Loans", 209.1, 304.2, 0.3, -6.2, 0.0),
            ("Distressed", 8.2, -1600.1, -22.9, 2.2, -0.2),
            ("Leveraged Credit EUR", 15.1, -163.2, 2.1, 90.2, -0.1)]),
        (None, "Credit Derivatives Total", [
            ("Credit Derivatives", 159.3, -48.1, -0.3, -107.1, 0.0)]),
    ], "Credit Total"),
    ("ALTERNATIVE FINANCE PRODUCTS", [
        ("CLO", 180.2, -1.1, -2.1, 65.2, 0.2),
        ("Loan Financing", 0.0, 4.1, 4.2, 229.1, -0.2),
        ("Structured Opportunities", 0.0, 1.1, 0.0, 50.1, -0.2),
        ("401(K)", 0.0, 107.2, 0.0, 0.0, 0.0),
        ("Alternative Finance Management", 0.0, 1.1, 0.0, 28.1, -0.1)], "Alternative Finance Products Total"),
    ("SECURITIZATION", [
        ("ABS", 4.1, 2.2, 1023.1, 20.2, 0.0),
        ("Cmbs_rmbs Secondary", 29.2, 1.1, 0.0, -0.3, 0.1),
        ("Securitization Finance", 0.0, 36.2, 14.1, 1155.2, -0.1)], "Securitization Total"),
    ("MUNI PRODUCTS", [
        ("Muni Portfolio Strategy", -0.3, -12.2, 4.1, 31.1, 0.1),
        ("Muni Sales & Trading USA", 528.3, -494.1, 186.2, -13.1, 0.1)], "Muni Products Total"),
    ("SPREAD MANAGEMENT", [], "Spread Management Total", (0.0, 298.2, 0.0, -0.3, 0.1)),
]

ESTIMATES = {"IG CDA": -244, "IG USA": -235, "IG EUR": 762, "IG APAC": 2, "High Yield": 294,
             "Loans": 480, "Distressed": -1579, "Leveraged Credit EUR": -178,
             "Credit Derivatives": -19, "CLO": 263, "Loan Financing": 210,
             "Structured Opportunities": 55, "401(K)": 106, "Alternative Finance Management": 27,
             "ABS": 1072, "Cmbs_rmbs Secondary": 25, "Securitization Finance": 1228,
             "Muni Portfolio Strategy": 20, "Muni Sales & Trading USA": 181,
             "Spread Management Total": 300}

COMMENTS = {
    "IG CDA": "Credit CDA (0.3)mm:\nNTA (0.3)mm: Corporate(0.3)mm\nMTM (0.1)mm: Interest Rate (PV01/KRD)(0.1)mm",
    "IG USA": "Investment Grade (0.3mm)\nNew Trading Activity +0.2mm: primarily driven by Hedging Pod: +0.2 mm.\nMTM (0.4mm): primarily driven by Front End: (0.4 mm).",
    "IG EUR": "Investment Grade: +0.6mm\nNew Trading Activity +0.2mm: primarily driven by Hybrid:+0.1mm\nMTM +0.5mm: cs01  +0.6mm, primarily driven by +0.2mm on Financials, +0.4mm on EUR Corporate pv01: -0.1mm",
    "High Yield": "High Yield +0.3mm\nMTM +0.2mm: primarily driven by +0.1mm Energy_DS and +0.1mm CDX hedge book",
    "Loans": 'Par loan: +0.5MM\nMTM: +0.3MM "AP CORE HLDGS II LLC" the rest spread across\nNTA: +0.2MM spread across',
    "Distressed": "Distressed -1.6mm\nMTM -1.5mm_x000D_-2.4mm Healthcare_MV, +0.4mm YDST-MV and +0.8mm RDSTUNLD_x000D_-0.1MM MALLINCKRODT INTL FIN SA, -0.2MM RACKSPACE FIN LLC",
    "CLO": "Total CLO +7K: Fee Accrual +7K, FX Reval 0K.",
    "Loan Financing": "Total TLF +228K: Fee Accrual +229K, JV split to Corp Banking and GIB -5K, FX reval 4K.",
}


def _k(x):
    return round(x * 1000.0, 2)


def compute():
    """Return ordered decmp rows: (kind, label, values dict in dollars)."""
    rows = []

    def leaf_vals(t):
        nta, mtm, fees, carry, other = (_k(v) for v in t)
        total = nta + mtm + fees + carry + other
        return {"revenue": total, "nta": nta, "reval": mtm, "subtotal": nta + mtm,
                "orig": fees, "carry": carry, "other": other, "total": total}

    def add(a, b):
        return {k: a.get(k, 0) + b[k] for k in b}

    desk = {}
    for block in STRUCTURE:
        if block[0] == "Credit":
            rows.append(("header", "Credit", None))
            credit = {}
            for header, total_label, leaves in block[1]:
                if header:
                    rows.append(("header", header, None))
                grp = {}
                for leaf in leaves:
                    v = leaf_vals(leaf[1:])
                    rows.append(("leaf", leaf[0], v))
                    grp = add(grp, v)
                rows.append(("total", total_label, grp))
                credit = add(credit, grp)
            rows.append(("total", block[2], credit))
            desk = add(desk, credit)
        else:
            rows.append(("header", block[0], None))
            grp = {}
            for leaf in block[1]:
                v = leaf_vals(leaf[1:])
                rows.append(("leaf", leaf[0], v))
                grp = add(grp, v)
            if len(block) > 3:   # total-only business
                grp = leaf_vals(block[3])
            rows.append(("total", block[2], grp))
            desk = add(desk, grp)
    rows.append(("blank", "", None))
    rows.append(("grand", "Spread Products Total", desk))
    return rows


def _header(ws, row, kind, title="Spread Products", date="Daily: May 12, 2026"):
    ws.cell(row=row, column=2, value=title).font = WHITE_BOLD
    ws.cell(row=row + 1, column=2, value=date).font = WHITE_BOLD
    if kind == "decmp":
        ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=10)
        if row > 10:
            ws.cell(row=row, column=4, value="Decomposition Parameter")
        heads = ["Revenues", "New Trading Activity", "Portfolio Revaluation",
                 "Sub-Total (New Trading Activity + Portfolio Reval)",
                 "Origination Fees Commissions Other Fee (Inc/Exp)", "Carry/Theta", "Other", "TOTAL"]
        ws.cell(row=row, column=3, value="Revenues")
        ws.cell(row=row + 1, column=3, value="C$ (1,000s)")
        for i, h in enumerate(heads[1:], start=4):
            ws.cell(row=row + 1, column=i, value=h)
        last = 10
    else:
        ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=5)
        ws.cell(row=row, column=3, value="C$ (1,000s)")
        ws.cell(row=row + 1, column=3, value="Actual P&L\n(A)")
        ws.cell(row=row + 1, column=4, value="Trader Estimate (E)")
        ws.cell(row=row + 1, column=5, value="Variance\n(A vs E)")
        if row < 10:
            ws.merge_cells(start_row=row, start_column=6, end_row=row + 1, end_column=6)
            ws.cell(row=row, column=6, value="Decomp Commentary")
            ws.merge_cells(start_row=row, start_column=7, end_row=row + 1, end_column=7)
            ws.cell(row=row, column=7, value="A vs E Variance Commentary (> 1k)")
        last = 7
    for r in (row, row + 1):
        for c in range(2, last + 1):
            ws.cell(row=r, column=c).fill = NAVY
            ws.cell(row=r, column=c).font = WHITE_BOLD
            ws.cell(row=r, column=c).alignment = Alignment(wrap_text=True)


def _put_decmp(ws, r, label, v, bold=False):
    ws.cell(row=r, column=2, value=label)
    if bold:
        for c in range(2, 11):
            ws.cell(row=r, column=c).fill = GREY
            ws.cell(row=r, column=c).font = BOLD
    if v is None:
        return
    for c, key in enumerate(["revenue", "nta", "reval", "subtotal", "orig", "carry", "other", "total"], 3):
        cell = ws.cell(row=r, column=c, value=round(v[key], 2))
        cell.number_format = FMT


def build(path, mutate=None):
    """Write the sample workbook. `mutate(wb)` lets tests break things on purpose."""
    rows = compute()
    vals = {lab: v for kind, lab, v in rows if v is not None}
    wb = Workbook()
    cover = wb.active
    cover.title = "Spread CoverPage"
    cover["B2"] = "RBC"

    # ---------------- Decmp
    ws = wb.create_sheet("Spread Decmp")
    ws.column_dimensions["B"].width = 34
    _header(ws, 3, "decmp")
    r = 5
    for kind, label, v in rows:
        _put_decmp(ws, r, label, v, bold=kind in ("total", "grand"))
        r += 1
    _header(ws, 45, "decmp")
    for i, lab in enumerate(["Credit", "Alternative Finance Products", "Securitization",
                             "Muni Products", "Spread Management", "Spread Products"]):
        src = "Spread Products Total" if lab == "Spread Products" else lab + " Total"
        _put_decmp(ws, 47 + i, lab, vals[src], bold=lab == "Spread Products")

    # ---------------- Commentary
    wc = wb.create_sheet("Spread Commentary")
    wc.column_dimensions["B"].width = 34
    wc.column_dimensions["F"].width = 70
    _header(wc, 3, "comm")

    est = dict((k, v * 1000.0) for k, v in ESTIMATES.items())
    est["Investment Grade Total"] = sum(est[x] for x in ["IG CDA", "IG USA", "IG EUR", "IG APAC"])
    est["Leveraged Credit Total"] = sum(est[x] for x in ["High Yield", "Loans", "Distressed", "Leveraged Credit EUR"])
    est["Credit Derivatives Total"] = est["Credit Derivatives"]
    est["Alternative Finance Products Total"] = sum(est[x] for x in ["CLO", "Loan Financing", "Structured Opportunities", "401(K)", "Alternative Finance Management"])
    est["Securitization Total"] = sum(est[x] for x in ["ABS", "Cmbs_rmbs Secondary", "Securitization Finance"])
    est["Muni Products Total"] = est["Muni Portfolio Strategy"] + est["Muni Sales & Trading USA"]
    est["Credit Total"] = est["Investment Grade Total"] + est["Leveraged Credit Total"] + est["Credit Derivatives Total"]
    est["Spread Products Total"] = sum(est[x] for x in ["Credit Total", "Alternative Finance Products Total",
                                                         "Securitization Total", "Muni Products Total",
                                                         "Spread Management Total"])

    def put(row, label, src=None, comment=None, label_text=None, numbers=True, bold=False):
        if label_text is not False:
            wc.cell(row=row, column=2, value=label_text or label)
        if numbers and src:
            a, e = vals[src]["revenue"], est[src]
            for c, x in ((3, a), (4, e), (5, a - e)):
                cell = wc.cell(row=row, column=c, value=round(x, 2))
                cell.number_format = FMT
        if comment:
            wc.cell(row=row, column=6, value=comment).alignment = Alignment(wrap_text=True, vertical="top")
        if bold:
            for c in range(2, 8):
                wc.cell(row=row, column=c).font = BOLD
                wc.cell(row=row, column=c).fill = GREY

    put(5, "Credit", numbers=False)
    for i, lab in enumerate(["IG CDA", "IG USA", "IG EUR", "IG APAC"]):
        put(6 + i, lab, lab, COMMENTS.get(lab))
    put(10, "Investment Grade Total", "Investment Grade Total", bold=True)
    put(11, "LEVERAGED CREDIT", numbers=False)
    put(12, "High Yield", "High Yield", COMMENTS["High Yield"])
    put(13, "Loans", "Loans", COMMENTS["Loans"])
    put(15, "Distressed", "Distressed", COMMENTS["Distressed"])
    put(19, "Leveraged Credit EUR", "Leveraged Credit EUR", label_text="Leveraged Credit Eur")
    put(20, "Leveraged Credit Total", "Leveraged Credit Total", bold=True)
    put(21, "Credit Derivatives", "Credit Derivatives")
    put(22, "Credit Derivatives Total", "Credit Derivatives Total", bold=True)
    put(23, "ALTERNATIVE FINANCE PRODUCTS", numbers=False)
    put(24, "CLO", "CLO", COMMENTS["CLO"])
    put(25, "Loan Financing", "Loan Financing", COMMENTS["Loan Financing"], label_text=False)  # numbers, no label
    put(26, "Loan Financing", numbers=False)                                                   # label, no numbers
    put(28, "Structured Opportunities", "Structured Opportunities")
    put(29, "401(K)", "401(K)")
    put(34, "Alternative Finance Management", "Alternative Finance Management")
    put(39, "Alternative Finance Products Total", "Alternative Finance Products Total", bold=True)
    put(40, "SECURITIZATION", numbers=False)
    put(41, "ABS", "ABS")
    put(43, "Cmbs_rmbs Secondary", "Cmbs_rmbs Secondary")
    put(44, "Securitization Finance", "Securitization Finance")
    put(46, "Securitization CDA", numbers=False, comment="Carry: +0.2mm 1-Days Accrual")
    put(47, "Securitization Finance", numbers=False,
        comment="Total US Conduit Finance +767K: Fee accrual +725K, FX reval 42K.")
    put(49, "Securitization Total", "Securitization Total", bold=True)
    put(50, "MUNI PRODUCTS", numbers=False)
    put(51, "Muni Portfolio Strategy", "Muni Portfolio Strategy")
    put(52, "Muni Sales & Trading USA", "Muni Sales & Trading USA")
    put(53, "Muni Products Total", "Muni Products Total", bold=True)
    put(54, "SPREAD MANAGEMENT", numbers=False)
    put(55, "Spread Management Total", "Spread Management Total", bold=True)
    put(61, "Spread Products Total", "Spread Products Total", bold=True)

    _header(wc, 63, "comm")
    for i, lab in enumerate(["Credit", "Alternative Finance Products", "Securitization",
                             "Muni Products", "Spread Management", "Spread Products"]):
        src = "Spread Products Total" if lab == "Spread Products" else lab + " Total"
        put(65 + i, lab, src, label_text=lab, bold=lab == "Spread Products")
    wc.merge_cells("F65:F69")
    wc["F65"] = "No material drivers"
    wc["B72"] = "Actual P&L vs TE Variance Drivers:"
    legend = ["(A) No Estimate: Entire desk or substantial part was not submitted",
              "(B) Submission Error: Incomplete or partial submissions",
              "(C) Difference in Curve/Price Snaps", "(D) 1st/2nd Order Effects: MTM risk related",
              "(E) Carry/Theta/CFLA: Carry/funding events", "(F) Late Trades/Adjustments",
              "(G) Intradesk Transfer", "(H) Reserves/Adjustments", "(I) Model/System Diff",
              "(J) Other: Example - Rates Management CAD"]
    for i, t in enumerate(legend):
        wc.cell(row=73 + i, column=2, value=t)

    if mutate:
        mutate(wb)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "sample_data" / "Daily_SpreadDecompTEReport_20260512.xlsx"
    build(out)
    print("Sample workbook written to", out)
