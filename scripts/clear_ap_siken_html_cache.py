#!/usr/bin/env python3
"""workspace/ap-siken-html/ にある ap-siken 過去問 HTML の一次ファイルをすべて削除する。

オーケストレーターが全ワーカー完了後、count_term_question_links.py の直後に1回実行する想定。
ワーカーは実行しない（並列中に他問のキャッシュを消さないため）。

使い方:
  python3 scripts/clear_ap_siken_html_cache.py
  python3 scripts/clear_ap_siken_html_cache.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ap_siken_kakomon import HTML_CACHE_DIR_NAME


def vault_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="ap-siken HTML 一次ファイルを削除")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="削除せずパスだけ表示",
    )
    args = parser.parse_args()

    cache_root = vault_root() / HTML_CACHE_DIR_NAME
    if not cache_root.is_dir():
        print(f"一次 HTML なし（{HTML_CACHE_DIR_NAME}/ が存在しません）")
        return

    files = sorted(cache_root.rglob("*.html"))
    if not files:
        print(f"一次 HTML なし（{HTML_CACHE_DIR_NAME}/ 内に .html がありません）")
        return

    rel_root = vault_root()
    for path in files:
        rel = path.relative_to(rel_root).as_posix()
        if args.dry_run:
            print(f"  (dry-run) {rel}")
        else:
            path.unlink()
            print(f"  削除: {rel}")

    if not args.dry_run:
        for directory in sorted(cache_root.rglob("*"), reverse=True):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        print(f"\n{len(files)} 件削除しました")
    else:
        print(f"\n(dry-run: {len(files)} 件)")


if __name__ == "__main__":
    main()
