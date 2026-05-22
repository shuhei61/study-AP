#!/usr/bin/env python3
"""ap-siken から過去問ノート用の図を取得し、assets/ に保存して HTML に埋め込む。

使い方（ボルトルート）:
  python3 scripts/fetch_question_figures.py --question 問題/午前/R3春期/14.md
  python3 scripts/fetch_question_figures.py --apply --question 問題/午前/R3春期/16.md
  python3 scripts/fetch_question_figures.py --apply --dry-run --question 問題/午前/R3春期/16.md

- 見出し1行目の ap-siken URL から HTML を取得（urllib。AI の WebFetch 禁止とは別）
- 図が無い問題は「図なし」で終了（ワーカーが curl 要否を判断する必要はない）
- 画像は assets/問題/{試験パス}/{問番号}/ に保存
- ap-question / ap-choice-text / ap-explanation に class="ap-fig" の img を挿入
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))

from glossary_lib import (
    QUESTIONS_DIR_NAME,
    QUESTION_TAG,
    normalize_question_ref,
    question_note_path,
)

ASSETS_DIR_NAME = "assets"
CHOICE_SUFFIX = {"a": "ア", "i": "イ", "u": "ウ", "e": "エ"}
QUESTION_URL_RE = re.compile(
    r"^#\s+\[[^\]]+\]\((https://www\.ap-siken\.com/kakomon/[^)]+)\)\s*$",
    re.MULTILINE,
)
AP_QUIZ_RE = re.compile(
    r"(<div\s+class=\"ap-quiz\">)(.*?)(</div>\s*)$",
    re.DOTALL | re.IGNORECASE,
)
AP_QUESTION_RE = re.compile(
    r"(<p\s+class=\"ap-question\"[^>]*>)(.*?)(</p>)",
    re.DOTALL | re.IGNORECASE,
)
AP_CHOICE_TEXT_RE = re.compile(
    r'(<div\s+class="ap-choice-text">)([アイウエ])　(.*?)(</div>)',
    re.DOTALL | re.IGNORECASE,
)
AP_EXPLANATION_RE = re.compile(
    r"(<div\s+class=\"ap-explanation\"[^>]*>)(.*?)(</div>)",
    re.DOTALL | re.IGNORECASE,
)
IMG_TAG_RE = re.compile(r"<img\s+[^>]*>", re.IGNORECASE)
IMG_SRC_RE = re.compile(r'src="([^"]+)"', re.IGNORECASE)
IMG_WIDTH_RE = re.compile(r'width="(\d+)"', re.IGNORECASE)
IMG_HEIGHT_RE = re.compile(r'height="(\d+)"', re.IGNORECASE)
FIG_PLACEHOLDER_RE = re.compile(
    r"<br>?\s*（[^）]*(?:元ページ|ap-siken|図を参照)[^）]*）|"
    r"（[^）]*(?:グラフの選択肢|元ページの図)[^）]*）",
)
AP_FIG_RE = re.compile(
    r'<img\s+class="ap-fig"[^>]*src="([^"]+)"[^>]*>',
    re.IGNORECASE,
)
QUESTION_NUM_FROM_URL_RE = re.compile(r"/q(\d+)\.html", re.IGNORECASE)
FIGURE_IMG_NAME_RE = re.compile(
    r"^\d+(?:_\d+)?[aeiu]?\.(png|gif|jpe?g)$",
    re.IGNORECASE,
)
SKIP_IMG_RE = re.compile(r"(?:titlelogo|ogimage|favicon)", re.IGNORECASE)


class Figure:
    def __init__(
        self,
        *,
        src_path: str,
        filename: str,
        width: str | None,
        height: str | None,
        slot: str,
        kana: str | None = None,
    ) -> None:
        self.src_path = src_path
        self.filename = filename
        self.width = width
        self.height = height
        self.slot = slot  # question | choice | explanation
        self.kana = kana


def vault_root() -> Path:
    return Path(__file__).resolve().parents[1]


def extract_ap_siken_url(text: str) -> str:
    m = QUESTION_URL_RE.search(text)
    if not m:
        raise SystemExit("見出し1行目に ap-siken の URL がありません（# […](https://www.ap-siken.com/…)）")
    return m.group(1)


def question_id_from_url(url: str) -> tuple[int, str, str]:
    """(数値, 非ゼロ埋め, 2桁ゼロ埋め) 例: 5 → (5, "5", "05")"""
    m = QUESTION_NUM_FROM_URL_RE.search(url)
    if not m:
        raise SystemExit(f"問番号を URL から取得できません: {url}")
    n = int(m.group(1))
    return n, str(n), f"{n:02d}"


def matches_question_image(filename: str, unpadded: str, padded: str) -> bool:
    stem = Path(filename).stem
    if stem in (unpadded, padded):
        return True
    for prefix in (unpadded, padded):
        if stem.startswith(f"{prefix}_"):
            return True
        if re.fullmatch(rf"{re.escape(prefix)}[aeiu]", stem, re.IGNORECASE):
            return True
    return False


def natural_sort_key(filename: str) -> list:
    stem = Path(filename).stem
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", stem)]


def fetch_html(url: str) -> str:
    req = Request(url, headers={"User-Agent": "obsidian-ap-vault/1.0 (fetch_question_figures)"})
    try:
        with urlopen(req, timeout=30) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except (HTTPError, URLError) as e:
        raise SystemExit(f"HTML の取得に失敗: {url}\n  {e}") from e


def slice_between(html: str, start_pat: str, end_pat: str) -> str:
    start = re.search(start_pat, html, re.IGNORECASE | re.DOTALL)
    if not start:
        return ""
    begin = start.end()
    end = re.search(end_pat, html[begin:], re.IGNORECASE | re.DOTALL)
    return html[begin : begin + end.start()] if end else html[begin:]


def parse_img_tag(tag: str) -> tuple[str, str | None, str | None] | None:
    src_m = IMG_SRC_RE.search(tag)
    if not src_m:
        return None
    src = src_m.group(1)
    if SKIP_IMG_RE.search(src):
        return None
    w = IMG_WIDTH_RE.search(tag)
    h = IMG_HEIGHT_RE.search(tag)
    return src, w.group(1) if w else None, h.group(1) if h else None


def normalize_img_src(src: str, page_url: str) -> str:
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        parsed = urlparse(page_url)
        return f"{parsed.scheme}://{parsed.netloc}{src}"
    return urljoin(page_url, src)


def figure_filename(src: str) -> str | None:
    path = urlparse(src).path
    name = Path(path).name
    if FIGURE_IMG_NAME_RE.match(name):
        return name
    if "/" in path:
        tail = path.split("/")[-2:]
        if len(tail) == 2 and tail[0] == "img" and FIGURE_IMG_NAME_RE.match(tail[1]):
            return tail[1]
    return None


def collect_figures(html: str, page_url: str, unpadded: str, padded: str) -> list[Figure]:
    mondai = slice_between(html, r'<div id="mondai"[^>]*>', r'<div class="ansbg"')
    kaisetsu = slice_between(html, r'<div[^>]*id="kaisetsu"[^>]*>', r"</div>\s*<div")
    first_ansbg = slice_between(html, r'<div class="ansbg"[^>]*>\s*<ul class="selectList', r"</ul>")
    choice_block = first_ansbg if first_ansbg else ""

    figures: list[Figure] = []
    seen: set[str] = set()

    def add_from_block(block: str, slot: str, kana: str | None = None) -> None:
        for tag in IMG_TAG_RE.findall(block):
            parsed = parse_img_tag(tag)
            if not parsed:
                continue
            src, width, height = parsed
            full = normalize_img_src(src, page_url)
            fname = figure_filename(src)
            if not fname or fname in seen:
                continue
            if not matches_question_image(fname, unpadded, padded):
                continue
            seen.add(fname)
            figures.append(
                Figure(
                    src_path=full,
                    filename=fname,
                    width=width,
                    height=height,
                    slot=slot,
                    kana=kana,
                )
            )

    add_from_block(mondai, "question")
    for suffix, kana in CHOICE_SUFFIX.items():
        span = re.search(
            rf'<span[^>]*id="select_{suffix}"[^>]*>(.*?)</span>',
            choice_block,
            re.DOTALL | re.IGNORECASE,
        )
        if span and IMG_TAG_RE.search(span.group(1)):
            add_from_block(span.group(1), "choice", kana)
    add_from_block(kaisetsu, "explanation")
    return figures


def assets_dir_for(qid: str, root: Path) -> Path:
    return root / ASSETS_DIR_NAME / QUESTIONS_DIR_NAME / Path(qid)


def rel_src_from_note(note_path: Path, asset_file: Path) -> str:
    rel = os.path.relpath(asset_file.resolve(), note_path.parent.resolve())
    return Path(rel).as_posix()


def build_img_tag(rel_src: str, alt: str, width: str | None, height: str | None) -> str:
    parts = [
        '<img class="ap-fig"',
        f'src="{rel_src}"',
        f'alt="{alt}"',
    ]
    if width:
        parts.append(f'width="{width}"')
    if height:
        parts.append(f'height="{height}"')
    parts.append(">")
    return " ".join(parts)


def download(url: str, dest: Path, dry_run: bool) -> None:
    if dest.is_file() and not dry_run:
        return
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": "obsidian-ap-vault/1.0 (fetch_question_figures)"})
    try:
        with urlopen(req, timeout=30) as resp:
            dest.write_bytes(resp.read())
    except (HTTPError, URLError) as e:
        raise SystemExit(f"画像の取得に失敗: {url}\n  {e}") from e


def strip_placeholders(html: str) -> str:
    return FIG_PLACEHOLDER_RE.sub("", html)


def has_fig_for_file(html: str, filename: str) -> bool:
    return filename in html or Path(filename).name in html


def inject_question(body: str, imgs: list[Figure], rel_by_file: dict[str, str]) -> str:
    if not imgs:
        return body

    def repl(m: re.Match[str]) -> str:
        inner = strip_placeholders(m.group(2))
        for fig in imgs:
            if has_fig_for_file(inner, fig.filename):
                continue
            tag = build_img_tag(
                rel_by_file[fig.filename],
                "問題図",
                fig.width,
                fig.height,
            )
            inner = inner.rstrip() + "<br>" + tag
        return m.group(1) + inner + m.group(3)

    return AP_QUESTION_RE.sub(repl, body, count=1)


def inject_choices(body: str, by_kana: dict[str, Figure], rel_by_file: dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        kana = m.group(2)
        inner = m.group(3).strip()
        fig = by_kana.get(kana)
        if not fig:
            return m.group(0)
        if has_fig_for_file(inner, fig.filename):
            inner = strip_placeholders(inner)
            return f'{m.group(1)}{kana}　{inner}{m.group(4)}'
        tag = build_img_tag(
            rel_by_file[fig.filename],
            f"選択肢{kana}の図",
            fig.width,
            fig.height,
        )
        return f'{m.group(1)}{kana}　{tag}{m.group(4)}'

    return AP_CHOICE_TEXT_RE.sub(repl, body)


def inject_explanation(body: str, imgs: list[Figure], rel_by_file: dict[str, str]) -> str:
    if not imgs:
        return body

    imgs_sorted = sorted(imgs, key=lambda f: natural_sort_key(f.filename))

    def repl(m: re.Match[str]) -> str:
        inner = strip_placeholders(m.group(2))
        pending = [f for f in imgs_sorted if not has_fig_for_file(inner, f.filename)]
        if not pending:
            return m.group(1) + inner + m.group(3)

        paras = list(re.finditer(r"(<p>.*?</p>)", inner, re.DOTALL))
        if not paras:
            for fig in pending:
                tag = build_img_tag(
                    rel_by_file[fig.filename], "解説図", fig.width, fig.height
                )
                inner = inner.rstrip() + f"<p>{tag}</p>"
            return m.group(1) + inner + m.group(3)

        strong_idxs = [i for i, p in enumerate(paras) if "<strong>" in p.group(1)]
        if len(pending) == 1 and not strong_idxs:
            # 解説ブロック先頭の1枚（模式図など。ap-siken の kaisetsu 冒頭配置）
            target_indices = [0]
        elif len(strong_idxs) >= len(pending):
            target_indices = strong_idxs[: len(pending)]
        else:
            start = max(0, len(paras) - len(pending))
            target_indices = list(range(start, len(paras)))[: len(pending)]

        img_by_para = dict(zip(target_indices, pending))
        parts: list[str] = []
        last = 0
        for i, pm in enumerate(paras):
            parts.append(inner[last : pm.start()])
            p_html = pm.group(1)
            fig = img_by_para.get(i)
            if fig:
                tag = build_img_tag(
                    rel_by_file[fig.filename], "解説図", fig.width, fig.height
                )
                parts.append(p_html + f"<p>{tag}</p>")
            else:
                parts.append(p_html)
            last = pm.end()
        parts.append(inner[last:])
        inner = "".join(parts)
        return m.group(1) + inner + m.group(3)

    return AP_EXPLANATION_RE.sub(repl, body, count=1)


def patch_note(text: str, figures: list[Figure], rel_by_file: dict[str, str]) -> str:
    m = AP_QUIZ_RE.search(text)
    if not m:
        raise SystemExit("ap-quiz ブロックが見つかりません")

    body = m.group(2)
    q_imgs = [f for f in figures if f.slot == "question"]
    c_imgs = {f.kana: f for f in figures if f.slot == "choice" and f.kana}
    e_imgs = [f for f in figures if f.slot == "explanation"]

    body = inject_question(body, q_imgs, rel_by_file)
    body = inject_choices(body, c_imgs, rel_by_file)
    body = inject_explanation(body, e_imgs, rel_by_file)

    return text[: m.start(2)] + body + text[m.end(2) :]


def print_report(
    *,
    note_path: str,
    url: str,
    figures: list[Figure],
    assets_rel: str,
    apply: bool,
    dry_run: bool,
    downloaded: list[str],
    patched: bool,
) -> None:
    print(f"対象: {note_path}")
    print(f"ap-siken: {url}\n")
    if not figures:
        print("図なし（ap-siken の問題・選択肢・解説に img/問番号*.png がありません）")
        return
    print("## 検出した図\n")
    for f in figures:
        where = {"question": "問題文", "choice": f"選択肢{f.kana}", "explanation": "解説"}[f.slot]
        print(f"  - {f.filename} → {where} ({assets_rel}/{f.filename})")
    print()
    if downloaded:
        print("## 取得\n")
        for name in downloaded:
            print(f"  - {name}")
        print()
    if apply:
        if dry_run:
            print("(dry-run: ノート・画像は未更新)")
        elif patched:
            print("ノートを更新しました")
        else:
            print("ノートは変更なし（埋め込み済み）")
    else:
        print("埋め込むには --apply を付けて再実行してください")


def main() -> None:
    parser = argparse.ArgumentParser(description="過去問ノートに ap-siken の図を取得・埋め込み")
    parser.add_argument(
        "--question",
        metavar="PATH",
        required=True,
        help="問題ノート（例: 問題/午前/R3春期/14.md）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="画像をダウンロードしノートに img を挿入",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="--apply 時はファイルを書き換えない",
    )
    args = parser.parse_args()
    if args.dry_run and not args.apply:
        raise SystemExit("--dry-run は --apply と併用")

    root = vault_root()
    questions_dir = root / QUESTIONS_DIR_NAME
    qid = normalize_question_ref(args.question, questions_dir, root)
    note_path = question_note_path(qid, questions_dir)
    if not note_path.is_file():
        raise SystemExit(f"問題ノートが見つかりません: {QUESTIONS_DIR_NAME}/{qid}.md")
    text = note_path.read_text(encoding="utf-8")
    if QUESTION_TAG not in text:
        raise SystemExit(f"{QUESTION_TAG} がありません: {QUESTIONS_DIR_NAME}/{qid}.md")

    url = extract_ap_siken_url(text)
    _qn, unpadded, padded = question_id_from_url(url)
    html = fetch_html(url)
    figures = collect_figures(html, url, unpadded, padded)

    assets_dir = assets_dir_for(qid, root)
    assets_rel = f"{ASSETS_DIR_NAME}/{QUESTIONS_DIR_NAME}/{qid}"
    rel_by_file: dict[str, str] = {}
    downloaded: list[str] = []

    for fig in figures:
        dest = assets_dir / fig.filename
        rel_by_file[fig.filename] = rel_src_from_note(note_path, dest)
        if args.apply:
            if not args.dry_run:
                download(fig.src_path, dest, dry_run=False)
            if not dest.is_file() and not args.dry_run:
                downloaded.append(fig.filename)
            elif args.dry_run:
                downloaded.append(f"{fig.filename} (dry-run)")
            else:
                downloaded.append(fig.filename)
        else:
            rel_by_file[fig.filename] = rel_src_from_note(note_path, dest)

    new_text = text
    patched = False
    if args.apply and figures:
        new_text = patch_note(text, figures, rel_by_file)
        patched = new_text != text
        if patched and not args.dry_run:
            note_path.write_text(new_text, encoding="utf-8")

    print_report(
        note_path=f"{QUESTIONS_DIR_NAME}/{qid}.md",
        url=url,
        figures=figures,
        assets_rel=assets_rel,
        apply=args.apply,
        dry_run=args.dry_run,
        downloaded=downloaded if args.apply else [],
        patched=patched,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
