#!/usr/bin/env python3
"""問題/ 内の用語リンクのみを集計し、用語一覧.md に過去問数を付与する。

集計対象:
  - フォルダ: 問題/**/*.md（`_サンプル` など `_` 始まりのディレクトリ／ファイルは除く）
  - タグ: #問題 があるファイルのみ
  - リンク: `ap-choice-note`・`ap-explanation` 内の HTML internal-link（href / data-href="用語/○○"）

集計しない例:
  - 用語ページの ## 出典 [[38]] や [[問題/午前/R3春期/38]]（用語→問題）
  - 用語ページ本文の [[脆弱性]] など（用語→用語）
  - 用語一覧.md の [[用語名]]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from glossary_lib import (
    GLOSSARY_FILENAME,
    GLOSSARY_LINE_RE,
    QUESTIONS_DIR_NAME,
    iter_question_notes,
    question_label,
    scan_questions_term_to_questions,
)

QUESTION_TAG = "#問題"


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

    counts = scan_questions_term_to_questions(questions_dir)
    print_report(counts, questions_dir)

    if args.dry_run:
        print(f"\n(dry-run: {GLOSSARY_FILENAME} は未更新)")
        return

    updated, with_hits = update_glossary_index(glossary_path, counts)
    print(f"\n更新: {glossary_path}")
    print(f"  一覧行に（N）を付与: {updated} 行（出題あり {with_hits} 語）")


if __name__ == "__main__":
    main()
