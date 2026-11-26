"""Render a Markdown document of docs/ as a print-ready PDF (A4), for the submission.

    python scripts/render_doc.py docs/proposal.md docs/proposal.pdf

The Markdown stays the source (it reads well on GitHub); the PDF is a styled print of it,
made with a Chromium-based browser in headless mode (Edge or Chrome). Needs: markdown.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
]

STYLE = """
@page { size: A4; margin: 20mm 20mm 20mm 20mm; }
/* Text: Times New Roman 12 pt, headings 14 pt, line spacing 1.5, all in black; the yellow
   bars mark the headings. The cover page keeps its own design. */
:root { --ink: #000; --line: #8c8c8c; --tint: #f2f2f2; --accent: #f2b705; }
* { box-sizing: border-box; }
body { font-family: "Times New Roman", Times, serif; color: #000; font-size: 12pt;
       line-height: 1.5; margin: 0; background: #fff; text-align: justify; }
h1 { font-size: 14pt; margin: 0 0 6pt; border-left: 6pt solid var(--accent); padding-left: 9pt;
     line-height: 1.3; }
h1 + p { margin: 0 0 10pt 15pt; }
h2 { font-size: 14pt; margin: 14pt 0 6pt; padding-bottom: 2pt; line-height: 1.3;
     border-bottom: 1.5pt solid var(--accent); break-after: avoid; text-align: left; }
p { margin: 0 0 6pt; }
blockquote { margin: 6pt 0 10pt; padding: 6pt 10pt; background: #fff8e1;
             border-left: 4pt solid var(--accent); }
blockquote p { margin: 0 0 3pt; }
ol, ul { margin: 0 0 6pt 0; padding-left: 18pt; }
li { margin-bottom: 2pt; }
/* Tables: same layout, black text, black header, readable size. */
table { width: 100%; border-collapse: collapse; margin: 4pt 0 10pt; font-size: 10.5pt;
        line-height: 1.3; break-inside: auto; text-align: left; }
th { background: #000; color: #fff; font-weight: bold; padding: 4pt 6pt; vertical-align: bottom; }
td { padding: 4pt 6pt; border-bottom: 0.6pt solid var(--line); vertical-align: top; color: #000; }
tr { break-inside: avoid; }
tbody tr:nth-child(even) td { background: var(--tint); }
td:first-child { font-weight: bold; }
strong { font-weight: bold; }
code { font-family: Consolas, "Courier New", monospace; font-size: 10pt; color: #000;
       background: var(--tint); padding: 0 2pt; overflow-wrap: anywhere; }
table code { font-size: 9.5pt; }
th code { background: transparent; color: #fff; }
pre { background: var(--tint); border: 0.6pt solid var(--line); padding: 5pt 8pt;
      margin: 4pt 0 8pt; white-space: pre-wrap; line-height: 1.3; text-align: left; }
pre code { background: none; padding: 0; }
figure { margin: 8pt 0 10pt; break-inside: avoid; text-align: center; }
figure img { width: 100%; max-height: 120mm; object-fit: contain; }
figcaption { font-size: 10.5pt; font-style: italic; margin-top: 3pt; }
/* A tall diagram may use almost the whole page height, so its labels stay readable. */
figure.tall img { max-height: 225mm; }
.toc { margin: 10pt 0; padding: 8pt 12pt; border: 0.8pt solid var(--line); text-align: left; }
.toc p { margin: 0; }
/* Cover page (report): a full first page, then the text. */
.cover { height: 255mm; display: flex; flex-direction: column; break-after: page;
         padding: 14mm 6mm 6mm; border-top: 10pt solid var(--accent); text-align: left;
         font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; color: #16202e;
         --ink2: #44536a; line-height: 1.4; }
.cover-top { font-size: 12pt; font-weight: 700; letter-spacing: 0.04em; line-height: 1.5; }
.cover-course { margin-top: 10mm; font-size: 11pt; color: var(--ink2); line-height: 1.5; }
.cover-title { margin-top: 48mm; font-size: 34pt; font-weight: 750; letter-spacing: -0.02em; }
.cover-sub { margin-top: 5mm; font-size: 13pt; color: var(--ink2); line-height: 1.45;
             border-left: 5pt solid var(--accent); padding-left: 9pt; }
.cover-meta { margin-top: auto; font-size: 10.5pt; line-height: 1.6; }
.cover-meta p { margin: 0; }
.cover-meta strong { display: inline-block; width: 30mm; color: var(--ink2); font-weight: 600; }
/* Page numbers (Chromium page-margin boxes); none on the cover. */
@page { @bottom-right { content: counter(page) " / " counter(pages); font-size: 10pt;
                        color: #000; font-family: "Times New Roman", Times, serif; } }
@page :first { @bottom-right { content: none; } }
"""


def browser() -> str:
    for candidate in BROWSERS:
        if Path(candidate).exists() or shutil.which(candidate):
            return candidate
    raise SystemExit("no Edge or Chrome found to print the PDF")


def render(source: Path, target: Path) -> None:
    # md_in_html: Markdown inside the HTML blocks (cover page, contents box) is rendered too.
    body = markdown.markdown(
        source.read_text(encoding="utf-8"), extensions=["tables", "md_in_html", "fenced_code"]
    )
    title = source.stem.replace("_", " ").title()
    # Images are referenced relative to the Markdown file (docs/diagrams/...).
    base = source.resolve().parent.as_uri() + "/"
    page = (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title>'
        f'<base href="{base}"><style>{STYLE}</style></head><body>{body}</body></html>'
    )
    with tempfile.TemporaryDirectory() as tmp:
        html = Path(tmp) / "page.html"
        html.write_text(page, encoding="utf-8")
        before = target.stat().st_mtime if target.exists() else 0
        try:
            _print(html, target, tmp)
        except subprocess.TimeoutExpired:
            # Headless Edge sometimes writes the PDF and then does not exit.
            if not target.exists() or target.stat().st_mtime <= before:
                raise
    print(f"written {target}")


def _print(html: Path, target: Path, tmp: str) -> None:
    subprocess.run(
        [
            # Own profile: an open browser window would otherwise take the job and hang.
            browser(), "--headless", "--disable-gpu", "--no-pdf-header-footer",
            "--no-first-run", f"--user-data-dir={Path(tmp) / 'profile'}",
            f"--print-to-pdf={target.resolve()}", html.resolve().as_uri(),
        ],
        check=True, capture_output=True, timeout=120,
    )  # fmt: skip


if __name__ == "__main__":
    render(Path(sys.argv[1]), Path(sys.argv[2]))
