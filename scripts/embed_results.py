"""Copy generated result files into README.md between markers, so no number is ever retyped.

    python scripts/embed_results.py

Markers in README.md:  <!-- EMBED:eval/results/summary.md -->  ...  <!-- /EMBED -->
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(ROOT, "README.md")
PAT = re.compile(r"(<!-- EMBED:(?P<path>[^ ]+) -->)(.*?)(<!-- /EMBED -->)", re.S)


def render(m):
    path = os.path.join(ROOT, m.group("path"))
    if not os.path.exists(path):
        body = f"\n_{m.group('path')} has not been generated yet._\n"
    else:
        body = "\n" + open(path, encoding="utf-8").read().replace("\n# ", "\n### ").lstrip("# ").strip() + "\n"
        body = re.sub(r"\]\((?!http|/)([^)]+\.png)\)", lambda x: f"](eval/results/{x.group(1)})"
                      if "eval/results" in m.group("path") else x.group(0), body)
    return f"{m.group(1)}{body}{m.group(4)}"


def main():
    text = open(README, encoding="utf-8").read()
    new, n = PAT.subn(render, text)
    open(README, "w", encoding="utf-8").write(new)
    print(f"embedded {n} block(s)")


if __name__ == "__main__":
    sys.exit(main())
