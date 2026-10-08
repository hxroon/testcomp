"""
Decomp Commentary Agent - command line entry point.

STEP 1  python main.py prepare "input/Daily_SpreadDecompTEReport_20260512.xlsx"
        -> output/<file name>/  facts.json, ai_input*.txt, check_report.txt, report_draft.html

STEP 2  Give ai_input.txt (or each ai_input_partN.txt) to the agent. Save its reply
        as ai_response.txt (ai_response_part2.txt, ...) in the same output folder.

STEP 3  python main.py render "output/Daily_SpreadDecompTEReport_20260512"
        -> report.html (final) and ai_check.txt (figures the AI wrote that Python cannot confirm)
"""
import argparse
import logging
import sys
from pathlib import Path

from decomp.pipeline import preprocess, render
from decomp.utils import WorkbookFormatError


def setup_logging(out_dir, verbose):
    out_dir.mkdir(parents=True, exist_ok=True)
    handlers = [logging.StreamHandler(sys.stdout),
                logging.FileHandler(out_dir / "run.log", mode="w", encoding="utf-8")]
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(levelname)-7s %(message)s", handlers=handlers, force=True)


def main(argv=None):
    p = argparse.ArgumentParser(description="P&L decomposition preprocessing for the commentary agent")
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("prepare", help="read the workbook and build facts + AI input")
    a.add_argument("workbook")
    a.add_argument("--out", default="output", help="parent output folder (default: output)")
    a.add_argument("-v", "--verbose", action="store_true")
    b = sub.add_parser("render", help="merge the AI reply into the final HTML report")
    b.add_argument("folder", help="the output folder created by 'prepare'")
    b.add_argument("--ai", nargs="*", help="AI reply file(s); default: ai_response*.txt in the folder")
    b.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    try:
        if args.command == "prepare":
            out_dir = Path(args.out) / Path(args.workbook).stem
            setup_logging(out_dir, args.verbose)
            facts, inputs = preprocess(args.workbook, out_dir)
            fails = sum(1 for r in facts["rows"] if r["reconciliation_status"] == "FAIL")
            print("\nDone. %d rows processed, %d with reconciliation FAIL." % (len(facts["rows"]), fails))
            print("Output folder: %s" % out_dir.resolve())
            print("  1. Open check_report.txt and compare a few numbers with Excel.")
            print("  2. Give the agent: %s" % ", ".join(inputs))
            print("  3. Save the agent's reply as ai_response.txt%s in that folder, then run:" %
                  (" (ai_response_part2.txt, ...)" if len(inputs) > 1 else ""))
            print('     python main.py render "%s"' % out_dir)
        else:
            out_dir = Path(args.folder)
            setup_logging(out_dir, args.verbose)
            html_path, problems = render(out_dir, args.ai)
            print("\nReport written: %s" % html_path.resolve())
            if problems:
                print("%d item(s) to review in ai_check.txt" % len(problems))
        return 0
    except WorkbookFormatError as exc:
        logging.getLogger("main").error(str(exc))
        print("\nSTOPPED: %s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
