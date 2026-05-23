#!/usr/bin/env bash
# Gate scripts/ invocations: deny cd, chaining, absolute paths; require
#   python3 scripts/<allowed>.py ...
set -euo pipefail

export VALIDATE_SHELL_INPUT
VALIDATE_SHELL_INPUT=$(cat)

python3 <<'PY'
import json
import os
import re
import sys

command = ""
try:
    payload = json.loads(os.environ.get("VALIDATE_SHELL_INPUT", "") or "{}")
    command = payload.get("command") or ""
except json.JSONDecodeError:
    command = ""

ALLOWED = (
    r"^python3\s+scripts/"
    r"(check_question_terms|count_term_question_links|fetch_question_figures|"
    r"build_tag_index|build_glossary_index)\.py"
)

def emit(permission: str, reason: str = "") -> None:
    body: dict = {"permission": permission}
    if permission == "deny":
        body["user_message"] = (
            "シェル形式がボルト規約に合いません。"
            "python3 scripts/... をリポジトリルートから1行だけ実行してください。"
        )
        body["agent_message"] = (
            f"{reason}\nRejected:\n  {command}\n\n"
            "Retry (one line, from repo root, no cd / && / ; / absolute path):\n"
            "  python3 scripts/<name>.py [options]\n"
            "Example:\n"
            "  python3 scripts/check_question_terms.py --question 問題/午前/R3春期/7.md\n"
            "Allowed scripts: check_question_terms, count_term_question_links, "
            "fetch_question_figures, build_tag_index, build_glossary_index"
        )
    print(json.dumps(body, ensure_ascii=False))

if "scripts/" not in command:
    emit("allow")
    sys.exit(0)

if re.search(r"(^|\s)cd(\s|;|&&|$)", command) or "&&" in command or ";" in command:
    emit("deny", "Blocked: cd, &&, and ; are not allowed when running vault scripts.")
    sys.exit(0)

if re.match(ALLOWED, command):
    emit("allow")
    sys.exit(0)

emit(
    "deny",
    "Blocked: use exactly python3 scripts/<allowed_script>.py "
    "with no path prefix (not ./scripts/, not an absolute path).",
)
PY
