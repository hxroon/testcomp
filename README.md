# testcomp

# Decomp Commentary Agent: Python preprocessing

**Python works out what happened numerically. The AI explains it in words.**

```
Excel workbook ──► python main.py prepare ──► ai_input.txt ──► internal agent (Haiku)
                                         │                           │
                                         ▼                           ▼
                                   facts.json  ◄── python main.py render ◄── ai_response.txt
                                         │
                                         ▼
                                    report.html  (6 columns, RBC style)
```

| Step | Who | What |
|---|---|---|
| 1 | Python | Reads both sheets, builds the hierarchy, reconciles, ranks drivers, extracts named clients, writes `ai_input.txt` |
| 2 | Agent | Writes only the AI Agent Commentary per row and the 5 summary lines |
| 3 | Python | Builds the HTML: numbers, analyst comments (verbatim), colours; checks every figure the AI wrote |

The AI never sees the raw workbook, never formats numbers and never builds HTML. That is what cuts tokens and removes the calculation, hierarchy and formatting errors.

---

## 1. One-time setup (VS Code, Windows)

1. Copy the `decomp_agent` folder somewhere on your PC, e.g. `C:\Users\<you>\decomp_agent`.
2. In VS Code: **File → Open Folder…** → choose `decomp_agent`.
3. Open a terminal: **Terminal → New Terminal**.
4. Create a virtual environment (a private Python just for this project):
   ```
   python -m venv .venv
   .venv\Scripts\activate
   ```
   The prompt should now start with `(.venv)`. If PowerShell blocks the script, run
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use the Command Prompt terminal instead.
5. Install the one dependency:
   ```
   pip install -r requirements.txt
   ```
   Corporate Artifactory (ask your team for the real URL; do not guess it):
   ```
   pip install -r requirements.txt --index-url <INTERNAL_PYPI_URL>
   ```
6. In VS Code, press `Ctrl+Shift+P` → **Python: Select Interpreter** → pick the one in `.venv`.
7. Check everything works:
   ```
   python -m unittest discover -s tests
   ```
   Expect `OK` (36 tests).

Only **openpyxl** is required. pandas is not used: the workbook is small, and openpyxl gives
direct access to merged cells, number formats and hidden rows, which this layout needs.

## 2. Daily run

1. Put the workbook in the `input` folder (create it), e.g. `input\Daily_SpreadDecompTEReport_20260512.xlsx`.
2. Prepare:
   ```
   python main.py prepare "input\Daily_SpreadDecompTEReport_20260512.xlsx"
   ```
   This creates `output\Daily_SpreadDecompTEReport_20260512\`.
3. Open `check_report.txt` and spot-check 3-4 numbers against Excel (desk total, one parent, one line).
4. Open the agent, attach (or paste) `ai_input_part1.txt`, and send *"Write the commentary for the attached facts file."*
   The input is split into 2-4 parts (whole businesses per part) so the agent has room for long answers.
   Send each part in a **new chat/message**, in order. Part 1 returns the Executive Summary plus its rows.
5. Copy the agent's reply into a new file `ai_response.txt` in the same output folder
   (`ai_response_part2.txt`, … for the other parts).
6. Render:
   ```
   python main.py render "output\Daily_SpreadDecompTEReport_20260512"
   ```
7. Open `report.html`. Read `ai_check.txt` (also shown in the report's **Data checks** box) for
   any figure the AI wrote that Python cannot find in the facts.

**Try it first on the sample:** `python main.py prepare "sample_data\Daily_SpreadDecompTEReport_20260512.xlsx"`.
The sample is synthetic: it copies your layout from the screenshots, with approximate numbers.

## 3. Updating the agent

Replace the agent's Custom instructions with the text between the START/END lines in
`prompts/agent_instructions.txt` (v9). Unlike v7.1 it asks for *reasoning* (result vs Estimate,
main driver, who led, what offset, analyst colour) instead of fill-in-the-blank sentences, and
it allows the AI to connect and compare the verified numbers but not to invent causes.
`prompts/example_commentary.txt` shows the target quality; every figure in it is checked
against the facts by the tests.

## 4. Output files

| File | Purpose |
|---|---|
| `check_report.txt` | Human check: hierarchy tree, Actual/Estimate/Variance, reconciliation exceptions, flags |
| `ai_input_partN.txt` (or `ai_input.txt` if small) | Facts for the agent: numbers, offsets, who led each driver, children, FULL analyst comments (about 2K tokens per part) |
| `facts.json` | Everything: all values in dollars and display form, sources, VERIFIED/INFERRED/UNVERIFIED labels, all checks |
| `report_draft.html` | Report with numbers and analyst comments, AI columns marked pending |
| `report.html` | Final report after `render` |
| `ai_check.txt` | Figures the AI wrote that are not in the facts, plus missing rows |
| `run.log` | Detailed log for troubleshooting |

### How to read facts.json

Each row has `actual`, `estimate` and `variance`, each with a `basis`:

- **VERIFIED**: read directly from a workbook cell (or a roll-up confirmed by a summary table).
- **INFERRED**: derived by Python, e.g. the Credit estimate (no Credit Total row on the
  Commentary sheet), hierarchy from layout, or client names read from comment text.
- **UNVERIFIED**: missing or not confirmable.

`reconciliation` lists every check: drivers→TOTAL, TOTAL→Revenues, Sub-Total→NTA+MTM,
children→parent, Commentary Actual→Decmp, Variance→A−E, and both summary tables→detail.
`confidence` is HIGH, MEDIUM or LOW.

In the AI input, `PY` = calculated by Python, `ANALYST SAID` = the analyst's words (unverified), and a `~` before a figure means "rolled up by Python" and `?` means "not available".

## 5. How the workbook is read (assumptions, all in `decomp/config.py`)

- **Sheets** are found by name; `Spread CoverPage` is ignored.
- **Columns** are found by header text, not letter (e.g. "New Trading", "Carry", "Actual P&L").
  Sub-Total is recognised and *excluded* from driver ranking so NTA+MTM is not counted twice.
- **Units:** cells hold dollars with a format that displays thousands. This is detected
  automatically from the number format, and the run stops with an explanation if it looks wrong.
- **Hierarchy** comes from layout: an UPPERCASE/section header row opens a group; `<Name> Total`
  closes it. `Credit Derivatives Total` has no header, so its child is inferred from the rows
  directly above (flagged). `Spread Products Total` ends the main table; the roll-up table
  below it is used only as a cross-check.
- **Commentary rows are matched by label**, not row number. The parser handles different row
  positions, case differences (`Eur`/`EUR`), numbers and label on different rows, comment-only
  rows (e.g. Securitization CDA → attached to Securitization Finance, flagged), and the missing
  Credit Total.
- **Analyst comments** are kept byte-for-byte in `facts.json`. In the HTML only line breaks are
  rendered (including Excel's `_x000D_`).
- **Display** is house style: `C$ 1,234.0`, negatives `(C$ 1,234.0)`, variances `+C$ 27.0`.
- **Tolerance** is C$1K or 0.1%, whichever is larger (`RECON_ABS_TOL`, `RECON_PCT_TOL`).

## 6. Troubleshooting

| Message | Fix |
|---|---|
| `python is not recognized` | Install Python 3.9+ from your software centre; tick "Add to PATH". |
| `No module named openpyxl` | Activate the venv (`.venv\Scripts\activate`), then `pip install -r requirements.txt`. |
| `Could not open … Is it open/locked` | Close the file in Excel, or copy it out of Outlook/OneDrive first. |
| `Old .xls format is not supported` | Save As `.xlsx`. |
| `Required sheet … not found` | Sheet renamed: add the new name to `DECOMP_SHEET_NAMES` / `COMMENTARY_SHEET_NAMES`. |
| `could not find column(s) [...]` | Header text changed: the message lists the headers seen; update `*_COLUMN_RULES`. |
| `formulas with no saved result` | Open in Excel, let it calculate, Save, run again. |
| `did not match any Decmp business` | A name differs between sheets: add it to `LABEL_ALIASES`. |
| Agent cuts off its answer | Lower `AI_INPUT_TOKEN_BUDGET` (default 2200, try 1600) so each part is smaller. |
| Rows show "(AI commentary pending)" | The reply was missing those `[Rnn]` lines; see `ai_check.txt`. |

## 7. Project layout

```
decomp_agent/
  main.py                    command line: prepare / render
  requirements.txt
  decomp/
    config.py                ALL workbook-specific settings
    workbook_reader.py       sheets, header/column detection, units, raw rows
    hierarchy.py             parent/child tree from header + Total rows
    commentary.py            Commentary sheet parsing and label matching
    comments.py              verbatim comments, mm/K amounts, client/book names
    calculations.py          reconciliation, ranking, contributions, confidence
    output_builder.py        facts.json + ai_input.txt (with chunking)
    html_builder.py          AI reply parsing, figure audit, RBC HTML
    pipeline.py              wiring
    utils.py                 formatting, number cleaning, tolerance checks
  prompts/agent_instructions.txt   new agent prompt
  tests/                     36 tests + synthetic workbook builder
  sample_data/               synthetic workbook + example outputs
```
