"""Copy generated result files into documents between markers, so no number is ever retyped.

    python scripts/embed_results.py [doc ...]        (default: README.md docs/TECHNICAL_REPORT.md docs/COOL.md)

Markers:  <!-- EMBED:eval/results/summary.md -->  ...  <!-- /EMBED -->
Image links inside embedded files are rewritten relative to the document that embeds them.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DOCS = ["README.md", os.path.join("docs", "TECHNICAL_REPORT.md"), os.path.join("docs", "COOL.md")]
PAT = re.compile(r"(<!-- EMBED:(?P<path>[^ ]+) -->)(.*?)(<!-- /EMBED -->)", re.S)
NL = "\n"


def render(m, doc_dir):
    src = os.path.join(ROOT, m.group("path"))
    if not os.path.exists(src):
        return f"{m.group(1)}{NL}_{m.group('path')} has not been generated yet._{NL}{m.group(4)}"
    body = open(src, encoding="utf-8").read().replace(NL + "# ", NL + "### ").lstrip("# ").strip()
    rel = os.path.relpath(os.path.dirname(src), doc_dir).replace(os.sep, "/")

    def fix(x):
        link = x.group(1)
        if re.match(r"(https?:|/|#)", link):
            return x.group(0)
        return f"]({rel}/{link})"

    body = re.sub(r"\]\(([^)]+\.(?:png|svg|jpg))\)", fix, body)
    return f"{m.group(1)}{NL}{body}{NL}{m.group(4)}"


def main():
    docs = sys.argv[1:] or DEFAULT_DOCS
    for d in docs:
        path = os.path.join(ROOT, d)
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8").read()
        doc_dir = os.path.dirname(path)
        new, n = PAT.subn(lambda m: render(m, doc_dir), text)
        open(path, "w", encoding="utf-8").write(new)
        print(f"{d}: embedded {n} block(s)")


if __name__ == "__main__":
    sys.exit(main())
