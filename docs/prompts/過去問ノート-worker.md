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
| 出典URL（**閲覧しない**） | {{AP_SIKEN_URL}} |

## ap-siken 取得（厳守・最優先）

**ap-siken の本文・図は `fetch_question_figures.py` だけ。** 見出しの URL をブラウザや WebFetch で開かない。

| やること | コマンド |
|----------|----------|
| 本文・分類・正解・解説 | `python3 scripts/fetch_question_figures.py --print-source --question {{QUESTION_PATH}}`（**1回**。失敗時は同じ1行を再実行） |
| 図の埋め込み | `python3 scripts/fetch_question_figures.py --apply --question {{QUESTION_PATH}}`（一次 HTML のみ。再 HTTP しない） |

**絶対に使わない:** WebFetch / `mcp_web_fetch` / ブラウザツール / `curl` / `wget` / `python3 -c` / `ap_siken_kakomon`・`fetch_question_figures` の **import**
**IDE が WebFetch や URL 閲覧の許可を求めたら:** **拒否（Skip）** する。許可して取得しない。上記 `--print-source` の1行を実行する。
**`--print-source` が空・エラーの時は、その旨を伝え手順を終了する** 


## 必読（作業前に読む）

1. `README.md` の「共通ルール」
2. `docs/ai/過去問ノート.md`（手順 0〜6。手順 7 の集計は**実行しない**）
3. `テンプレート/過去問ノート.md`（HTML 形式）

## 手順（この順で完了させる）

### 0. 見出しだけ先に置く（**URLは開かない**）

- `{{QUESTION_PATH}}` にテンプレートを複製し、**見出し1行目だけ**確定する（他は後で埋める）:
  - `# [{{EXAM_LABEL}} {{SECTION}} 問{{QUESTION_NUM}}]({{AP_SIKEN_URL}})`
- 見出しの `{{AP_SIKEN_URL}}` は **Obsidian 用の出典リンク文字列**（タスク表の値をそのまま貼るだけ）。**WebFetch・ブラウザで開かない。** 問題文・解説の取得は **手順1** の `--print-source` だけ。
- スクリプトは見出しの URL から問を特定するため、**先にこの1行だけ**置く（= 手順0 → 手順1 の順は変えない）。

### 1. 本文の取得（スクリプト・1回）

**次の1行だけをそのまま実行**（`cd`・`&&` でつなげない）。

```bash
python3 scripts/fetch_question_figures.py --print-source --question {{QUESTION_PATH}}
```

- 標準出力の **問題文・分類・正解・選択肢・解説** をもとに手順 2 でノートを書く（HTML は `workspace/ap-siken-html/` に保存。手順 4 の `--apply` はそれを読むだけ）
- 上記 **「ap-siken 取得（厳守）」** に従う（WebFetch 許可ダイアログは拒否してスクリプトに戻る）
- 選択肢が `[画像のみ: …]` のとき: 手順 2.5 で表を `ap-question` に埋め込み、`ap-choice-text` はア〜エのみ
- 図・表の数値が出力に無いとき: 解説テキストにある範囲だけ使う。それ以外は「元ページの図を参照」「要確認」（**推測で表の数値を埋めない**）

### 2. ファイル完成

- `{{QUESTION_PATH}}` に本文を保存（既存なら上書き前に内容を確認し、ユーザー指示がなければ上書き可とみなす）
- 分野タグ: ap-siken「分類」→ `タグ一覧.md` で `#問題` の直後に実タグ（`#大分類` プレースホルダのままにしない）
- HTML クイズ: テンプレート準拠。**`<div class="ap-quiz">` 内に空行を入れない**

### 3. 本文（用語リンクはまだ付けない）

- `ap-question` / `ap-choice-text` / `ap-choice-note` / `ap-explanation`
- `ap-explanation` は ap-siken の解説に沿う（独自の言い換え・数値の追加はしない。図は「元ページでは図で示されています」等）
- `ap-choice-note` は `docs/ai/過去問ノート.md` の A/B/C 基準で書く

### 4. 図（毎回）

**次の1行だけをそのまま実行**（`cd`・`&&` でつなげない）。

```bash
python3 scripts/fetch_question_figures.py --apply --question {{QUESTION_PATH}}
```

- **図なし**と出たら次へ（curl 要否の判断は不要。スクリプトが自動判定）
- レポートに **「選択肢表（4肢まとめ）」** が出たら、スクリプトが `ap-question` 末尾（問題図の直後）に表画像を埋め込む。各 `ap-choice-text` は **ア／イ／ウ／エ のラベルのみ**（a～d の組合せは表に任せ、テキストで重複させない）
- 肢ごとに別画像の選択肢は、ここで `ap-choice-text` に図が入る

### 4.5. 文中インライン図（該当問のみ・手動）

`--apply` のあと、**`docs/ai/過去問ノート.md` の「手順 4.5」** を確認する。該当時のみ実施（スクリプトは自動化しない）。

- **目印:** `#mondai` に番号付き条件リスト＋条件文中の小さな `<img>`（例: R4春 問16 の `16_1`〜`16_3`）
- **やること:** 〔ジョブ群〕等の見出し・(1)〜(n)・文中図の位置を HTML に合わせる。文中図には `style="display:inline;vertical-align:middle;margin:0"`
- **参照:** `問題/午前/R4春期/16.md`
- 完了報告に「手順4.5実施」と書く

### 5〜8. 用語リンク

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

- **`cd`・`&&` でのコマンド連結**（例: `cd … && python3 …`）。各スクリプトは **1行ずつ** `python3 scripts/…` のみ
- ap-siken の **手動取得**（WebFetch・ブラウザ・`curl`・`wget`・`python3 -c`・スクリプト import。**本文は `--print-source`、図は `--apply` のみ**）
- **{{AP_SIKEN_URL}} を WebFetch で開くこと**（見出しリンク用。取得はスクリプトのみ）
- `python3 scripts/count_term_question_links.py` / `clear_ap_siken_html_cache.py`（親オーケストレーターが全問完了後に1回）
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
6. ap-siken 取得: **`--print-source` のみ** / WebFetch は**未使用**（使った場合は正直に記載）
