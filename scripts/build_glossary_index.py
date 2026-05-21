#!/usr/bin/env python3
"""ap-siken 用語集から 用語一覧.md を生成する（シラバス 7.2 / 全23分野）。

  python3 scripts/build_glossary_index.py
  python3 scripts/build_glossary_index.py --only 1,11   # 特定分野のみ

生成後、過去問リンク数を付ける場合（ボルトルート）:
  python3 scripts/count_term_question_links.py
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

BASE_URL = "https://www.ap-siken.com/keyword"
CATEGORY_COUNT = 23
USER_AGENT = "AP-Glossary-Indexer/1.0 (+local study vault)"


class SectionParser(HTMLParser):
    """category ページの h2 / h3.section__title / ul.section__list を解析。"""

    def __init__(self) -> None:
        super().__init__()
        self.in_h2 = False
        self.in_h3 = False
        self.in_list = False
        self.in_a = False
        self.h2 = ""
        self.sections: list[dict[str, object]] = []
        self.cur: dict[str, object] | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        cls = dict(attrs).get("class") or ""
        if tag == "h2":
            self.in_h2 = True
            self._buf = []
        elif tag == "h3" and "section__title" in cls:
            self.in_h3 = True
            self._buf = []
        elif tag == "ul" and "section__list" in cls:
            self.in_list = True
        elif tag == "a" and self.in_list:
            self.in_a = True
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self.in_h2:
            self.h2 = "".join(self._buf).strip()
            self.in_h2 = False
        elif tag == "h3" and self.in_h3:
            title = "".join(self._buf).strip()
            self.cur = {"title": title, "terms": []}
            self.sections.append(self.cur)
            self.in_h3 = False
        elif tag == "ul" and self.in_list:
            self.in_list = False
        elif tag == "a" and self.in_a:
            term = "".join(self._buf).strip()
            if term and self.cur is not None:
                self.cur["terms"].append(term)
            self.in_a = False

    def handle_data(self, data: str) -> None:
        if self.in_h2 or self.in_h3 or self.in_a:
            self._buf.append(data)


def fetch_category(cat_id: int, delay: float) -> tuple[str, list[tuple[str, list[str]]]]:
    url = f"{BASE_URL}/{cat_id}/"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        raise SystemExit(f"取得失敗 {url}: {e}") from e
    finally:
        if delay > 0:
            time.sleep(delay)

    parser = SectionParser()
    parser.feed(html)
    sections: list[tuple[str, list[str]]] = []
    for sec in parser.sections:
        title = str(sec["title"])
        terms = [str(t) for t in sec["terms"]]
        if terms:
            sections.append((title, terms))
    return parser.h2, sections


def parse_only_arg(value: str) -> list[int]:
    ids: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        n = int(part)
        if n < 1 or n > CATEGORY_COUNT:
            raise argparse.ArgumentTypeError(f"分野番号は 1–{CATEGORY_COUNT}: {n}")
        ids.append(n)
    return ids


def build_markdown(categories: list[tuple[int, str, list[tuple[str, list[str]]]]]) -> str:
    lines = [
        "# 用語一覧",
        "",
        "出典: [応用情報技術者試験 用語集（シラバス7.2）](https://www.ap-siken.com/keyword/)",
        "",
        "## 運用",
        "",
        "- このファイルは**索引のみ**。各 `[[用語]]` のページは事前に作らない",
        "- `用語/` にページがあるもの → リンク済み（クリックで開ける）",
        "- 未作成のもの → 未解決リンク（学習中に `用語/用語名.md` を追加）",
        "- **問題・解説**で用語が出てきたとき、一覧に載っていればユーザーが `用語/用語名.md` を追加（AI は明示依頼時のみ作成）",
        "- `（N）` は **問題ページ**からその用語へのリンク数（`#問題` ノートのみ。用語ページの出典は含まない）",
        "- 再生成: `python3 scripts/build_glossary_index.py` → `python3 scripts/count_term_question_links.py`",
        "",
        "---",
        "",
    ]
    grand = 0
    for cat_id, heading, sections in categories:
        section_total = sum(len(terms) for _, terms in sections)
        grand += section_total
        lines.append(f"## {heading}")
        lines.append("")
        for subsection, terms in sections:
            lines.append(f"### {subsection}")
            lines.append("")
            for term in terms:
                lines.append(f"- [[{term}]]")
            lines.append("")
        lines.append(f"<!-- #{cat_id} 件数: {section_total} -->")
        lines.append("")
        if cat_id < categories[-1][0]:
            lines.append("---")
            lines.append("")

    lines.append(f"<!-- 総件数: {grand} -->")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        type=parse_only_arg,
        metavar="N,N,...",
        help=f"取得する分野番号（1–{CATEGORY_COUNT}、カンマ区切り）",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.4,
        help="リクエスト間隔（秒、既定 0.4）",
    )
    args = parser.parse_args()

    cat_ids = args.only if args.only else list(range(1, CATEGORY_COUNT + 1))
    root = Path(__file__).resolve().parents[1]
    out = root / "用語一覧.md"

    categories: list[tuple[int, str, list[tuple[str, list[str]]]]] = []
    for i, cat_id in enumerate(cat_ids):
        heading, sections = fetch_category(cat_id, delay=args.delay if i else 0.0)
        if not heading:
            print(f"警告: #{cat_id} 見出しが空", file=sys.stderr)
        if not sections:
            print(f"警告: #{cat_id} 用語が0件", file=sys.stderr)
        term_count = sum(len(t) for _, t in sections)
        print(f"#{cat_id:2d}  {term_count:4d}語  {heading}")
        categories.append((cat_id, heading, sections))

    out.write_text(build_markdown(categories), encoding="utf-8")
    total = sum(sum(len(t) for _, t in s) for _, _, s in categories)
    print(f"\nwrote {out} ({total} terms, {len(categories)} categories)")


if __name__ == "__main__":
    main()
