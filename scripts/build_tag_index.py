#!/usr/bin/env python3
"""用語一覧.md の見出しから タグ一覧.md を生成する。

AI: ユーザーがタグ一覧の再生成を明示依頼したとき以外は実行しない（README 共通ルール参照）。

用語行（数千件）は含めない。過去問の分野タグ決定用。

  python3 scripts/build_tag_index.py
"""

from __future__ import annotations

import re
from pathlib import Path

GLOSSARY_FILENAME = "用語一覧.md"
TAG_INDEX_FILENAME = "タグ一覧.md"

SECTION_RE = re.compile(r"^## (#\d+) (.+?) - \d+語")
SUBSECTION_RE = re.compile(r"^### (.+?)（\d+）")

EXAM_TOP = [
    (range(1, 12), "テクノロジ系", "テクノロジ"),
    (range(12, 17), "マネジメント系", "マネジメント"),
    (range(17, 24), "ストラテジ系", "ストラテジ"),
]


def tag_from_name(name: str) -> str:
    """Obsidian タグ用（空白・記号はそのまま。先頭 # は付けない）。"""
    return name.strip()


def exam_top_for_cat(cat_num: int) -> tuple[str, str]:
    for nums, ap_label, tag in EXAM_TOP:
        if cat_num in nums:
            return ap_label, tag
    return "要確認", "要確認"


def parse_glossary_headings(path: Path) -> tuple[list[dict], list[dict]]:
    sections: list[dict] = []
    subsections: list[dict] = []
    current: dict | None = None

    for line in path.read_text(encoding="utf-8").splitlines():
        m_sec = SECTION_RE.match(line)
        if m_sec:
            num = int(m_sec.group(1).lstrip("#"))
            title = m_sec.group(2)
            ap_label, top_tag = exam_top_for_cat(num)
            current = {
                "num": num,
                "title": title,
                "tag": tag_from_name(title),
                "ap_top": ap_label,
                "top_tag": top_tag,
            }
            sections.append(current)
            continue
        m_sub = SUBSECTION_RE.match(line)
        if m_sub and current is not None:
            sub_title = m_sub.group(1)
            subsections.append(
                {
                    "title": sub_title,
                    "tag": tag_from_name(sub_title),
                    "parent_num": current["num"],
                    "parent_title": current["title"],
                    "parent_tag": current["tag"],
                }
            )

    return sections, subsections


def build_markdown(sections: list[dict], subsections: list[dict]) -> str:
    lines = [
        "# タグ一覧",
        "",
        "過去問ノートの `#問題` に続けて付ける分野タグ。**用語リンクの可否は `用語一覧.md` を見る。**",
        "",
        "出典: [ap-siken 用語集](https://www.ap-siken.com/keyword/) の分野構成（`用語一覧.md` の見出しと一致）",
        "",
        "再生成: `python3 scripts/build_tag_index.py`（`用語一覧.md` 更新後）",
        "",
        "---",
        "",
        "## タグの付け方（過去問）",
        "",
        "1. ap-siken 問題ページの **分類** 行を読む（例: `テクノロジ系 » 基礎理論 » 離散数学`）",
        "2. 下表で Obsidian タグに変換し、`#問題` の直後に付ける",
        "3. **付けるタグ**: 大分類タグ ＋ 中分類タグ ＋ 小分類タグ（分類に出てきた段階だけ。全部付けなくてよい）",
        "",
        "---",
        "",
        "## 午前IV 大分類（ap-siken「分類」の先頭）",
        "",
        "| ap-siken | Obsidianタグ | シラバス #N の範囲 |",
        "|----------|--------------|-------------------|",
    ]
    for nums, ap_label, tag in EXAM_TOP:
        lo, hi = nums.start, nums.stop - 1
        lines.append(f"| {ap_label} | `#{tag}` | #{lo}–#{hi} |")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 中分類（`用語一覧` の `## #N …` ＝ ap-siken 分類の中段）",
            "",
            "| #N | 分野名 | Obsidianタグ | 午前IV |",
            "|----|--------|--------------|--------|",
        ]
    )
    for s in sections:
        lines.append(
            f"| {s['num']} | {s['title']} | `#{s['tag']}` | {s['ap_top']} |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 小分類（`用語一覧` の `### …` ＝ ap-siken 分類の末段）",
            "",
            "| 小分類 | Obsidianタグ | 親 #N | 親タグ |",
            "|--------|--------------|-------|--------|",
        ]
    )
    for sub in subsections:
        lines.append(
            f"| {sub['title']} | `#{sub['tag']}` | {sub['parent_num']} | `#{sub['parent_tag']}` |"
        )

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    glossary = root / GLOSSARY_FILENAME
    out = root / TAG_INDEX_FILENAME

    if not glossary.is_file():
        raise SystemExit(f"{GLOSSARY_FILENAME} がありません: {glossary}")

    sections, subsections = parse_glossary_headings(glossary)
    out.write_text(build_markdown(sections, subsections), encoding="utf-8")
    print(f"更新: {out}")
    print(f"  中分類: {len(sections)}  小分類: {len(subsections)}")


if __name__ == "__main__":
    main()
