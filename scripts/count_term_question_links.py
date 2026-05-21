#!/usr/bin/env python3
"""問題/ 内の用語リンクのみを集計し、用語一覧.md に過去問数を付与する。

集計対象:
  - フォルダ: 問題/**/*.md（`_サンプル` など `_` 始まりのディレクトリ／ファイルは除く）
  - タグ: #問題 があるファイルのみ
  - リンク: HTML internal-link（href / data-href="用語/○○"）

集計しない例:
  - 用語ページの ## 出典 [[令和3年春期 午前 問38]]（用語→問題）
  - 用語ページ本文の [[脆弱性]] など（用語→用語）
  - 用語一覧.md の [[用語名]]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

QUESTIONS_DIR_NAME = "問題"
GLOSSARY_FILENAME = "用語一覧.md"
QUESTION_TAG = "#問題"

# 問題ノート → 用語（HTML）
TERM_LINK_RE = re.compile(
    r'(?:href|data-href)="用語/([^"]+)"',
    re.MULTILINE,
)

# _用語一覧.md の行: - [[用語名]] または - [[用語名]]（3）
GLOSSARY_LINE_RE = re.compile(
    r"^(- \[\[)(.+?)(\]\])(?:（\d+）)?\s*$",
)


def is_excluded_question_path(path: Path, questions_dir: Path) -> bool:
    """テンプレート・下書きを集計から除外。"""
    if path.name.startswith("_"):
        return True
    rel_parts = path.relative_to(questions_dir).parts
    return any(part.startswith("_") for part in rel_parts)


def iter_question_notes(questions_dir: Path):
    """問題/ 配下の .md（_サンプル 等は除く）。"""
    for path in sorted(questions_dir.rglob("*.md")):
        if is_excluded_question_path(path, questions_dir):
            continue
        yield path


def question_label(path: Path, questions_dir: Path) -> str:
    """問題ノートの識別子（サブフォルダ時は 令和3年/午前 問38 形式）。"""
    return str(path.relative_to(questions_dir).with_suffix(""))


def scan_questions(questions_dir: Path) -> dict[str, set[str]]:
    """用語名 → リンク元になっている問題ノート識別子の集合。"""
    counts: dict[str, set[str]] = defaultdict(set)
    skipped: list[str] = []

    for path in iter_question_notes(questions_dir):
        text = path.read_text(encoding="utf-8")
        if QUESTION_TAG not in text:
            skipped.append(question_label(path, questions_dir))
            continue
        qid = question_label(path, questions_dir)
        for term in TERM_LINK_RE.findall(text):
            counts[term].add(qid)

    if skipped:
        print(
            f"スキップ（{QUESTION_TAG} なし）: {', '.join(skipped)}",
            file=sys.stderr,
        )

    return dict(counts)


def update_glossary_index(glossary_path: Path, counts: dict[str, set[str]]) -> tuple[int, int]:
    """一覧の各行に （N） を付与。N=0 のときは付けない。戻り値: (更新行数, 出題あり語数)。"""
    lines = glossary_path.read_text(encoding="utf-8").splitlines()
    updated = 0
    with_hits = 0
    out: list[str] = []

    for line in lines:
        m = GLOSSARY_LINE_RE.match(line)
        if not m:
            out.append(line)
            continue
        prefix, term, suffix = m.group(1), m.group(2), m.group(3)
        n = len(counts.get(term, ()))
        if n > 0:
            out.append(f"{prefix}{term}{suffix}（{n}）")
            updated += 1
            with_hits += 1
        else:
            out.append(f"{prefix}{term}{suffix}")

    glossary_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return updated, with_hits


def print_report(counts: dict[str, set[str]], questions_dir: Path) -> None:
    scanned = list(iter_question_notes(questions_dir))
    tagged = sum(1 for p in scanned if QUESTION_TAG in p.read_text(encoding="utf-8"))
    print(f"問題ノート: {len(scanned)} 件（{QUESTION_TAG} あり: {tagged} 件）")
    if not counts:
        print("用語リンク: 0 件")
        return
    ranked = sorted(counts.items(), key=lambda x: (-len(x[1]), x[0]))
    print(f"リンクがある用語: {len(ranked)} 語\n")
    for term, questions in ranked:
        q_list = ", ".join(sorted(questions))
        print(f"  {term}: {len(questions)} 問 — {q_list}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="一覧を更新せず、集計結果だけ表示",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    questions_dir = root / QUESTIONS_DIR_NAME
    glossary_path = root / GLOSSARY_FILENAME

    if not questions_dir.is_dir():
        raise SystemExit(f"{QUESTIONS_DIR_NAME} フォルダがありません: {questions_dir}")
    if not glossary_path.is_file():
        raise SystemExit(f"用語一覧がありません: {glossary_path}")

    counts = scan_questions(questions_dir)
    print_report(counts, questions_dir)

    if args.dry_run:
        print(f"\n(dry-run: {GLOSSARY_FILENAME} は未更新)")
        return

    updated, with_hits = update_glossary_index(glossary_path, counts)
    print(f"\n更新: {glossary_path}")
    print(f"  一覧行に（N）を付与: {updated} 行（出題あり {with_hits} 語）")


if __name__ == "__main__":
    main()
