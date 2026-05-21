"""用語一覧・問題ノート・用語ページの共通処理。"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

QUESTIONS_DIR_NAME = "問題"
GLOSSARY_FILENAME = "用語一覧.md"
TERMS_DIR_NAME = "用語"
QUESTION_TAG = "#問題"

TERM_LINK_RE = re.compile(
    r'(?:href|data-href)="用語/([^"]+)"',
    re.MULTILINE,
)

WIKI_LINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]+)?\]\]")

TERMS_TAG = "#用語"
SOURCE_SECTION = "## 出典"

GLOSSARY_LINE_RE = re.compile(
    r"^(- \[\[)(.+?)(\]\])(?:（\d+）)?\s*$",
)


def is_excluded_question_path(path: Path, questions_dir: Path) -> bool:
    if path.name.startswith("_"):
        return True
    rel_parts = path.relative_to(questions_dir).parts
    return any(part.startswith("_") for part in rel_parts)


def iter_question_notes(questions_dir: Path):
    for path in sorted(questions_dir.rglob("*.md")):
        if is_excluded_question_path(path, questions_dir):
            continue
        yield path


def question_label(path: Path, questions_dir: Path) -> str:
    return path.relative_to(questions_dir).with_suffix("").as_posix()


def normalize_question_ref(
    ref: str,
    questions_dir: Path,
    vault_root: Path,
) -> str:
    """問題ノート参照を 問題/ 配下の相対ID（スラッシュ区切り・拡張子なし）に正規化。

    受け付ける例:
      問題/午前/R3春期/問38
      問題/午前/R3春期/問38.md
      午前/R3春期/問38  （従来形式・問題/ 省略可）
    """
    raw = ref.strip().strip('"').strip("'")
    if not raw:
        raise SystemExit("問題ノートのパスが空です")

    p = Path(raw)
    if p.is_absolute():
        target = p.resolve()
    elif p.parts and p.parts[0] == QUESTIONS_DIR_NAME:
        target = (vault_root / p).resolve()
    else:
        target = (questions_dir / p).resolve()

    if target.suffix.lower() != ".md":
        with_md = target.with_suffix(".md")
        target = with_md if with_md.is_file() else target.with_suffix(".md")

    qdir = questions_dir.resolve()
    try:
        rel = target.relative_to(qdir)
    except ValueError as e:
        raise SystemExit(
            f"問題ノートのパスを解決できません: {ref}\n"
            f"  例: 問題/午前/R3春期/問38  または  午前/R3春期/問38"
        ) from e

    return rel.with_suffix("").as_posix()


def question_note_path(qid: str, questions_dir: Path) -> Path:
    return questions_dir.joinpath(*Path(qid).parts).with_suffix(".md")


def load_glossary_terms(glossary_path: Path) -> set[str]:
    terms: set[str] = set()
    for line in glossary_path.read_text(encoding="utf-8").splitlines():
        m = GLOSSARY_LINE_RE.match(line)
        if m:
            terms.add(m.group(2))
    return terms


def existing_term_pages(terms_dir: Path) -> set[str]:
    if not terms_dir.is_dir():
        return set()
    return {p.stem for p in terms_dir.glob("*.md") if not p.name.startswith("_")}


def extract_term_links(text: str) -> list[str]:
    """出現順を保ちつつ重複を除いた用語名リスト。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for term in TERM_LINK_RE.findall(text):
        if term not in seen:
            seen.add(term)
            ordered.append(term)
    return ordered


def scan_questions_by_file(
    questions_dir: Path,
    *,
    require_tag: bool = True,
    question_filter: str | None = None,
) -> tuple[dict[str, list[str]], list[str]]:
    """問題識別子 → リンクされている用語名（順序保持・重複なし）。"""
    by_file: dict[str, list[str]] = {}
    skipped: list[str] = []

    filter_qid: str | None = None
    if question_filter is not None:
        filter_qid = normalize_question_ref(
            question_filter, questions_dir, questions_dir.parent
        )

    for path in iter_question_notes(questions_dir):
        qid = question_label(path, questions_dir)
        if filter_qid is not None and qid != filter_qid:
            continue
        text = path.read_text(encoding="utf-8")
        if require_tag and QUESTION_TAG not in text:
            skipped.append(qid)
            continue
        terms = extract_term_links(text)
        if terms:
            by_file[qid] = terms

    return by_file, skipped


def _term_appears_in_text(term: str, text: str) -> bool:
    """一覧語が本文に「用語として」出ているか（短い英字の部分一致を抑える）。"""
    if len(term) < 2:
        return False
    # 英数字・記号のみの語は長さ3以上＋単語境界っぽい前後
    if re.fullmatch(r"[A-Za-z0-9./+\-_]+", term):
        if len(term) < 3:
            return False
        pat = r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"
        return bool(re.search(pat, text))
    return term in text


def suggest_glossary_terms_in_text(text: str, glossary_terms: set[str]) -> list[str]:
    """本文に出現する用語一覧の語を、長い語優先で列挙。"""
    found: list[str] = []
    for term in sorted(glossary_terms, key=len, reverse=True):
        if _term_appears_in_text(term, text):
            found.append(term)
    return found


def internal_link_html(term: str) -> str:
    return (
        f'<a href="用語/{term}" class="internal-link" '
        f'data-href="用語/{term}">{term}</a>'
    )


def _replace_plain_occurrences(segment: str, term: str, replacement: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9./+\-_]+", term):
        if len(term) < 3:
            return segment
        pat = r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"
        return re.sub(pat, replacement, segment)
    return segment.replace(term, replacement)


def _replace_in_outside_tags(text: str, term: str, replacement: str) -> str:
    """HTML タグの外側のテキストだけ置換（既存 <a> 内は触らない）。"""
    if f'data-href="用語/{term}"' in text:
        chunks = re.split(r"(<a\s[^>]*>.*?</a>)", text, flags=re.DOTALL | re.IGNORECASE)
        out: list[str] = []
        for i, chunk in enumerate(chunks):
            if i % 2 == 0:
                chunk = _replace_plain_occurrences(chunk, term, replacement)
            out.append(chunk)
        return "".join(out)
    parts = re.split(r"(<[^>]+>)", text)
    for i in range(0, len(parts), 2):
        parts[i] = _replace_plain_occurrences(parts[i], term, replacement)
    return "".join(parts)


def parse_apply_terms_arg(chunks: list[str], glossary_terms: set[str]) -> list[str]:
    """--terms の値（カンマ区切り可・複数回指定可）を正規化し、一覧に無い語はエラー。"""
    out: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        for part in chunk.split(","):
            t = part.strip()
            if not t or t in seen:
                continue
            seen.add(t)
            if t not in glossary_terms:
                raise ValueError(f"用語一覧にない語: {t}")
            out.append(t)
    if not out:
        raise ValueError("--terms に語が指定されていません")
    return out


def apply_question_internal_links(
    text: str,
    glossary_terms: set[str],
    only_terms: list[str] | None = None,
) -> tuple[str, list[str], list[str]]:
    """未リンクの語に internal-link を付与。

    only_terms 指定時はその語だけ（本文に出現・未リンクのもの）。
    戻り値: (新テキスト, 付与した語, スキップした語)
    """
    linked = set(extract_term_links(text))
    if only_terms is not None:
        pool = only_terms
    else:
        pool = suggest_glossary_terms_in_text(text, glossary_terms)
    to_apply: list[str] = []
    skipped: list[str] = []
    for t in pool:
        if t in linked:
            skipped.append(t)
            continue
        if not _term_appears_in_text(t, text):
            skipped.append(t)
            continue
        to_apply.append(t)
    if not to_apply:
        return text, [], skipped
    out = text
    for term in sorted(to_apply, key=len, reverse=True):
        out = _replace_in_outside_tags(out, term, internal_link_html(term))
    return out, to_apply, skipped


def apply_term_wiki_links(
    text: str,
    glossary_terms: set[str],
    own_term: str,
    only_terms: list[str] | None = None,
) -> tuple[str, list[str], list[str]]:
    """## 出典 より前に未リンクの語へ [[用語]] を付与。"""
    body = term_note_body(text)
    suffix = text[len(body) :]
    linked = set(extract_term_wiki_links(text))
    if only_terms is not None:
        pool = only_terms
    else:
        pool = suggest_terms_for_term_note(text, glossary_terms, own_term)
    to_apply: list[str] = []
    skipped: list[str] = []
    for t in pool:
        if t in linked:
            skipped.append(t)
            continue
        if not _term_appears_in_text(t, body):
            skipped.append(t)
            continue
        to_apply.append(t)
    if not to_apply:
        return text, [], skipped
    new_body = body
    for term in sorted(to_apply, key=len, reverse=True):
        new_body = _replace_in_outside_tags(new_body, term, f"[[{term}]]")
    return new_body + suffix, to_apply, skipped


def term_note_body(text: str) -> str:
    """## 出典 より前を用語リンクの対象本文とする。"""
    idx = text.find(SOURCE_SECTION)
    return text[:idx] if idx >= 0 else text


def is_excluded_term_path(path: Path) -> bool:
    return path.name.startswith("_")


def iter_term_notes(terms_dir: Path):
    for path in sorted(terms_dir.rglob("*.md")):
        if is_excluded_term_path(path):
            continue
        yield path


def term_label(path: Path, terms_dir: Path) -> str:
    return path.relative_to(terms_dir).with_suffix("").as_posix()


def normalize_term_ref(
    ref: str,
    terms_dir: Path,
    vault_root: Path,
) -> str:
    """用語ページ参照を 用語/ 配下の相対ID に正規化。"""
    raw = ref.strip().strip('"').strip("'")
    if not raw:
        raise SystemExit("用語ノートのパスが空です")

    p = Path(raw)
    if p.is_absolute():
        target = p.resolve()
    elif p.parts and p.parts[0] == TERMS_DIR_NAME:
        target = (vault_root / p).resolve()
    else:
        target = (terms_dir / p).resolve()

    if target.suffix.lower() != ".md":
        with_md = target.with_suffix(".md")
        target = with_md if with_md.is_file() else target.with_suffix(".md")

    tdir = terms_dir.resolve()
    try:
        rel = target.relative_to(tdir)
    except ValueError as e:
        raise SystemExit(
            f"用語ノートのパスを解決できません: {ref}\n"
            f"  例: 用語/脆弱性  または  脆弱性"
        ) from e

    return rel.with_suffix("").as_posix()


def term_note_path(tid: str, terms_dir: Path) -> Path:
    return terms_dir.joinpath(*Path(tid).parts).with_suffix(".md")


def extract_wiki_links(text: str) -> list[str]:
    """出現順を保ちつつ重複を除いた wiki リンク先。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for target in WIKI_LINK_RE.findall(text):
        t = target.strip()
        if t and t not in seen:
            seen.add(t)
            ordered.append(t)
    return ordered


def glossary_term_targets(links: list[str]) -> list[str]:
    """用語一覧と照合するリンク先のみ（問題ノート・出典用は除外）。"""
    out: list[str] = []
    for target in links:
        if target.startswith(f"{QUESTIONS_DIR_NAME}/"):
            continue
        if target.startswith(f"{TERMS_DIR_NAME}/"):
            target = target[len(TERMS_DIR_NAME) + 1 :]
        out.append(target)
    return out


def extract_term_wiki_links(text: str) -> list[str]:
    return glossary_term_targets(extract_wiki_links(term_note_body(text)))


def scan_terms_by_file(
    terms_dir: Path,
    vault_root: Path,
    *,
    require_tag: bool = True,
    term_filter: str | None = None,
) -> tuple[dict[str, list[str]], list[str]]:
    by_file: dict[str, list[str]] = {}
    skipped: list[str] = []

    filter_tid: str | None = None
    if term_filter is not None:
        filter_tid = normalize_term_ref(term_filter, terms_dir, vault_root)

    for path in iter_term_notes(terms_dir):
        tid = term_label(path, terms_dir)
        if filter_tid is not None and tid != filter_tid:
            continue
        text = path.read_text(encoding="utf-8")
        if require_tag and TERMS_TAG not in text:
            skipped.append(tid)
            continue
        terms = extract_term_wiki_links(text)
        if terms:
            by_file[tid] = terms

    return by_file, skipped


def suggest_terms_for_term_note(
    text: str,
    glossary_terms: set[str],
    own_term: str,
) -> list[str]:
    body = term_note_body(text)
    found = suggest_glossary_terms_in_text(body, glossary_terms)
    return [t for t in found if t != own_term]


def scan_questions_term_to_questions(questions_dir: Path) -> dict[str, set[str]]:
    """用語名 → リンク元問題の集合（#問題 タグ必須）。"""
    counts: dict[str, set[str]] = defaultdict(set)
    by_file, _ = scan_questions_by_file(questions_dir, require_tag=True)
    for qid, terms in by_file.items():
        for term in terms:
            counts[term].add(qid)
    return dict(counts)
