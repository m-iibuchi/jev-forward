# 05: state構築（`src/jevfwd/state/`）

- 対象：`state/builder.py` `state/truncate.py` `state/context.py`、`docs/contracts/state.v2.schema.json`
- マイルストーン：M3（`market_context` は段階1では null。実データは M6）
- 関連：CLAUDE.md ルール2・4・6、要件 F2-1〜F2-6、基本設計 3.3、ADR 002・015・017・020・024・026、task 005・006・013
- 版：2026-09-20 初版

## 1. 責務

- bundle 1件から、Jev に渡す state（JSON）を組み立てる（書式は `docs/contracts/state.v2.schema.json` が正）
- `judge.max_state_chars` に収まるまで切り詰める（要件 F2-4）
- 埋められなかった項目を `state_completeness` に残す（要件 F2-6、ADR 017）

しないこと：HTTP・判定（07-判定）、市場データの取得（`market/`。`state` は読むだけ）、`bundles` への INSERT（`cli` が `state_json` を付けて書く）、問いの文言の生成（`judge/questions.py`）。

**評価軸になる語を state に足さない**（CLAUDE.md ルール3）。state は事実だけを置く。

## 2. 依存

- 標準ライブラリのみ（`json` `re` `datetime`）
- `jevfwd.common`（`timeutil` `codes` `jsonutil` `errors`）、`jevfwd.settings`、`jevfwd.store`、`jevfwd.market`（00-共通規約 8章で許可されている）
- `bundle` は import しない。bundle の結果（`BundlePlan` 相当の情報）は引数で受ける

## 3. 公開インターフェース

### 3.1 `state/builder.py`

```python
@dataclass(frozen=True, slots=True)
class DocInput:
    """1論理開示。連番は連結済みの本文を渡す（連結は builder が logical_docs_json の順に行う）"""
    title: str
    body: str | None               # PDF 取得失敗・未着なら None（表題のみ）
    rank: int

@dataclass(frozen=True, slots=True)
class StateResult:
    state_json: str                # Jev に送る文字列そのもの。bundles.state_json に生のまま入れる
    state: dict                    # 検証・テスト用（state_json を json.loads したもの）
    state_chars: int               # len(state_json)
    completeness: dict             # bundles.state_completeness_json（schema の $defs/state_completeness）
    flags: tuple[str, ...]         # truncated / provisional_only / scan_suspect

def build_state(*, issuer: IssuerInput, anchor_published_at: str, session: str,
                docs: Sequence[DocInput], market_ctx: MarketContextProvider,
                disc_ctx: DisclosureContext, cfg: Settings) -> StateResult:
    """docs は rank 昇順（先頭が主開示）。副作用なし。now は取らない（時刻は anchor と ctx が持つ）"""
```

### 3.2 `state/context.py`（2つに分ける）

段階1で「取れないもの」と「取れるもの」の境目が違うので、プロトコルを分ける。

```python
class MarketContextProvider(Protocol):
    """market_cache（ADR 017）由来。段階1（market_cache.enabled=false）では全項目 null"""
    def market_context(self, code5: str, anchor_utc: str, session: str) -> tuple[dict, list[str]]: ...
        # 返り値は (market_context の dict, 欠損項目のパス)

class DisclosureContext(Protocol):
    """events / xbrl 由来。段階1でも取れる"""
    def recent_titles(self, code5: str, before_utc: str, days: int) -> list[str]: ...
    def forecast_context(self, code5: str, event_ids: Sequence[int]) -> dict | None: ...

class NullMarketContext(MarketContextProvider):  # 段階1。4項目すべて null を返す
class DbMarketContext(MarketContextProvider):    # M6。market.prices / listed_master を queries 経由で読む
class DbDisclosureContext(DisclosureContext):    # queries.recent_titles と events.xbrl_json
```

`issuer.market`（市場区分）は段階1でも TDnet 一覧の社名接頭辞から埋まる（4.2）。`listed_master` が入ったらそちらを優先する。

### 3.3 `state/truncate.py`（純関数）

```python
def fit(state: dict, budget: int, cfg: StateCfg) -> tuple[dict, dict]:
    """budget（文字数）に収まるまで state を縮める。返り値は (縮めた state, truncate レポート)"""

def is_report_like(body: str, cfg: StateCfg) -> bool
def chapter_headings(body: str) -> list[tuple[int, str]]          # (行番号, 見出し)
def extract_sections(body: str, cfg: StateCfg) -> list[dict]      # [{"heading":…, "text":…}]
def normalize_body(text: str) -> str                              # 改ページ \f → 空行、行末空白、3連以上の空行を圧縮
```

## 4. データ契約

### 4.1 state の書式

`docs/contracts/state.v2.schema.json`（本文は同ファイル）。`freeze-state --version v2` で `state_versions` に凍結する（03-CLI 3.6、ADR 020）。基本設計 3.3 の例がそのまま valid。

項目の埋め方：

| 項目 | 出どころ |
|---|---|
| `issuer.company` | `events.company` から市場区分の接頭辞を剥がす（`filters.strip_market_prefix`） |
| `issuer.code` | `common.codes.display_code(code5)`（4文字。5文字のまま渡さない） |
| `issuer.market` | 4.2 |
| `issuer.role` | 定数 `"発行者"`（ADR 002） |
| `published_at` | bundle の `anchor_published_at` を JST 表記に（`+09:00`）。DB は UTC のまま |
| `market_context` | `MarketContextProvider`。段階1は4項目とも null。**オブジェクトは必ず置く** |
| `forecast_context` | `DisclosureContext.forecast_context`（task 005 まで null） |
| `recent_disclosures_30d` | `queries.recent_titles(code, before=anchor, days=state.recent_days)`。`"YYYY-MM-DD 表題"` の形 |
| `same_time_disclosures` | 同 bundle の主開示以外の論理開示の表題（全件） |
| `primary` | rank 最小の論理開示。`body` は連番順に連結・正規化した本文 |
| `secondary` | 次の `state.max_secondary_bodies` 件（既定2、要件 F2-4）。本文つき |
| `other_titles` | 残りの論理開示の表題 |
| `state_version` | `cfg.judge.state_version`（`"v2"`） |

### 4.2 `issuer.market` の決め方（段階1）

`listed_master` は M6 まで無い。TDnet 一覧の社名接頭辞が市場区分を持っているので、`filters.v1.yaml` の `market_map`（04-束ね 4.12）で引く。
`Ｐ－`→東証プライム、`Ｓ－`→東証スタンダード、`Ｇ－`→東証グロース。接頭辞が無ければ null（`completeness.missing` に `issuer.market`）。
M6 以降は `listed_master` を優先し、`completeness.sources["issuer.market"]` を `listed_master` にする。

### 4.3 本文の正規化

| 段 | 何をするか |
|---|---|
| fetch（M2、06-取得） | PyMuPDF の出力を `\r\n`→`\n`、行末空白の除去、3連以上の空行の圧縮。ページ区切りは `\f` のまま `events.body_text` に入れる |
| state（本書） | `\f` → `\n\n`。前後の空白を落とす。連番の論理開示は `logical_docs_json` の順に `\n\n` で連結してから正規化 |

`tests/fixtures/*.txt` は CRLF で保存されているので、テストは必ず `Path(...).read_text(encoding="utf-8")`（ユニバーサル改行で LF になる）で読む。`read_bytes().decode()` だと `\r` が残り文字数が変わる（`9502` は 283,113 字 と 291,498 字の差）。

### 4.4 切り詰め（要件 F2-4、ADR 026）

**予算の数え方**：`len(json.dumps(state, ensure_ascii=False, indent=None))`＝実際に送る文字列の長さ。本文の合計長ではない。
`ensure_ascii=False` でも `"` と改行はエスケープされるので、本文を N 文字削っても JSON は N 文字縮まない。1回の計算で決め打ちせず、測って削るループにする。

```
0. builder が secondary を max_secondary_bodies 件に絞る（残りは other_titles）
1. 収まっていればそのまま（applied=false）
2. secondary の本文を rank の大きい順に1件ずつ表題のみ（body=null）へ落とす。各段で測り直す
3. primary が報告書型（4.5）なら excerpts を作って足す（この時点で state は一度増える）
4. primary.body を先頭優先で切る。収束するまで最大5回（超えたら JevfwdError。無限ループにしない）
```

- 切り詰めたら `flags` に `truncated`、`completeness.truncate` に前後の文字数・落とした件数・切った文字数・章見出しを残す
- 全部の `body` が None（PDF 未着）なら `flags` に `provisional_only`（暫定判定。ADR 015・024）
- `judge.max_state_chars` は 40,000。Jev の入力上限（5万〜5.5万字）との差は、問い7問とリクエストの外枠のぶん
- `state_chars` = `len(state_json)`。`judgments.input_chars` = `len(request_json)`（別物。07-判定）
- **切り詰め規則を変えたら state の版を上げる**（v3）。`completeness.rules.truncate_rev` に規則の改訂日を残す

### 4.5 報告書型の判定と章抽出

`9502_chubu_report_full.txt`（283,113字）で確認した実際の形：

- 目次らしき行は 123 行ある（`第 6 原因分析 .......... 222` のようにドットリーダーと頁番号を持つ）。ただし **「目次」という見出し語は本文に無い**ので、見出し語では判定できない
- 本文の章見出しは `第6 原因分析`（7290行目）。**第と数字の間に空白が無い**
- 誤検知しやすいのは `第 1 回ヘルプライン通報`（空白あり）、`第 624 回適合性審査会合`（空白あり）、`第一原子力発電所`（漢数字）、`第 6（222 頁から 234 頁）の原因の分析`（本文中の参照）

判定と抽出：

```python
HEADING = re.compile(r"^第[0-9０-９]+[ 　]\S")      # 第と数字の間に空白を入れない見出しだけを拾う
LEADER  = re.compile(r"\.{10,}|・{10,}|…{5,}")      # 目次のドットリーダー
PAGENO  = re.compile(r"^[0-9]{1,3}$")                # 章の直前に挟まる頁番号の行
SECTION_KEYS = ("原因", "評価", "結論", "結語", "再発防止", "提言")
```

- `is_report_like`：本文が `state.report_min_chars`（既定 50,000）以上で、かつ `HEADING` に一致する短い行（60文字未満）が `state.report_min_headings`（既定 5）以上、または `LEADER` を含む行が 20 以上
- `extract_sections`：`HEADING` の行のうち見出し文字列が `SECTION_KEYS` のいずれかを含むものを上から順に、次の `HEADING` 行までを章とし、`PAGENO` だけの行を除いて先頭 `state.excerpt_chars`（既定 2,000）字を取る。最大4章（＝最大 8,000 字）
- 抜粋は `primary.body` を書き換えず `primary.excerpts` に置く（ADR 026）。どこが原文でどこが抜粋かを後から見分けられるようにする
- `9502` で拾えるのは `第6 原因分析`・`第7 再発防止策の提言`・`第8 結語` の3章。**要件 F2-4 の「結論」はこの報告書では「結語」**なので、キーワードに `結語` と `提言` を足した（★4）

### 4.6 `state_completeness`

形は `docs/contracts/state.v2.schema.json` の `$defs/state_completeness`。`bundles.state_completeness_json` にだけ入れ、**Jev に送る state には含めない**（送る内容は版で固定する）。

```json
{"missing": ["market_context.prev_close", "forecast_context"],
 "sources": {"market_context": "null", "issuer.market": "tdnet_prefix"},
 "truncate": {"applied": true, "chars_before": 283500, "chars_after": 39884,
              "secondary_bodies_dropped": 1, "primary_body_cut_chars": 251000,
              "excerpt_headings": ["第6 原因分析"], "report_like": true},
 "rules": {"state_version": "v2", "truncate_rev": "2026-09-20", "filters_version": "v1"}}
```

### 4.7 先読みの禁止（CLAUDE.md ルール4の趣旨）

| 項目 | 規則 |
|---|---|
| `recent_disclosures_30d` | `published_at < anchor_published_at`（**`<=` にしない**。同時刻の開示は `same_time_disclosures` にあり、二重になる） |
| `market_context.prev_close` | `published_at` より前に確定している日足のうち最新のもの。J-Quants Light は前営業日までなので、実際には前営業日の終値になる。当日の終値を後から入れ直さない（追記専用） |
| `return_20d_vs_topix` `avg_turnover_20d_jpy` | 同じ基準日から遡った20営業日 |
| `forecast_context` | この bundle の event の XBRL、または公表時刻より前の開示のもの |

### 4.8 暫定判定と本判定の state（task 013）

ADR 024（04-束ね 4.8）で、PDF が後から届いた場合は superseding bundle を作ると決めた。したがって：

- 暫定（表題のみ）の state は旧 bundle の `state_json`、本判定の state は新 bundle の `state_json` にある
- どちらも `state_completeness` が付くので、暫定と本判定の差を後から測れる
- `judgments.request_json`（生）から state を復元する必要は無くなった

## 5. エラー時の振る舞い

| 事象 | 振る舞い |
|---|---|
| 切り詰めが5回で収束しない | `JevfwdError`。`cli` が捕まえて `judgments` にエラー行を残す（判定はしない） |
| `state_version` が未凍結 | `JudgeError`（判定側。02-設定 3.2 `render_from_db` と同じ扱い） |
| 生成した state が schema に合わない | `JevfwdError`。**送る前に落とす**（凍結ログに不正な state を残さない） |
| 本文がすべて None | 例外にしない。表題のみの state ＋ `provisional_only` |
| `market_context` が取れない | 例外にしない。null ＋ `completeness.missing` |
| `issuer.company` が空 | `ValueError`（問いの主語が空になる。ADR 002 の前提が崩れる） |

## 6. 設定項目

| キー | 既定 | 用途 |
|---|---|---|
| `judge.max_state_chars` | 40000 | 切り詰めの予算（4.4） |
| `judge.state_version` | v2 | `state_version` と凍結する schema |
| `paths.contracts_dir` | docs/contracts | `state.vN.schema.json` の場所 |
| `market_cache.enabled` | false | 段階1は `NullMarketContext` |
| `state.max_secondary_bodies` | 2 | 全文を載せる副次開示の数（要件 F2-4）★新設 |
| `state.excerpt_chars` | 2000 | 章抜粋の長さ（要件 F2-4）★新設 |
| `state.max_excerpts` | 4 | 抜粋する章の上限 ★新設 |
| `state.recent_days` | 30 | `recent_disclosures_30d`（要件 F2-2）★新設 |
| `state.report_min_chars` | 50000 | 報告書型の判定（4.5）★新設 |
| `state.report_min_headings` | 5 | 同上 ★新設 |

## 7. 擬似コード

```python
def build_state(*, issuer, anchor_published_at, session, docs, market_ctx, disc_ctx, cfg):
    docs = sorted(docs, key=lambda d: d.rank)
    mc, missing = market_ctx.market_context(issuer.code5, anchor_published_at, session)
    fc = disc_ctx.forecast_context(issuer.code5, issuer.event_ids)
    state = {
        "issuer": {"company": issuer.company, "code": display_code(issuer.code5),
                   "market": issuer.market, "role": "発行者"},
        "published_at": to_jst(parse_utc(anchor_published_at)).isoformat(timespec="seconds"),
        "market_context": mc,
        "forecast_context": fc,
        "recent_disclosures_30d": disc_ctx.recent_titles(issuer.code5, anchor_published_at, cfg.state.recent_days),
        "same_time_disclosures": [d.title for d in docs[1:]],
        "primary": {"title": docs[0].title, "body": normalize_body(docs[0].body or "")},
        "secondary": [{"title": d.title, "body": normalize_body(d.body) if d.body else None}
                      for d in docs[1:1 + cfg.state.max_secondary_bodies]],
        "other_titles": [d.title for d in docs[1 + cfg.state.max_secondary_bodies:]],
        "state_version": cfg.judge.state_version,
    }
    state, report = fit(state, cfg.judge.max_state_chars, cfg.state)
    text = json.dumps(state, ensure_ascii=False)
    flags = ()
    if report["applied"]:                               flags += ("truncated",)
    if all(d.body is None for d in docs):               flags += ("provisional_only",)
    completeness = {"missing": missing + _missing_of(state), "sources": _sources(...),
                    "truncate": report, "rules": {...}}
    return StateResult(text, state, len(text), completeness, flags)

def fit(state, budget, cfg):
    report = {"applied": False, "chars_before": _n(state), "chars_after": 0,
              "secondary_bodies_dropped": 0, "primary_body_cut_chars": 0,
              "excerpt_headings": [], "report_like": False}
    if _n(state) <= budget:
        report["chars_after"] = _n(state); return state, report
    report["applied"] = True
    for i in range(len(state["secondary"]) - 1, -1, -1):          # rank の大きい順
        if _n(state) <= budget: break
        if state["secondary"][i]["body"] is not None:
            state["secondary"][i]["body"] = None
            report["secondary_bodies_dropped"] += 1
    body = state["primary"]["body"]
    if _n(state) > budget and is_report_like(body, cfg):
        report["report_like"] = True
        secs = extract_sections(body, cfg)[: cfg.max_excerpts]
        state["primary"]["excerpts"] = secs
        report["excerpt_headings"] = [s["heading"] for s in secs]
    for _ in range(5):                                            # 測って削るループ（エスケープぶん）
        over = _n(state) - budget
        if over <= 0: break
        cut = min(len(state["primary"]["body"]), int(over * 1.1) + 32)
        state["primary"]["body"] = state["primary"]["body"][: len(state["primary"]["body"]) - cut]
        report["primary_body_cut_chars"] += cut
    if _n(state) > budget:
        raise JevfwdError(f"切り詰めが収束しない: {_n(state)} > {budget}")
    report["chars_after"] = _n(state)
    return state, report

def _n(state): return len(json.dumps(state, ensure_ascii=False))
```

## 8. 受入テスト一覧（`tests/test_state.py`）

共通：本文 fixture は `Path(...).read_text(encoding="utf-8")` で読む（4.3）。複数文書の fixture は `tests/conftest.py` の `split_disclosures`（04-束ね 8章）で分ける。
schema 検証は `docs/contracts/state.v2.schema.json` を読み、テスト側の最小バリデータ（`tests/schema_check.py`、`type` `const` `pattern` `required` `additionalProperties` `items` `properties` `minLength` のみ）で行う（`jsonschema` は依存に入れない）。

| ID | テスト関数 | 前提・入力 | 期待 | fixture |
|---|---|---|---|---|
| T05-01 | `test_schema_file_is_valid_json_schema` | `docs/contracts/state.v2.schema.json` | `json.loads` できる object、`$schema` が draft 2020-12、`$defs.state_completeness` がある | `docs/contracts/state.v2.schema.json` |
| T05-02 | `test_basic_design_example_is_valid` | 基本設計 3.3 の例 JSON（テストに literal で持つ） | schema で valid | 同上 |
| T05-03 | `test_hobonichi_state_shape` | ほぼ日4件（本文は `3560_hobonichi_fiscal_year_change.txt` の1件のみ、他は body=None） | schema で valid。`issuer.code == "3560"`、`issuer.role == "発行者"`、`published_at == "2026-09-17T17:30:00+09:00"`、`same_time_disclosures` が3件 | `tdnet_list_2026-09-17.tsv` 9・12・15・16行目、`3560_hobonichi_fiscal_year_change.txt` |
| T05-04 | `test_display_code_is_four_chars` | 同上（DB のコードは `35600`） | `issuer.code` が `"3560"`。5文字が混ざっていない | 同上 |
| T05-05 | `test_market_from_name_prefix` | `Ｇ－ミンカブ`（`44360`）、接頭辞なしの `ほぼ日` | 前者 `issuer.market == "東証グロース"`・`company == "ミンカブ"`、後者は `market is null` かつ `missing` に `issuer.market` | `tdnet_list_2026-09-17.tsv` |
| T05-06 | `test_null_market_context_records_missing` | `NullMarketContext` | `market_context` の4項目が null（キーは存在する）、`completeness.missing` に4項目、`sources.market_context == "null"` | — |
| T05-07 | `test_recent_disclosures_excludes_same_minute` | 同一銘柄で anchor と同時刻の開示、1分前の開示、31日前の開示 | `recent_disclosures_30d` に1分前だけが入る（同時刻は入らない、31日前も入らない） | — |
| T05-08 | `test_prev_close_uses_last_completed_bar` | `DbMarketContext`、`prices` に anchor 前日までの日足と anchor 当日の日足 | `prev_close` は anchor より前に確定した最新の日足（当日分を使わない） | — |
| T05-09 | `test_liberta_two_same_title_docs_in_state` | リベルタ 16:00 の同一表題2件（本文は `4935_liberta_3days_bundle.txt` の296行目・337行目の各位ブロック） | `primary` と `secondary[0]` の `title` が同じで `body` が違う。`other_titles` は空 | `4935_liberta_3days_bundle.txt` |
| T05-10 | `test_secondary_bodies_capped_at_two` | 本文つき論理開示5件 | `secondary` は2件、残り2件の表題が `other_titles` | `6497_hamai_3core.txt` |
| T05-11 | `test_short_state_not_truncated` | ほぼ日（1,691字） | `truncate.applied is False`、`flags` に `truncated` が無い、`state_chars == len(state_json)` | `3560_hobonichi_fiscal_year_change.txt` |
| T05-12 | `test_chubu_report_fits_budget` | `9502_chubu_report_full.txt`（283,113字）を primary に | `state_chars <= 40000`、`json.dumps(state, ensure_ascii=False)` の長さも 40000 以下、`flags` に `truncated` | `9502_chubu_report_full.txt` |
| T05-13 | `test_chubu_excerpts_are_the_real_chapters` | 同上 | `primary.excerpts` の `heading` が `第6 原因分析`・`第7 再発防止策の提言`・`第8 結語` を含み、`第6 原因分析` の `text` が「中部電力は、上記第 4 のとおり」で始まる | 同上 |
| T05-14 | `test_chapter_heading_false_positives_rejected` | 同上の本文 | `chapter_headings` に `第 1 回ヘルプライン通報`・`第 624 回適合性審査会合`・`第一原子力発電所`・`第 6（222 頁から 234 頁）` が入らない。拾う見出しはちょうど8件（`第1 調査の概要`〜`第8 結語`） | 同上 |
| T05-15 | `test_leopalace_bundle_truncated` | レオパレス（`8848_leopalace_tob_target_bundle_full.txt` の4ブロック、194,441字） | `state_chars <= 40000`、`secondary` の本文が null に落ちている件数が `truncate.secondary_bodies_dropped` と一致 | `8848_leopalace_tob_target_bundle_full.txt` |
| T05-16 | `test_truncate_is_not_report_like_for_press_release` | `9227_microwave_growth_plan.txt`（25,789字、スライド） | `report_like is False`（`excerpts` を作らない） | `9227_microwave_growth_plan.txt` |
| T05-17 | `test_escaping_accounted_in_budget` | 本文が `"` と改行だらけの合成文字列（生の長さは予算内、エスケープ後は超える） | 最終的に `len(json.dumps(...)) <= budget`（1回の引き算で済ませていないこと） | — |
| T05-18 | `test_truncate_raises_when_not_converging` | `budget=50`（外枠だけで超える） | `JevfwdError` | — |
| T05-19 | `test_formfeed_normalized` | `\f` を含む合成本文 | state の `body` に `\f` が無く、空行に置き換わっている | — |
| T05-20 | `test_crlf_fixture_read_convention` | `9502_chubu_report_full.txt` を `read_text` と `read_bytes().decode()` で読む | 前者 283,113 字、後者 291,498 字。実装・テストは前者を使う（4.3） | `9502_chubu_report_full.txt` |
| T05-21 | `test_provisional_only_when_no_body` | 全 doc の `body=None`（`pdf_status='failed'`） | `flags` に `provisional_only`、`primary.body == ""`、schema で valid | — |
| T05-22 | `test_completeness_matches_schema_def` | 任意の state の `completeness` | `$defs/state_completeness` で valid。`rules.state_version == "v2"`、`rules.truncate_rev` がある | `docs/contracts/state.v2.schema.json` |
| T05-23 | `test_state_json_is_stored_raw` | `StateResult.state_json` と `json.loads` → 再 `dumps` | `state_chars == len(state_json)`。`bundles.state_json` には `state_json` をそのまま入れる（キー順を並べ替えない。★6） | — |
| T05-24 | `test_empty_company_rejected` | `company=""` | `ValueError` | — |
| T05-25 | `test_sequence_docs_concatenated_in_order` | 中部電力3分割を1論理開示として（本文は3つに切った合成） | `primary.body` が（１／３）→（２／３）→（３／３）の順で連結されている | `tdnet_list_2026-09-14_16.tsv` 930〜932行目 |

## 9. 完了条件

- T05-01〜T05-25 が通る
- `docs/contracts/state.v2.schema.json` が存在し、`jevfwd freeze-state --version v2` が成功する（03-CLI T03-15）
- `state` が `bundle` `judge` を import していない（T00-14）
- task 006 を done にする

## 10. 基本設計からの差分

| ★ | 変更 | 基本設計書の修正箇所 |
|---|---|---|
| 1 | 切り詰めの予算は「送る JSON 文字列の長さ」で測る（本文合計ではない）。エスケープのぶんを測り直すループにする（ADR 026） | 3.3 の切り詰め手順 |
| 2 | 報告書型の判定は「目次に頁番号付き章立て」ではなく、**見出し行の形と数**（本文に「目次」の語が無い fixture で確認） | 3.3 の 3 |
| 3 | 章の抜粋は `primary.body` の先頭に足さず `primary.excerpts` に分けて渡す（ADR 026） | 3.3 の 3 |
| 4 | 章キーワードに `結語` `提言` を追加（要件 F2-4 の「結論」は実物では「結語」） | 要件 F2-4 の注記 |
| 5 | `state_completeness` は `bundles` の列にだけ置き、Jev に送る state には含めない | 3.3 の本文 |
| 6 | `bundles.state_json` を「生保存」列に加える（`canonical` でキー順を変えると、送った文字列と保存が食い違う） | 00-共通規約 5章 |
| 7 | ContextProvider を `MarketContextProvider` と `DisclosureContext` に分ける（段階1で取れるものが違う） | 2章ツリー、3.3 |
| 8 | `issuer.market` は段階1では社名接頭辞から埋める（`filters.v1.yaml` の `market_map`） | 3.3 |
| 9 | `state.*` の設定キーを新設（`max_secondary_bodies` `excerpt_chars` `max_excerpts` `recent_days` `report_min_chars` `report_min_headings`） | 5章 |
| 10 | 暫定 state と本判定 state は別 bundle に載る（ADR 024。task 013 の結論） | 3.4 |
