"""ap-siken 過去問（kakomon）ページの URL 検証・HTML 取得・本文抽出。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

USER_AGENT = "obsidian-ap-vault/1.0 (ap_siken_kakomon)"

# 過去問 HTML の一次保管（.gitignore）。--print-source で書き、--apply はここだけ読む。
HTML_CACHE_DIR_NAME = "workspace/ap-siken-html"

# 見出し1行目の Markdown リンク（kakomon のみ）
QUESTION_HEADING_URL_RE = re.compile(
    r"^#\s+\[[^\]]+\]\((https://www\.ap-siken\.com/kakomon/[^)]+)\)\s*$",
    re.MULTILINE,
)

# 許可 URL: https://www.ap-siken.com/kakomon/{試験スラッグ}/q{問番号}.html
KAKOMON_URL_ALLOWED_RE = re.compile(
    r"^https://www\.ap-siken\.com/kakomon/[0-9]{2}_[a-z0-9]+/q[0-9]+\.html$",
    re.IGNORECASE,
)

QUESTION_NUM_FROM_URL_RE = re.compile(r"/q(\d+)\.html", re.IGNORECASE)

CHOICE_SUFFIX = {"a": "ア", "i": "イ", "u": "ウ", "e": "エ"}
CHOICE_NOTE_RE = re.compile(
    r'<li\s+class="li([aeiu])"[^>]*>(.*?)</li>',
    re.DOTALL | re.IGNORECASE,
)
SELECT_SPAN_RE = re.compile(
    r'<span[^>]*id="select_([aeiu])"[^>]*>(.*?)</span>',
    re.DOTALL | re.IGNORECASE,
)
IMG_TAG_RE = re.compile(r"<img\s+[^>]*>", re.IGNORECASE)
CLASSIFICATION_RE = re.compile(
    r"<h3>\s*分類\s*:\s*</h3>\s*<div>(.*?)</div>",
    re.DOTALL | re.IGNORECASE,
)
ANSWER_RE = re.compile(
    r'<span\s+id="answerChar"[^>]*>([^<]+)</span>',
    re.IGNORECASE,
)


class KakomonUrlError(ValueError):
    pass


@dataclass
class KakomonPage:
    url: str
    question_num: int
    classification: str
    correct_answer: str
    question_text: str
    choices: dict[str, str] = field(default_factory=dict)
    choice_notes: dict[str, str] = field(default_factory=dict)
    explanation: str = ""
    figure_hints: list[str] = field(default_factory=list)


def validate_kakomon_url(url: str) -> None:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "www.ap-siken.com":
        raise KakomonUrlError(
            f"許可されていないホストです（www.ap-siken.com の https のみ）: {url}"
        )
    if not KAKOMON_URL_ALLOWED_RE.match(url):
        raise KakomonUrlError(
            "許可されていない URL です。"
            " https://www.ap-siken.com/kakomon/{試験スラッグ}/q{問番号}.html のみ取得できます: "
            f"{url}"
        )


def extract_ap_siken_url_from_note(text: str) -> str:
    m = QUESTION_HEADING_URL_RE.search(text)
    if not m:
        raise SystemExit(
            "見出し1行目に ap-siken の URL がありません（# […](https://www.ap-siken.com/kakomon/…)）"
        )
    url = m.group(1)
    try:
        validate_kakomon_url(url)
    except KakomonUrlError as e:
        raise SystemExit(str(e)) from e
    return url


def question_id_from_url(url: str) -> tuple[int, str, str]:
    """(数値, 非ゼロ埋め, 2桁ゼロ埋め) 例: 5 → (5, "5", "05")"""
    m = QUESTION_NUM_FROM_URL_RE.search(url)
    if not m:
        raise SystemExit(f"問番号を URL から取得できません: {url}")
    n = int(m.group(1))
    return n, str(n), f"{n:02d}"


def fetch_kakomon_html(url: str) -> str:
    """ap-siken へ HTTP（--print-source 時のみ。--apply からは呼ばない）。"""
    validate_kakomon_url(url)
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=30) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except (HTTPError, URLError) as e:
        raise SystemExit(f"HTML の取得に失敗: {url}\n  {e}") from e


def html_cache_path(url: str, vault_root: Path) -> Path:
    validate_kakomon_url(url)
    path = urlparse(url).path.lstrip("/")
    return vault_root / HTML_CACHE_DIR_NAME / path


def write_html_cache(cache_path: Path, html: str) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(html, encoding="utf-8")


def read_html_cache(cache_path: Path) -> str:
    if not cache_path.is_file():
        rel = cache_path.as_posix()
        raise SystemExit(
            f"HTML 一次ファイルがありません: {rel}\n"
            "  先に python3 scripts/fetch_question_figures.py --print-source --question … を実行してください"
        )
    return cache_path.read_text(encoding="utf-8")


def fetch_and_cache_html(url: str, vault_root: Path) -> tuple[str, Path]:
    """HTTP して workspace 配下に保存し、内容を返す。"""
    cache_path = html_cache_path(url, vault_root)
    html = fetch_kakomon_html(url)
    write_html_cache(cache_path, html)
    return html, cache_path


def load_cached_html(url: str, vault_root: Path) -> tuple[str, Path]:
    """一次ファイルのみ（HTTP しない）。"""
    cache_path = html_cache_path(url, vault_root)
    return read_html_cache(cache_path), cache_path


def slice_between(html: str, start_pat: str, end_pat: str) -> str:
    start = re.search(start_pat, html, re.IGNORECASE | re.DOTALL)
    if not start:
        return ""
    begin = start.end()
    end = re.search(end_pat, html[begin:], re.IGNORECASE | re.DOTALL)
    return html[begin : begin + end.start()] if end else html[begin:]


KAISETSU_OPEN_RE = re.compile(
    r'<div[^>]*\bid=["\']?kaisetsu["\']?[^>]*>',
    re.IGNORECASE,
)
_BALANCED_DIV_TAG_RE = re.compile(r"</div\s*>|<div\s", re.IGNORECASE)


def _slice_balanced_div_inner(html: str, inner_start: int) -> str:
    """opening <div> の直後から、対応する </div> の手前まで。"""
    depth = 1
    for m in _BALANCED_DIV_TAG_RE.finditer(html, inner_start):
        if m.group(0).lower().startswith("</div"):
            depth -= 1
            if depth == 0:
                return html[inner_start : m.start()]
        else:
            depth += 1
    return html[inner_start:]


def slice_kaisetsu(html: str) -> str:
    """#kaisetsu ブロックの内側（img_margin 等の入れ子 div を含む）。"""
    m = KAISETSU_OPEN_RE.search(html)
    if not m:
        return ""
    return _slice_balanced_div_inner(html, m.end())


def html_fragment_to_text(fragment: str) -> str:
    if not fragment:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.IGNORECASE)
    text = IMG_TAG_RE.sub("[画像]", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


def _choice_text_from_span(inner: str) -> str:
    if IMG_TAG_RE.search(inner) and not html_fragment_to_text(inner.replace("[画像]", "")):
        imgs = IMG_TAG_RE.findall(inner)
        names = []
        for tag in imgs:
            m = re.search(r'src="[^"]*/([^"/]+)"', tag, re.IGNORECASE)
            names.append(m.group(1) if m else "画像")
        return "[画像のみ: " + ", ".join(names) + "]"
    return html_fragment_to_text(inner)


def parse_kakomon_page(html: str, url: str) -> KakomonPage:
    qn, _, _ = question_id_from_url(url)

    mondai = slice_between(html, r'<div id="mondai"[^>]*>', r'<div class="ansbg"')
    question_text = html_fragment_to_text(mondai)

    choices: dict[str, str] = {}
    for m in SELECT_SPAN_RE.finditer(html):
        suffix = m.group(1).lower()
        kana = CHOICE_SUFFIX.get(suffix, suffix)
        choices[kana] = _choice_text_from_span(m.group(2))

    kaisetsu = slice_kaisetsu(html)
    choice_notes: dict[str, str] = {}
    for m in CHOICE_NOTE_RE.finditer(kaisetsu):
        suffix = m.group(1).lower()
        kana = CHOICE_SUFFIX.get(suffix, suffix)
        choice_notes[kana] = html_fragment_to_text(m.group(2))

    explanation_html = CHOICE_NOTE_RE.sub("", kaisetsu)
    explanation_html = re.sub(r"<ul>\s*</ul>", "", explanation_html, flags=re.IGNORECASE)
    explanation = html_fragment_to_text(explanation_html)

    cm = CLASSIFICATION_RE.search(html)
    classification = ""
    if cm:
        classification = html_fragment_to_text(cm.group(1)).replace(" » ", " » ")

    am = ANSWER_RE.search(html)
    correct = am.group(1).strip() if am else ""

    figure_hints: list[str] = []
    for block_name, block in (
        ("mondai", mondai),
        ("kaisetsu", kaisetsu),
    ):
        for tag in IMG_TAG_RE.findall(block):
            m = re.search(r'src="[^"]*/([^"/]+)"', tag, re.IGNORECASE)
            if m:
                figure_hints.append(f"{block_name}: {m.group(1)}")

    return KakomonPage(
        url=url,
        question_num=qn,
        classification=classification,
        correct_answer=correct,
        question_text=question_text,
        choices=choices,
        choice_notes=choice_notes,
        explanation=explanation,
        figure_hints=figure_hints,
    )


def format_kakomon_page_for_ai(page: KakomonPage) -> str:
    lines = [
        "# ap-siken 取得結果",
        f"URL: {page.url}",
        f"問番号: {page.question_num}",
    ]
    if page.correct_answer:
        lines.append(f"正解: {page.correct_answer}")
    if page.classification:
        lines.append(f"分類: {page.classification}")

    lines.extend(["", "## 問題文", page.question_text or "（空）"])

    lines.extend(["", "## 選択肢"])
    for kana in ("ア", "イ", "ウ", "エ"):
        text = page.choices.get(kana, "（ap-siken にテキストなし）")
        lines.append(f"{kana}: {text}")

    if page.choice_notes:
        lines.extend(["", "## 選択肢ごとの解説（ap-siken）"])
        for kana in ("ア", "イ", "ウ", "エ"):
            note = page.choice_notes.get(kana)
            if note:
                lines.append(f"{kana}: {note}")

    lines.extend(["", "## 解説本文", page.explanation or "（空）"])

    if page.figure_hints:
        lines.extend(
            [
                "",
                "## 図・表（参考）",
                "画像は python3 scripts/fetch_question_figures.py --apply --question … で埋め込む（HTML 一次ファイルを使用。HTTP しない）。",
            ]
        )
        for hint in page.figure_hints:
            lines.append(f"- {hint}")

    return "\n".join(lines) + "\n"
