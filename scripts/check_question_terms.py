#!/usr/bin/env python3
"""用語一覧と照合する（問題ノート・用語ノート）。

問題ノート（--question）:
  --suggest  解説からリンクすべき語（リンク前）
  --apply    リンクを付与（--terms 省略時は --suggest と同じ全候補）
  --terms    --apply 時に付与する語（カンマ区切り・複数回可）
  （既定）   一覧外 internal-link の検出

用語ノート（--term）:
  --suggest  本文から [[リンク]] すべき語（## 出典 より前）
  --apply    候補に [[用語名]] を付与
  （既定）   一覧外 [[リンク]] の検出

使い方:
  python3 scripts/check_question_terms.py --suggest --question 問題/…
  python3 scripts/check_question_terms.py --apply --question 問題/… --terms 語1,語2
  python3 scripts/check_question_terms.py --question 問題/…
  python3 scripts/check_question_terms.py --suggest --term 用語/…
  python3 scripts/check_question_terms.py --apply --term 用語/…
  python3 scripts/check_question_terms.py --term 用語/…
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from glossary_lib import (
    GLOSSARY_FILENAME,
    QUESTIONS_DIR_NAME,
    QUESTION_TAG,
    TERMS_DIR_NAME,
    TERMS_TAG,
    apply_question_internal_links,
    apply_term_wiki_links,
    parse_apply_terms_arg,
    extract_term_links,
    extract_term_wiki_links,
    load_glossary_terms,
    normalize_question_ref,
    normalize_term_ref,
    question_note_path,
    scan_questions_by_file,
    scan_terms_by_file,
    suggest_glossary_terms_in_text,
    suggest_terms_for_term_note,
    term_note_path,
)


def check_glossary(
    glossary_terms: set[str],
    by_file: dict[str, list[str]],
) -> tuple[list[tuple[str, list[str]]], list[str]]:
    issues: list[tuple[str, list[str]]] = []
    ok: list[str] = []
    for nid in sorted(by_file):
        bad = [t for t in by_file[nid] if t not in glossary_terms]
        if bad:
            issues.append((nid, bad))
        else:
            ok.append(nid)
    return issues, ok


def print_check_report(
    *,
    kind: str,
    display_path: str,
    issues: list[tuple[str, list[str]]],
    ok: list[str],
    skipped: list[str],
    all_label: str,
    empty_msg: str,
) -> None:
    print(f"対象: {display_path}（リンク照合）\n")
    if skipped:
        print(f"スキップ（{kind} なし）: {', '.join(skipped)}\n")
    if not issues and not ok:
        print(empty_msg)
        return
    if issues:
        print("## 要対応（一覧外リンク）\n")
        for nid, bad in issues:
            print(f"### {all_label}/{nid}.md")
            for t in bad:
                print(f"  - {t}")
            print()
    if ok:
        print("## OK（リンクはすべて用語一覧にあり）\n")
        for nid in ok:
            print(f"  - {all_label}/{nid}.md")
        print()


def print_apply_report(
    *,
    note_path: str,
    kind_label: str,
    applied: list[str],
    skipped: list[str],
    dry_run: bool,
) -> None:
    print(f"対象: {note_path}（{kind_label}）\n")
    if not applied and not skipped:
        print("付与する語: なし\n")
        return
    if applied:
        print("## 付与した語\n")
        for t in applied:
            print(f"  - {t}")
        print()
    if skipped:
        print("## スキップ（リンク済・本文に未出現など）\n")
        for t in skipped:
            print(f"  - {t}")
        print()
    if dry_run:
        print("(dry-run: ファイルは未更新)")


def print_suggest_report(
    *,
    note_path: str,
    candidates: list[str],
    linked: list[str],
    link_hint: str,
) -> None:
    print(f"対象: {note_path}（リンク候補の抽出）\n")
    not_linked = [t for t in candidates if t not in linked]
    if not candidates:
        print("リンク候補: なし（一覧の語が本文に見つかりませんでした）\n")
        return
    print("## リンクすべき語（用語一覧にあり・本文に出現）\n")
    for t in not_linked:
        print(f"  - {t}")
    for t in candidates:
        if t in linked:
            print(f"  - {t}（リンク済）")
    print()
    print(f"結果: {link_hint}")


def read_question(
    questions_dir: Path,
    vault_root: Path,
    question_ref: str,
) -> tuple[Path, str, str]:
    qid = normalize_question_ref(question_ref, questions_dir, vault_root)
    path = question_note_path(qid, questions_dir)
    if not path.is_file():
        raise SystemExit(f"問題ノートが見つかりません: {QUESTIONS_DIR_NAME}/{qid}.md")
    text = path.read_text(encoding="utf-8")
    if QUESTION_TAG not in text:
        raise SystemExit(f"{QUESTION_TAG} がありません: {QUESTIONS_DIR_NAME}/{qid}.md")
    return path, qid, text


def read_term(terms_dir: Path, vault_root: Path, term_ref: str) -> tuple[Path, str, str]:
    tid = normalize_term_ref(term_ref, terms_dir, vault_root)
    path = term_note_path(tid, terms_dir)
    if not path.is_file():
        raise SystemExit(f"用語ノートが見つかりません: {TERMS_DIR_NAME}/{tid}.md")
    text = path.read_text(encoding="utf-8")
    if TERMS_TAG not in text:
        raise SystemExit(f"{TERMS_TAG} がありません: {TERMS_DIR_NAME}/{tid}.md")
    return path, tid, text


def finish_check(issues: list[tuple[str, list[str]]]) -> None:
    if issues:
        n = sum(len(b) for _, b in issues)
        print(f"結果: 一覧にない語へのリンク {n} 語 — リンクを直して再実行")
        sys.exit(1)
    print("結果: すべて問題なし")
    sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suggest", action="store_true", help="リンク前: すべき語を抽出")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="リンクを付与（--terms で語を限定可能）",
    )
    parser.add_argument(
        "--terms",
        action="append",
        metavar="WORDS",
        help="--apply 時に付与する語（カンマ区切り。複数回指定可）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="--apply 時はファイルを書き換えない",
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--question",
        metavar="PATH",
        help="問題ノート（例: 問題/…）。.md 省略可",
    )
    target.add_argument(
        "--term",
        metavar="PATH",
        help="用語ノート（例: 用語/…）。.md 省略可",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    questions_dir = root / QUESTIONS_DIR_NAME
    terms_dir = root / TERMS_DIR_NAME
    glossary_path = root / GLOSSARY_FILENAME

    if not glossary_path.is_file():
        raise SystemExit(f"用語一覧がありません: {glossary_path}")

    glossary_terms = load_glossary_terms(glossary_path)

    if not args.question and not args.term:
        raise SystemExit("--question または --term を指定してください")
    if args.suggest and args.apply:
        raise SystemExit("--suggest と --apply は同時に指定しない")
    if args.dry_run and not args.apply:
        raise SystemExit("--dry-run は --apply と併用")
    if args.terms and not args.apply:
        raise SystemExit("--terms は --apply と併用")

    only_terms: list[str] | None = None
    if args.terms:
        try:
            only_terms = parse_apply_terms_arg(args.terms, glossary_terms)
        except ValueError as e:
            raise SystemExit(str(e)) from e

    if args.term:
        if not terms_dir.is_dir():
            raise SystemExit(f"{TERMS_DIR_NAME} フォルダがありません: {terms_dir}")

        if args.suggest:
            _, tid, text = read_term(terms_dir, root, args.term)
            candidates = suggest_terms_for_term_note(text, glossary_terms, tid)
            linked = extract_term_wiki_links(text)
            print_suggest_report(
                note_path=f"{TERMS_DIR_NAME}/{tid}.md",
                candidates=candidates,
                linked=linked,
                link_hint="候補を絞ったあと --apply --term 用語/… --terms 語1,語2 で付与",
            )
            sys.exit(0)

        if args.apply:
            path, tid, text = read_term(terms_dir, root, args.term)
            new_text, applied, skipped = apply_term_wiki_links(
                text, glossary_terms, tid, only_terms=only_terms
            )
            note_path = f"{TERMS_DIR_NAME}/{tid}.md"
            print_apply_report(
                note_path=note_path,
                kind_label="wiki リンク付与",
                applied=[f"[[{t}]]" for t in applied],
                skipped=skipped,
                dry_run=args.dry_run,
            )
            if args.dry_run:
                sys.exit(0)
            if new_text != text:
                path.write_text(new_text, encoding="utf-8")
                print(f"更新: {note_path}")
            elif applied:
                print("変更なし")
            sys.exit(0)

        display_tid = normalize_term_ref(args.term, terms_dir, root)
        by_file, skipped = scan_terms_by_file(
            terms_dir, root, require_tag=True, term_filter=args.term
        )
        if not by_file:
            try:
                read_term(terms_dir, root, args.term)
            except SystemExit:
                raise
            print(f"対象: {TERMS_DIR_NAME}/{display_tid}.md（リンク照合）\n")
            print("用語への wiki リンクがまだありません。先に --suggest で候補を確認してください。")
            sys.exit(1)

        issues, ok = check_glossary(glossary_terms, by_file)
        print_check_report(
            kind=TERMS_TAG,
            display_path=f"{TERMS_DIR_NAME}/{display_tid}.md",
            issues=issues,
            ok=ok,
            skipped=skipped,
            all_label=TERMS_DIR_NAME,
            empty_msg="用語への wiki リンクがある用語ノートはありません。",
        )
        finish_check(issues)

    # --question
    if not questions_dir.is_dir():
        raise SystemExit(f"{QUESTIONS_DIR_NAME} フォルダがありません: {questions_dir}")

    if args.suggest:
        _, qid, text = read_question(questions_dir, root, args.question)
        candidates = suggest_glossary_terms_in_text(text, glossary_terms)
        linked = extract_term_links(text)
        print_suggest_report(
            note_path=f"{QUESTIONS_DIR_NAME}/{qid}.md",
            candidates=candidates,
            linked=linked,
            link_hint="候補を絞ったあと --apply --question 問題/… --terms 語1,語2 で付与",
        )
        sys.exit(0)

    if args.apply:
        path, qid, text = read_question(questions_dir, root, args.question)
        new_text, applied, skipped = apply_question_internal_links(
            text, glossary_terms, only_terms=only_terms
        )
        note_path = f"{QUESTIONS_DIR_NAME}/{qid}.md"
        print_apply_report(
            note_path=note_path,
            kind_label="internal-link 付与",
            applied=applied,
            skipped=skipped,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            sys.exit(0)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            print(f"更新: {note_path}")
        elif applied:
            print("変更なし")
        sys.exit(0)

    display_qid = normalize_question_ref(args.question, questions_dir, root)
    by_file, skipped = scan_questions_by_file(
        questions_dir, require_tag=True, question_filter=args.question
    )
    if not by_file:
        try:
            read_question(questions_dir, root, args.question)
        except SystemExit:
            raise
        print(f"対象: {QUESTIONS_DIR_NAME}/{display_qid}.md（リンク照合）\n")
        print("用語リンクがまだありません。先に --suggest で候補を確認してください。")
        sys.exit(1)

    issues, ok = check_glossary(glossary_terms, by_file)
    print_check_report(
        kind=QUESTION_TAG,
        display_path=f"{QUESTIONS_DIR_NAME}/{display_qid}.md",
        issues=issues,
        ok=ok,
        skipped=skipped,
        all_label=QUESTIONS_DIR_NAME,
        empty_msg="用語リンク付きの問題ノートはありません。",
    )
    finish_check(issues)


if __name__ == "__main__":
    main()
