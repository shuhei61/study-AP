#!/usr/bin/env python3
"""ap-siken 過去問ページの取得（本文テキスト出力・図の埋め込み）。

使い方:
  python3 scripts/fetch_question_figures.py --print-source --question 問題/午前/R3春期/7.md
  python3 scripts/fetch_question_figures.py --question 問題/午前/R3春期/14.md
  python3 scripts/fetch_question_figures.py --apply --question 問題/午前/R3春期/16.md
  python3 scripts/fetch_question_figures.py --print-source --apply --question 問題/午前/R3春期/7.md

- --print-source … HTTP で取得し workspace/ap-siken-html/ に一次 HTML を保存して標準出力
- --apply / 図検出のみ … 一次 HTML のみ使用（HTTP しない。無ければエラー）
- --print-source --apply … 取得1回で保存・出力・図埋め込み
- 一次 HTML の削除 … 親が全問完了後に scripts/clear_ap_siken_html_cache.py（オーケストレーター）
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from html import escape, unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ap_siken_kakomon import (
    CHOICE_NOTE_RE,
    CHOICE_SUFFIX,
    USER_AGENT,
    extract_ap_siken_url_from_note,
    fetch_and_cache_html,
    format_kakomon_page_for_ai,
    html_fragment_to_text,
    load_cached_html,
    parse_kakomon_page,
    question_id_from_url,
    slice_between,
    slice_kaisetsu,
    validate_kakomon_url,
)
from ap_siken_kakomon import KakomonUrlError
from glossary_lib import (
    QUESTIONS_DIR_NAME,
    QUESTION_TAG,
    normalize_question_ref,
    question_note_path,
)

ASSETS_DIR_NAME = "assets"
AP_QUIZ_RE = re.compile(
    r"(<div\s+class=\"ap-quiz\">)(.*?)(</div>\s*)$",
    re.DOTALL | re.IGNORECASE,
)
AP_QUESTION_RE = re.compile(
    r"(<p\s+class=\"ap-question\"[^>]*>)(.*?)(</p>)",
    re.DOTALL | re.IGNORECASE,
)
AP_CHOICE_TEXT_RE = re.compile(
    r'(<div\s+class="ap-choice-text">)([アイウエ])　?(.*?)(</div>)',
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
# 問番号.png / 29_1.png / 選択肢 29a.png / 解説 29ii.png / 第2検証 23iii.png など
FIGURE_IMG_NAME_RE = re.compile(
    r"^\d+(?:_\d+)?(?:[aeiu]{1,3})?\.(png|gif|jpe?g)$",
    re.IGNORECASE,
)
_CHOICE_LETTER_ORDER = {"a": 0, "i": 1, "u": 2, "e": 3}
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
        self.slot = slot  # question | choice | choice_table | explanation
        self.kana = kana


def vault_root() -> Path:
    return Path(__file__).resolve().parents[1]


def matches_question_image(filename: str, unpadded: str, padded: str) -> bool:
    stem = Path(filename).stem
    if stem in (unpadded, padded):
        return True
    for prefix in (unpadded, padded):
        if stem.startswith(f"{prefix}_"):
            return True
        # 1〜3連（例: 23a / 23aa / 23iii・23uuu＝第2検証図）
        if re.fullmatch(rf"{re.escape(prefix)}[aeiu]{{1,3}}", stem, re.IGNORECASE):
            return True
    return False


def natural_sort_key(filename: str) -> list:
    """29_1 → 29ii → 29uu → 29iii のように、連番サフィックスを aeiu 系より先に並べる。"""
    stem = Path(filename).stem
    m = re.match(r"^(\d+)(?:_(\d+))?([aeiu]*)$", stem, re.IGNORECASE)
    if not m:
        return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", stem)]
    qnum = int(m.group(1))
    sub = m.group(2)
    suffix = (m.group(3) or "").lower()
    if sub is not None:
        return (qnum, 0, int(sub), "")
    if not suffix:
        return (qnum, 1, 0, "")
    if len(suffix) == 1:
        return (qnum, 2, _CHOICE_LETTER_ORDER.get(suffix, 9), suffix)
    if len(suffix) == 2 and suffix[0] == suffix[1]:
        return (qnum, 3, _CHOICE_LETTER_ORDER.get(suffix[0], 9), suffix)
    if len(suffix) == 3 and len(set(suffix)) == 1:
        return (qnum, 4, _CHOICE_LETTER_ORDER.get(suffix[0], 9), suffix)
    return (qnum, 5, suffix)


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
    kaisetsu = slice_kaisetsu(html)
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
    # selectList: 4肢が1枚の表画像（例: 29a.png）のみで HTML テキストが無い問題
    # （choice_block は ansbg+selectList の slice 成功時のみ非空）
    if choice_block:
        for tag in IMG_TAG_RE.findall(choice_block):
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
                    slot="choice_table",
                )
            )
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
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=30) as resp:
            dest.write_bytes(resp.read())
    except (HTTPError, URLError) as e:
        raise SystemExit(f"画像の取得に失敗: {url}\n  {e}") from e


def strip_placeholders(html: str) -> str:
    return FIG_PLACEHOLDER_RE.sub("", html)


def has_fig_for_file(html: str, filename: str) -> bool:
    return filename in html or Path(filename).name in html


IMG_MARGIN_DIV_RE = re.compile(
    r'<div\s+class="img_margin"[^>]*>.*?</div>',
    re.DOTALL | re.IGNORECASE,
)


def extract_kaisetsu_li_segments(kaisetsu: str) -> list[tuple[str, str | None]]:
    """解説 #kaisetsu 内の ul>li.li[aeiu] から (テキスト, 画像ファイル名) を aeiu 順に返す。"""
    segments: list[tuple[str, str | None]] = []
    for m in CHOICE_NOTE_RE.finditer(kaisetsu):
        inner = m.group(2)
        img_fname: str | None = None
        for tag in IMG_TAG_RE.findall(inner):
            parsed = parse_img_tag(tag)
            if not parsed:
                continue
            img_fname = figure_filename(parsed[0])
            if img_fname:
                break
        text_html = IMG_MARGIN_DIV_RE.sub("", inner)
        text = html_fragment_to_text(text_html)
        if text or img_fname:
            segments.append((text, img_fname))
    return segments


def explanation_fig_alt(filename: str) -> str:
    stem = Path(filename).stem
    parts = stem.split("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return f"解説図 {parts[1]}"
    return "解説図"


def append_explanation_figure_paragraphs(
    inner: str,
    figures: list[Figure],
    rel_by_file: dict[str, str],
    *,
    text: str = "",
) -> str:
    for fig in figures:
        if has_fig_for_file(inner, fig.filename):
            continue
        tag = build_img_tag(
            rel_by_file[fig.filename],
            explanation_fig_alt(fig.filename),
            fig.width,
            fig.height,
        )
        if text:
            body = f"{escape(text)}<br>{tag}"
        else:
            body = tag
        inner += f"<p>{body}</p>"
    return inner


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


def inject_choice_table(body: str, imgs: list[Figure], rel_by_file: dict[str, str]) -> str:
    """選択肢表を ap-question 末尾（問題図の直後）に挿入。"""
    if not imgs:
        return body

    def repl(m: re.Match[str]) -> str:
        inner = m.group(2)
        if any(has_fig_for_file(inner, f.filename) for f in imgs):
            return m.group(1) + inner + m.group(3)
        tags = []
        for fig in imgs:
            tags.append(
                build_img_tag(
                    rel_by_file[fig.filename],
                    "選択肢の組合せ表",
                    fig.width,
                    fig.height,
                )
            )
        block = "<br>" + "".join(tags)
        return m.group(1) + inner.rstrip() + block + m.group(3)

    return AP_QUESTION_RE.sub(repl, body, count=1)


def inject_explanation(
    body: str,
    imgs: list[Figure],
    rel_by_file: dict[str, str],
    *,
    kaisetsu: str = "",
) -> str:
    if not imgs:
        return body

    imgs_sorted = sorted(imgs, key=lambda f: natural_sort_key(f.filename))
    fig_by_name = {f.filename: f for f in imgs_sorted}
    li_segments = extract_kaisetsu_li_segments(kaisetsu) if kaisetsu else []
    li_has_images = li_segments and any(fname for _, fname in li_segments)

    def repl(m: re.Match[str]) -> str:
        inner = strip_placeholders(m.group(2))
        pending = [f for f in imgs_sorted if not has_fig_for_file(inner, f.filename)]
        if not pending:
            return m.group(1) + inner + m.group(3)

        if li_has_images:
            li_fnames = {fname for _, fname in li_segments if fname}
            pending_non_li = [f for f in pending if f.filename not in li_fnames]
            for text, fname in li_segments:
                if not fname or fname not in fig_by_name:
                    continue
                if has_fig_for_file(inner, fname):
                    if text and text not in inner:
                        img_in_p = re.search(
                            rf"(<p[^>]*>)(.*?<img[^>]*{re.escape(fname)}[^>]*>.*?</p>)",
                            inner,
                            re.DOTALL | re.IGNORECASE,
                        )
                        if img_in_p and escape(text) not in img_in_p.group(2):
                            inner = (
                                inner[: img_in_p.start()]
                                + img_in_p.group(1)
                                + escape(text)
                                + "<br>"
                                + img_in_p.group(2)
                                + inner[img_in_p.end() :]
                            )
                        else:
                            inner += f"<p>{escape(text)}</p>"
                    continue
                fig = fig_by_name[fname]
                tag = build_img_tag(
                    rel_by_file[fig.filename],
                    explanation_fig_alt(fig.filename),
                    fig.width,
                    fig.height,
                )
                if text:
                    inner += f"<p>{escape(text)}<br>{tag}</p>"
                else:
                    inner += f"<p>{tag}</p>"
            pending = pending_non_li

        if pending:
            paras = list(re.finditer(r"(<p>.*?</p>)", inner, re.DOTALL))
            if not paras:
                inner = append_explanation_figure_paragraphs(
                    inner, pending, rel_by_file
                )
            else:
                strong_idxs = [
                    i for i, p in enumerate(paras) if "<strong>" in p.group(1)
                ]
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
                            rel_by_file[fig.filename],
                            explanation_fig_alt(fig.filename),
                            fig.width,
                            fig.height,
                        )
                        parts.append(p_html + f"<p>{tag}</p>")
                    else:
                        parts.append(p_html)
                    last = pm.end()
                parts.append(inner[last:])
                inner = "".join(parts)
                still_pending = [
                    f
                    for f in pending
                    if not has_fig_for_file(inner, f.filename)
                ]
                inner = append_explanation_figure_paragraphs(
                    inner, still_pending, rel_by_file
                )

        return m.group(1) + inner + m.group(3)

    return AP_EXPLANATION_RE.sub(repl, body, count=1)


def patch_note(
    text: str,
    figures: list[Figure],
    rel_by_file: dict[str, str],
    *,
    kaisetsu: str = "",
) -> str:
    m = AP_QUIZ_RE.search(text)
    if not m:
        raise SystemExit("ap-quiz ブロックが見つかりません")

    body = m.group(2)
    q_imgs = [f for f in figures if f.slot == "question"]
    c_imgs = {f.kana: f for f in figures if f.slot == "choice" and f.kana}
    t_imgs = [f for f in figures if f.slot == "choice_table"]
    e_imgs = [f for f in figures if f.slot == "explanation"]

    body = inject_question(body, q_imgs, rel_by_file)
    body = inject_choices(body, c_imgs, rel_by_file)
    body = inject_choice_table(body, t_imgs, rel_by_file)
    body = inject_explanation(body, e_imgs, rel_by_file, kaisetsu=kaisetsu)

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
        where = {
            "question": "問題文",
            "choice": f"選択肢{f.kana}",
            "choice_table": "選択肢表（4肢まとめ）",
            "explanation": "解説",
        }[f.slot]
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
            print(
                "ノートは変更なし（埋め込み済み、または ap-choice-text の形式不一致）"
            )
    else:
        print("埋め込むには --apply を付けて再実行してください")


def resolve_url(args: argparse.Namespace, text: str | None) -> str:
    if args.url:
        try:
            validate_kakomon_url(args.url)
        except KakomonUrlError as e:
            raise SystemExit(str(e)) from e
        return args.url.strip()
    if text is None:
        raise SystemExit("--question または --url を指定してください")
    return extract_ap_siken_url_from_note(text)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ap-siken 過去問（kakomon）の HTML 取得・本文出力・図埋め込み"
    )
    parser.add_argument(
        "--question",
        metavar="PATH",
        help="問題ノート（例: 問題/午前/R3春期/14.md）。見出しから URL を読む",
    )
    parser.add_argument(
        "--url",
        metavar="URL",
        help="見出しの代わりに kakomon URL を直接指定（https://www.ap-siken.com/kakomon/… のみ）",
    )
    parser.add_argument(
        "--print-source",
        action="store_true",
        help="問題文・分類・選択肢・解説を標準出力（ノート作成用）",
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
    if not args.question and not args.url:
        raise SystemExit("--question または --url のいずれかが必要です")
    if args.dry_run and not args.apply:
        raise SystemExit("--dry-run は --apply と併用")
    detect_only = not args.print_source and not args.apply
    if detect_only and not args.question:
        raise SystemExit("図の検出のみのときは --question が必要です")
    if detect_only and args.url:
        raise SystemExit("図の検出のみのときは --url は使えません（--question を指定）")
    if not detect_only and not args.print_source and not args.apply:
        raise SystemExit("--print-source または --apply のいずれかが必要です")

    root = vault_root()
    questions_dir = root / QUESTIONS_DIR_NAME
    text: str | None = None
    note_path: Path | None = None
    qid = ""

    if args.question:
        qid = normalize_question_ref(args.question, questions_dir, root)
        note_path = question_note_path(qid, questions_dir)
        if not note_path.is_file():
            raise SystemExit(f"問題ノートが見つかりません: {QUESTIONS_DIR_NAME}/{qid}.md")
        text = note_path.read_text(encoding="utf-8")
        if args.apply and QUESTION_TAG not in text:
            raise SystemExit(f"{QUESTION_TAG} がありません: {QUESTIONS_DIR_NAME}/{qid}.md")

    url = resolve_url(args, text)
    _qn, unpadded, padded = question_id_from_url(url)

    needs_network = bool(args.print_source)
    if needs_network:
        html, cache_path = fetch_and_cache_html(url, root)
        print(f"HTML 一次ファイル: {cache_path.relative_to(root).as_posix()}", file=sys.stderr)
    else:
        html, cache_path = load_cached_html(url, root)
        print(f"HTML 一次ファイルを使用: {cache_path.relative_to(root).as_posix()}", file=sys.stderr)

    if args.print_source:
        page = parse_kakomon_page(html, url)
        print(format_kakomon_page_for_ai(page), end="")

    need_figures = args.apply or detect_only
    figures = collect_figures(html, url, unpadded, padded) if need_figures else []

    if detect_only or args.apply:
        if note_path is None:
            raise SystemExit("図の検出・埋め込みには --question が必要です")
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

        if args.apply:
            assert text is not None
            new_text = text
            patched = False
            if figures:
                kaisetsu = slice_kaisetsu(html)
                new_text = patch_note(
                    text, figures, rel_by_file, kaisetsu=kaisetsu
                )
                patched = new_text != text
                if patched and not args.dry_run:
                    note_path.write_text(new_text, encoding="utf-8")

            if args.print_source:
                print()
            print_report(
                note_path=f"{QUESTIONS_DIR_NAME}/{qid}.md",
                url=url,
                figures=figures,
                assets_rel=assets_rel,
                apply=True,
                dry_run=args.dry_run,
                downloaded=downloaded,
                patched=patched,
            )
        else:
            print_report(
                note_path=f"{QUESTIONS_DIR_NAME}/{qid}.md",
                url=url,
                figures=figures,
                assets_rel=assets_rel,
                apply=False,
                dry_run=False,
                downloaded=[],
                patched=False,
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
