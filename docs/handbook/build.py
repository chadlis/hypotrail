"""Assemble the handbook: one source file per chapter, one self-contained HTML file.

Standard library only. Run from anywhere:

    python docs/handbook/build.py [--out FILE]

Each chapter is `chapters/NN-name.html`. Its first line is a comment of the form

    <!-- chapter: id=feasibility-spike; kicker=Spike; title=Feasibility spike; accent=gold -->

and the rest is the chapter body. The build wraps each body in the charter's
section, builds the table of contents, and fills `template.html`. Nothing is
fetched when the page is opened: no script, stylesheet, font or image comes
from a URL.
"""

import argparse
import html
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACCENTS = {"gold", "pink", "green", "teal", "violet", "sky", "coral", "amber"}
HEADER = re.compile(r"\A<!--\s*chapter:(?P<fields>.*?)-->\s*", re.S)


def parse_chapter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = HEADER.match(text)
    if not match:
        raise SystemExit(f"{path.name}: the first line must be a '<!-- chapter: ... -->' comment")
    fields = dict(
        part.strip().split("=", 1) for part in match["fields"].split(";") if "=" in part
    )
    missing = {"id", "kicker", "title", "accent"} - set(fields)
    if missing:
        raise SystemExit(f"{path.name}: missing chapter fields: {sorted(missing)}")
    if fields["accent"] not in ACCENTS:
        raise SystemExit(f"{path.name}: unknown accent {fields['accent']!r}")
    fields["body"] = text[match.end():]
    return fields


def build(chapters_dir: Path = HERE / "chapters", template: Path = HERE / "template.html") -> str:
    files = sorted(chapters_dir.glob("[0-9][0-9]-*.html"))
    if not files:
        raise SystemExit(f"no chapter found in {chapters_dir}")
    toc, sections = [], []
    for number, path in enumerate(files, 1):
        chapter = parse_chapter(path)
        label = f"{number:02d}"
        accent = f"var(--{chapter['accent']})"
        toc.append(
            f'<a href="#{chapter["id"]}" style="--ac:{accent}"><span>{label}</span>'
            f'{html.escape(chapter["title"])}</a>'
        )
        sections.append(
            f'<section id="{chapter["id"]}" style="--ac:{accent}"><div class="sh"><div class="n">{label}</div>'
            f'<div><p class="k">{html.escape(chapter["kicker"])}</p><h2>{html.escape(chapter["title"])}</h2></div></div>\n'
            f'{chapter["body"].strip()}\n</section>'
        )
    page = template.read_text(encoding="utf-8")
    page = page.replace("{{TITLE}}", "Hypotrail handbook")
    page = page.replace("{{TOC}}", "".join(toc))
    page = page.replace("{{SECTIONS}}", "\n".join(sections))
    return page


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=HERE / "handbook.html")
    args = parser.parse_args(argv)
    args.out.write_text(build(), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
