"""Render README.md and docs/*.md into one readable HTML file (docs_html/index.html).

Markdown is hard to read in Notepad; this needs no dependencies and works offline."""

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORDER = [
    "README.md",
    "docs/PREREG.md",
    "docs/METRICS.md",
    "docs/DECISIONS.md",
    "docs/ASSUMPTIONS.md",
    "docs/SECURITY.md",
    "docs/DATA_CARD.md",
    "docs/PRD.md",
]
CSS = (
    "body{font:16px/1.55 system-ui,sans-serif;max-width:860px;margin:0 auto;padding:16px}"
    "pre{background:#f3f3f3;padding:10px;overflow-x:auto}code{background:#f3f3f3}"
    "nav a{margin-right:12px}@media(prefers-color-scheme:dark){body{background:#161616;"
    "color:#eee}pre,code{background:#2a2a2a}a{color:#7aa2f7}}"
)


def inline(t: str) -> str:
    t = html.escape(t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)


def render(md: str) -> str:
    out, in_code, in_list = [], False, False
    for line in md.splitlines():
        if line.startswith("```"):
            out.append("</pre>" if in_code else "<pre>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        item = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)", line)
        if item and not in_list:
            out.append("<ul>")
            in_list = True
        if not item and in_list:
            out.append("</ul>")
            in_list = False
        if item:
            out.append(f"<li>{inline(item.group(1))}</li>")
        elif m := re.match(r"^(#+)\s+(.*)", line):
            out.append(f"<h{len(m[1])}>{inline(m[2])}</h{len(m[1])}>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    return "\n".join(out + (["</ul>"] if in_list else []))


def main() -> None:
    parts, nav = [], []
    for rel in ORDER:
        p = ROOT / rel
        if p.exists():
            anchor = rel.replace("/", "-").replace(".md", "")
            nav.append(f'<a href="#{anchor}">{rel}</a>')
            parts.append(
                f'<section id="{anchor}"><hr>{render(p.read_text(encoding="utf-8"))}</section>'
            )
    out = ROOT / "docs_html" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        f"<!doctype html><meta charset=utf-8><title>TBV docs</title><style>{CSS}</style>"
        f"<nav>{''.join(nav)}</nav>{''.join(parts)}",
        encoding="utf-8",
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
