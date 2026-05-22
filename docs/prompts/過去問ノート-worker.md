# 過去問ノート作成 — ワーカー（サブエージェント・1問）

あなたは応用情報ボルトで **1問分の過去問ノートだけ** を作成するワーカーです。他の問や `用語一覧.md` の（N）集計は触らない。

## 今回のタスク

| 項目 | 値 |
|------|-----|
| 試験 | {{EXAM_LABEL}} |
| 区分 | {{SECTION}} |
| 回 | {{TERM_DIR}} |
| 問番号 | {{QUESTION_NUM}} |
| 保存先 | `{{QUESTION_PATH}}` |
| ap-siken | {{AP_SIKEN_URL}} |

## 必読（作業前に読む）

1. `README.md` の「共通ルール」
2. `docs/ai/過去問ノート.md`（手順 0〜6・2.5 まで。手順 7 は**実行しない**）
3. `テンプレート/過去問ノート.md`（HTML 形式）

## 手順（この順で完了させる）

### 0. 取得

- `{{AP_SIKEN_URL}}` を **WebFetch 等**で開く（**1回で足りる。再取得のためシェル HTTP は使わない**）
- **禁止（ap-siken 取得）:** `curl` / `wget` / `urllib.request` / `requests` 等による HTML 取得、HTML パース用の `python3 -c` / `python3 <<'PY'`、**`from fetch_question_figures import fetch_html` 等スクリプト経由の HTML パース**、ネットワーク許可を伴うスクレイピング。図・表が画像だけでも **上記で代替しない**
- 選択肢が HTML テキストで取れない問題（ap-siken の `selectList`＋表画像のみ等）は、手順 2.5 で表を `ap-question` に埋め込み、`ap-choice-text` はア〜エのみ（シェルで HTML を再取得しない）
- 図・表の数値が WebFetch に無いとき: 解説テキストに書いてある範囲だけ使う。それ以外は「元ページの図を参照」「要確認」と注記（**推測で表の数値を埋めない**）
- 取得するもの: 問題文、分類、正解、解説、各選択肢の説明（あれば）
- 画像のみの部分は「要確認」または元ページ参照の注記（推測で補う場合はその旨）

### 1. ファイル作成

- `{{QUESTION_PATH}}` に保存（既存なら上書き前に内容を確認し、ユーザー指示がなければ上書き可とみなす）
- 見出し: `# [{{EXAM_LABEL}} {{SECTION}} 問{{QUESTION_NUM}}]({{AP_SIKEN_URL}})`
- 分野タグ: ap-siken「分類」→ `タグ一覧.md` で `#問題` の直後に実タグ（`#大分類` プレースホルダのままにしない）
- HTML クイズ: テンプレート準拠。**`<div class="ap-quiz">` 内に空行を入れない**

### 2. 本文（用語リンクはまだ付けない）

- `ap-question` / `ap-choice-text` / `ap-choice-note` / `ap-explanation`
- `ap-explanation` は ap-siken の解説に沿う（独自の言い換え・数値の追加はしない。図は「元ページでは図で示されています」等）
- `ap-choice-note` は `docs/ai/過去問ノート.md` の A/B/C 基準で書く

### 2.5. 図（毎回）

**シェルはコマンド1行だけ**（ワークスペースは既にこのボルト。`cd`・絶対パス・`&&` 連結は使わない）。

```bash
python3 scripts/fetch_question_figures.py --apply --question {{QUESTION_PATH}}
```

- **図なし**と出たら次へ（curl 要否の判断は不要。スクリプトが自動判定）
- レポートに **「選択肢表（4肢まとめ）」** が出たら、スクリプトが `ap-question` 末尾（問題図の直後）に表画像を埋め込む。各 `ap-choice-text` は **ア／イ／ウ／エ のラベルのみ**（a～d の組合せは表に任せ、テキストで重複させない）
- 肢ごとに別画像の選択肢は、ここで `ap-choice-text` に図が入る

### 3〜6. 用語リンク

```bash
python3 scripts/check_question_terms.py --suggest --question {{QUESTION_PATH}}
```

- `用語一覧.md` で各候補を確認し、**文脈と一致する試験用語だけ**残す（汎用語・部品名だけの語は除外）
- 表記ゆれ（例: 打ち切り誤差 vs 一覧の打切り誤差）は一覧の語名に合わせてリンクする

```bash
python3 scripts/check_question_terms.py --apply --question {{QUESTION_PATH}} --terms 語1,語2,...
python3 scripts/check_question_terms.py --question {{QUESTION_PATH}}
```

- 照合 NG ならリンクを直して再照合し、**終了コード 0** にする

### 実行しないこと

- **`cd`・絶対パス・`&&` でのコマンド連結**（例: `cd … && python3 … && python3 …`）。各スクリプトは上記どおり **1行ずつ** `python3 scripts/…` のみ
- ap-siken の **手動シェル HTTP 取得**（`curl` / `wget` / `python3 -c` / `python3 <<'PY'` / `fetch_question_figures.fetch_html` の import など。本文は WebFetch のみ。**図・選択肢表は `fetch_question_figures.py --apply` のみ**）
- `python3 scripts/count_term_question_links.py`（親オーケストレーターが全問完了後に1回実行）
- `build_tag_index.py` / `build_glossary_index.py`
- `用語/○○.md` の新規作成
- `.obsidian/` の編集
- git commit

## 完了報告（親に返す）

次を必ず含める:

1. 保存パス
2. 正解（ア〜エ）
3. 付与した用語リンク一覧
4. 照合コマンドの結果（OK / 修正した内容）
5. 要確認にした箇所があればその旨
