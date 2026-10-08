"""
CONFIGURATION - the only file you should normally need to edit.

Everything workbook-specific (sheet names, header keywords, tolerances,
display wording) lives here so the rest of the code stays generic.
Search for "CONFIRM" to find the assumptions worth double-checking.
"""

# --------------------------------------------------------------------------
# 1. Sheets
# --------------------------------------------------------------------------
# Matched case-insensitively, ignoring extra spaces. First match wins.
DECOMP_SHEET_NAMES = ["Spread Decmp", "Spread Decomp"]
COMMENTARY_SHEET_NAMES = ["Spread Commentary"]
IGNORED_SHEET_NAMES = ["Spread CoverPage"]

# --------------------------------------------------------------------------
# 2. Column detection (by header text, never by column letter)
# --------------------------------------------------------------------------
# A column's header text = all text in that column inside the header block
# (handles headers split over two rows / merged cells), lower-cased.
# Rules are tried IN ORDER and each column can be claimed only once. That is
# why "sub-total" is matched before "new trading" (its header mentions both)
# and "origination" before "other".
#   "contains" -> header contains any of the phrases
#   "equals"   -> header equals one of the phrases
DECOMP_COLUMN_RULES = [
    ("subtotal", "contains", ["sub-total", "subtotal", "sub total"]),
    ("revenue", "contains", ["revenue"]),
    ("nta", "contains", ["new trading"]),
    ("reval", "contains", ["portfolio reval", "revaluation"]),
    ("orig", "contains", ["origination"]),
    ("carry", "contains", ["carry", "theta"]),
    ("other", "equals", ["other"]),
    ("total", "equals", ["total"]),
]
DECOMP_REQUIRED = ["revenue", "nta", "reval", "orig", "carry", "total"]
DECOMP_ANCHOR = "new trading"            # text that identifies the header block

COMMENTARY_COLUMN_RULES = [
    ("decomp_comment", "contains", ["decomp commentary"]),
    ("ave_comment", "contains", ["variance commentary"]),
    ("actual", "contains", ["actual"]),
    ("estimate", "contains", ["estimate"]),
    ("variance", "contains", ["variance"]),
]
COMMENTARY_REQUIRED = ["actual", "estimate", "variance", "decomp_comment"]
COMMENTARY_ANCHOR = "actual p&l"
COMMENT_KEYS = ["decomp_comment", "ave_comment"]   # text columns, not numbers

# Additive decomposition drivers (they should sum to "total").
# "subtotal" is NOT a driver: it is NTA + Reval and would double count.
DRIVER_KEYS = ["nta", "reval", "orig", "carry", "other"]
DRIVER_NAMES = {
    "nta": "New Trading Activity",
    "reval": "Portfolio Revaluation (MTM)",
    "orig": "Origination Fees/Commissions",
    "carry": "Carry/Theta",
    "other": "Other",
}
DRIVER_SHORT = {"nta": "NTA", "reval": "MTM", "orig": "Fees",
                "carry": "Carry", "other": "Other"}

# --------------------------------------------------------------------------
# 3. Units  (CONFIRM)
# --------------------------------------------------------------------------
# "auto"      -> detect from number formats and magnitudes (recommended)
# "dollars"   -> cells hold whole dollars (244000 displayed as 244)
# "thousands" -> cells already hold thousands (244 means 244,000)
UNITS_MODE = "auto"

# --------------------------------------------------------------------------
# 4. Row classification
# --------------------------------------------------------------------------
TOTAL_SUFFIX_REGEX = r"\s+total\s*$"      # "Credit Total", "Investment Grade Total"
SKIP_LABEL_REGEXES = [                    # metadata rows, never business lines
    r"^daily\s*:", r"^report check", r"^actual p&l vs te", r"^\([a-j]\)",
    r"variance drivers", r"^c\$\s*\(1,000s\)",
]
# Map alternate spellings between sheets onto one name (normalised text:
# lower case, single spaces, underscores -> spaces).
# Example: {"leveraged credit europe": "leveraged credit eur"}
LABEL_ALIASES = {}

# --------------------------------------------------------------------------
# 5. Reconciliation tolerances (DOLLARS)  (CONFIRM)
# --------------------------------------------------------------------------
# PASS when |difference| <= max(ABS_TOL, PCT_TOL * |reference|);
# WARN up to WARN_MULTIPLIER x tolerance; FAIL beyond that.
RECON_ABS_TOL = 1_000            # C$1K
RECON_PCT_TOL = 0.001            # 0.1%
RECON_WARN_MULTIPLIER = 5
# Below this absolute size a total is treated as zero for % contributions.
ZERO_THRESHOLD = 500             # C$0.5K

# --------------------------------------------------------------------------
# 6. Ranking / AI input size
# --------------------------------------------------------------------------
TOP_N_CHILDREN = 3
TOP_N_DRIVERS = 3
TOP_N_NAMED_ITEMS = 4            # named clients/books passed per row
TOP_N_SUMMARY_FLOWS = 6          # named flows offered for exec summary section 4
INCLUDE_COMMENT_TEXT_IN_AI_INPUT = True
MAX_COMMENT_CHARS_IN_AI_INPUT = 0     # 0 = full analyst comments (no cut)
# The internal agent runs Haiku 4.5 with an 8K context. Each AI input part is
# kept below this budget (1 token ~ 4 characters) to leave room for the
# instructions and the answer. Lower it if the agent truncates.
AI_INPUT_TOKEN_BUDGET = 2_200

# --------------------------------------------------------------------------
# 7. Display
# --------------------------------------------------------------------------
CURRENCY = "C$"
DISPLAY_DECIMALS_SUFFIX = ".0"   # house style: whole thousands shown as 1,234.0
NO_COMMENT_TEXT = "(no comment)"
AI_PENDING_TEXT = "(AI commentary pending)"
REPORT_TITLE = "P&L Commentary Report"
REPORT_SUBTITLE = "Global Product Control \u00b7 Daily report \u00b7 Internal use only"
AGENT_VERSION = "P&L Commentary Agent v8.0 (Python facts + AI narrative)"
SUMMARY_SECTIONS = [
    ("S1", "Top contributors"),
    ("S2", "Dominant driver"),
    ("S3", "Secondary driver"),
    ("S4", "Notable named flow"),
    ("S5", "Negative actual"),
]

# --------------------------------------------------------------------------
# 8. Named-driver extraction from analyst comments
# --------------------------------------------------------------------------
ENTITY_SUFFIXES = ["LLC", "INC", "SA", "LTD", "CORP", "PLC", "LP", "AG", "NV",
                   "BV", "GMBH", "LLP"]
# Desk/book/strategy phrases worth surfacing when they appear in a comment.
KNOWN_DRIVER_TERMS = ["Hedging Pod", "Commercial Paper", "Front End", "Hybrid",
                      "CDX hedge book", "US Conduit Finance", "Par loan",
                      "Upfront fee", "DCM fee", "Corporate", "Financials"]
