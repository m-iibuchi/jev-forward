# 03: CLI（`src/jevfwd/cli.py`）

- 対象：`cli.py`、`pyproject.toml` の `[project.scripts]`
- マイルストーン：M1（`init-db` `freeze-questions` `freeze-state` と `--help`。他サブコマンドはスタブ）
- 関連：CLAUDE.md ルール2、要件 F3-6、基本設計 2章・8章 M1、ADR 014・020、01-凍結ログ、02-設定
- 版：2026-09-20 初版（同日 M3 追補：`bundle` サブコマンド、T03-15 の確定。同日追補2：`cmd_bundle` の擬似コードと `state_of` の組み立て（task 017）、`pyproject.toml` の `dev` extras、Docker 内での実行）

## 1. 責務

- `python -m jevfwd.cli <subcommand>` と console script `jevfwd` の入口。引数解釈、設定の読み込み、DB 接続、終了コードの変換だけを行う
- 業務処理は各モジュールの関数を呼ぶ。`cli.py` に SQL や判定ロジックを書かない。`freeze-questions` / `freeze-state` の DB 側の手順は `store/freeze.py` の `freeze_version`（01-凍結ログ 3.5）。`cli.py` は `sqlite3` を import しない（例外は `db.IntegrityError` の別名で捕まえる）
- 全サブコマンド名を M1 で登録し、未実装は明示的に「未実装（Mx で実装）」と言って終了コード1で止まる（黙って何もしない、を無くす）

## 2. 依存

- 標準ライブラリ `argparse` `logging` `sys` `importlib.metadata`
- `jevfwd.settings` `jevfwd.store.db` `jevfwd.store.freeze` `jevfwd.store.queries` `jevfwd.judge.questions` `jevfwd.common`
- `cli` は全モジュールを import してよい（00-共通規約 境界表）。逆に `cli` を import するモジュールは無い

## 3. 公開インターフェース

### 3.1 コマンド体系

```
jevfwd [--config PATH] [--log-level LEVEL] [--version] <subcommand> [options]

  init-db                          schema を現在版まで前進（冪等）
  freeze-questions --version vN [--file PATH]
  freeze-state     --version vN [--file PATH]
  fetch            [--once]        M2
  heartbeat        [--once]        M2
  bundle           [--once]        M3
  judge            [--once] [--bundle ID]   M4
  market-cache     [--once]        M6
  score                            M6
  digest           [--run 18:30|07:30]      M7
  paper                            M7
  report                           M8
```

- `--config PATH`：`settings.yaml` の場所。`resolve_settings_path(cli_arg, env)`（02-設定）で `--config` → `$JEVFWD_CONFIG` → `config/settings.yaml`
- `--log-level`：`DEBUG|INFO|WARNING|ERROR`、既定 `INFO`。stdout に `%(asctime)s %(levelname)s %(name)s %(message)s`、時刻は UTC（`logging.Formatter.converter = time.gmtime`）。`SecretMaskFilter`（00-共通規約）をルートロガーに付ける
- `--version`：`jevfwd <importlib.metadata.version("jevfwd")>` を出して exit 0
- サブコマンド名はハイフン区切り（`init-db` `freeze-questions` `market-cache`）。基本設計2章の `cli.py` コメントの一覧に `init-db` と `bundle` を加える（★）
- `bundle` は束ね〜state構築〜判定キューを回すプロセス（M3）。`bundle` `state` `judge` を横断して繋ぐのは `cli` の役目（00-共通規約 8章）

### 3.2 終了コード

| コード | 意味 | 出どころ |
|---|---|---|
| 0 | 成功。no-op（既に凍結済み、既に最新版）も 0 | — |
| 1 | 業務エラー・設定エラー・未実装 | `JevfwdError`（`SchemaMismatchError` 以外）、`NotImplementedError` |
| 2 | 引数の誤り | argparse 既定 |
| 3 | スキーマ不一致（`init-db` が必要） | `SchemaMismatchError`。supervisord の `exitcodes` で区別し、ワーカーの再起動ループを止める判断に使う |

予期しない例外（`JevfwdError` 以外）はトレースバックを stderr に出して exit 1。`db.IntegrityError`（制約違反）も 1（メッセージをそのまま出す。トレースバックは出さない）。

### 3.3 `main(argv: list[str] | None = None) -> int`

テストは `main([...])` を直接呼び、戻り値と `capsys` で検証する。`sys.exit` は `if __name__ == "__main__": sys.exit(main())` と console script のみ。

### 3.4 `init-db`

- `settings.storage.db_path` に対して `db.migrate` を呼ぶ。出力 `schema_version=1 path=data/db/jevfwd.sqlite`
- 冪等。2回目も exit 0
- 運用：supervisord で `[program:init-db] priority=1 autorestart=false startsecs=0`、または Docker entrypoint の先頭で1回。ワーカーは `connect` で版を検査するだけで自動マイグレーションしない（01-凍結ログ 3.1）

### 3.5 `freeze-questions --version vN [--file PATH]`

手順（ADR 020）：

1. `path = --file` または `settings.questions_path(vN)`（`<config_dir>/questions.vN.json`）。無ければ exit 1
2. `raw = path.read_bytes()`、`sha = sha256_hex(raw)`、`text = raw.decode("utf-8")`（BOM があれば exit 1）
3. `questions.parse(text, vN)` で形と `_version` を検証。失敗は exit 1、DB に触らない
4. `conn = db.connect(db_path)`（未初期化なら exit 3）
5. `store.freeze.freeze_version(conn, table="question_versions", version=vN, text=text, sha256=sha, now=to_utc_str(now_utc()))`（01-凍結ログ 3.5）
   - `("frozen", sha, ts)` → 出力 `frozen question_version=v2 sha256=<sha> frozen_at=<ts>`、exit 0
   - `("already", sha, ts)` → 出力 `already frozen question_version=v2 sha256=<sha> frozen_at=<既存 ts>`、exit 0
   - `ConfigError`（不一致）→ exit 1。stderr `ERROR: question_versions v2 は sha256=<既存> で凍結済み。ファイルは <sha>。版ファイルを変更してはいけない（新しい版を作る）`。INSERT されない
6. 並行実行の UNIQUE 衝突は `freeze_version` が1回やり直す（T01-27）

`json` 列にはファイル本文を**そのまま**入れる（正規化・整形しない）。DB 側の `sha256` はファイルバイト列のもの。`text.encode("utf-8")` と `raw` が一致することを凍結前に確認する（BOM・改行の変換が無いこと）。

### 3.6 `freeze-state --version vN [--file PATH]`

`freeze-questions` と同じ手順で、既定パス `settings.state_schema_path(vN)`（`docs/contracts/state.vN.schema.json`）、検証は `json.loads` が object であることと `"$schema"` キーの存在、`freeze_version(table="state_versions", …)`（`spec` 列）。

`docs/contracts/state.v2.schema.json` は task 006 で作成済み（2026-09-20）。`tmp_path` の最小スキーマでのテスト（T03-16）に加えて、実ファイルのテスト（T03-15）を行う。

### 3.7 スタブ（`fetch` `heartbeat` `bundle` `judge` `market-cache` `score` `digest` `paper` `report`）

```
ERROR: サブコマンド fetch は未実装（M2 で実装。docs/detailed/06-取得.md）
```
を stderr に出して exit 1。対応表：fetch/heartbeat → M2、bundle → M3（`docs/detailed/04-束ね.md` `05-state構築.md`）、judge → M4、market-cache/score → M6、digest/paper → M7、report → M8。

各マイルストーンで実装したサブコマンドは `STUBS` から外す（M3 で `bundle` を外すと T03-04 のスタブは 8 本になる。表の期待値も同時に直す）。

### 3.8 `bundle [--once]`（M3 で実装。セッション 3b）

- 束ね（04-束ね）→ state 構築（05-state構築）→ `bundles` への INSERT を1周期分回す。`--once` で1回だけ、無しなら `bundle.poll_sec` 周期のループ（M5 で supervisord の `program:bundler` に載せる）
- `bundle` は `state` を import できないので、`cli` が `state_of: Callable[[BundlePlan], StateResult | None]` を組み立てて `runner.run_once` に渡す（04-束ね 3.4、task 017）。`cli` 自身は `bundles` に INSERT しない
- `state_of` の中身：`queries.event_bodies(conn, plan.event_ids)` で本文を引き、`plan.logical_docs` の各 `event_ids` の順（連番順）に連結して `DocInput(title, body, rank)` に変換 → `IssuerInput`（`plan.company` から `filters.strip_market_prefix`、`market_of_company`）→ `build_state(..., market_ctx=NullMarketContext(), disc_ctx=DbDisclosureContext(conn), cfg=settings)`。`ValueError`（社名空）は `JevfwdError` に包む
- 出力：`bundles=<件数> ids=<id,...>` を1行。`JevfwdError` 以外の例外は 3.2 の表どおり exit 1（`--once` 無しのループでは捕まえて `heartbeat(ok=0)` を書いて次周期）

## 4. データ契約

- `question_versions` / `state_versions` の行の形は 01-凍結ログ 4.3
- 標準出力の1行は `key=value` を空白区切り（`frozen question_version=v2 sha256=… frozen_at=…`）。事前宣言（`docs/事前宣言.md`）にこの行を貼る
- `pyproject.toml`：

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "jevfwd"
version = "0.1.0"
description = "Jev判定フォワードテスト基盤"
requires-python = ">=3.11"
dependencies = ["pymupdf>=1.24", "httpx>=0.27", "pyyaml>=6", "pydantic>=2"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
jevfwd = "jevfwd.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
jevfwd = ["store/*.sql", "store/migrations/*.sql"]   # schema.sql は import 時に読む

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- 開発・テストは **Docker コンテナ内**で行う（ホストの Python に依存しない。`docs/実装セッション指示.md` 共通の前置き）。`deploy/Dockerfile` の `dev` ターゲット（`python:3.11-slim`、`pip install -e .[dev]`）と `deploy/docker-compose.yml` の `dev` サービス（リポジトリを `/app` に bind mount）を M1 のセッション 1a で作る。M5 が本番ターゲットと各プロセスのサービスを足す
- 実行例：`docker compose -f deploy/docker-compose.yml run --rm dev pytest`、`docker compose -f deploy/docker-compose.yml run --rm dev jevfwd --help`

## 5. エラー時の振る舞い

3.2 の表の通り。加えて：

- `--config` のファイルが無い → `ConfigError` → exit 1、メッセージにパス
- `freeze-*` で DB の親ディレクトリが無い → `connect` は `SchemaMismatchError`（DB 無し）→ exit 3、「`jevfwd init-db` を実行」
- `KeyboardInterrupt` → exit 130、メッセージなし
- ログには秘密を出さない。`--log-level DEBUG` でも `Secrets` は `repr` のマスク表示

## 6. 設定項目

`storage.db_path` `paths.config_dir` `paths.contracts_dir` `judge.question_version`（`freeze-questions` の `--version` 省略時の既定にはしない。凍結は明示の版を要求する）。

## 7. 擬似コード

```python
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jevfwd", description="Jev判定フォワードテスト基盤")
    p.add_argument("--config"); p.add_argument("--log-level", default="INFO", choices=[...])
    p.add_argument("--version", action="version", version=f"jevfwd {metadata.version('jevfwd')}")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db").set_defaults(func=cmd_init_db)
    fq = sub.add_parser("freeze-questions"); fq.add_argument("--version", required=True, dest="ver"); fq.add_argument("--file")
    fq.set_defaults(func=cmd_freeze_questions)
    ...  # freeze-state 同様
    for name, ms, doc in STUBS:   # ("fetch", "M2", "06-取得.md"), ...
        sub.add_parser(name).set_defaults(func=functools.partial(cmd_stub, name=name, milestone=ms, doc=doc))
    return p

def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.log_level, Secrets.from_env())
    try:
        settings = load_settings(resolve_settings_path(args.config))
        return args.func(args, settings)
    except SchemaMismatchError as e: print(f"ERROR: {e}", file=sys.stderr); return 3
    except JevfwdError as e:         print(f"ERROR: {e}", file=sys.stderr); return 1
    except NotImplementedError as e: print(f"ERROR: {e}", file=sys.stderr); return 1
    except KeyboardInterrupt:        return 130

def _read_version_file(path: Path) -> tuple[str, str]:      # (text, sha256)
    if not path.exists(): raise ConfigError(f"版ファイルがありません: {path}")
    raw = path.read_bytes(); text = raw.decode("utf-8")
    if text.encode("utf-8") != raw or text.startswith("\ufeff"): raise ConfigError("UTF-8（BOM なし）で保存してください")
    return text, sha256_hex(raw)

def cmd_freeze_questions(args, settings) -> int:
    path = Path(args.file) if args.file else settings.questions_path(args.ver)
    text, sha = _read_version_file(path)
    questions.parse(text, args.ver)                                  # 形と _version の検証。失敗は DB に触らず exit 1
    conn = db.connect(settings.storage.db_path)                      # 未初期化は SchemaMismatchError → exit 3
    status, sha, ts = freeze.freeze_version(conn, table="question_versions", version=args.ver,
                                            text=text, sha256=sha, now=to_utc_str(now_utc()))
    print(f"{'frozen' if status == 'frozen' else 'already frozen'} question_version={args.ver} sha256={sha} frozen_at={ts}")
    return 0

def cmd_bundle(args, settings) -> int:                              # M3（セッション 3b）で追加。task 017
    filters = load_filters(settings.filters_path()); calendar = load_calendar(settings.calendar_path())
    conn = db.connect(settings.storage.db_path)
    disc_ctx = DbDisclosureContext(conn); market_ctx = NullMarketContext()     # 段階1。market_cache.enabled で切替は M6

    def state_of(plan: BundlePlan) -> StateResult | None:
        bodies = queries.event_bodies(conn, plan.event_ids)               # {event_id: body_text | None}
        docs = [DocInput(title=d.title, rank=d.rank,
                         body=_concat_bodies([bodies[i] for i in d.event_ids]))   # 連番順に連結。全件 None なら None
                for d in plan.logical_docs]
        raw_company = plan.company or ""
        issuer = IssuerInput(code5=plan.code, company=filters.strip_market_prefix(raw_company),
                             market=filters.market_of_company(raw_company), event_ids=plan.event_ids)
        try:
            return build_state(issuer=issuer, anchor_published_at=plan.anchor_published_at, session=plan.session,
                               docs=docs, market_ctx=market_ctx, disc_ctx=disc_ctx, cfg=settings)
        except ValueError as e:                                     # 社名空など。行として残すため JevfwdError に包む
            raise JevfwdError(f"state 構築の入力不正: {e}") from e

    def once() -> int:
        ids = runner.run_once(conn, now_utc(), settings, filters, calendar, state_of)
        print(f"bundles={len(ids)} ids={','.join(map(str, ids))}")
        return 0

    if args.once:
        return once()
    while True:                                                     # 常駐。例外は heartbeat に書いて次周期
        try: once()
        except JevfwdError as e: log.error("%s", e); _heartbeat_ng(conn, "bundler", str(e))
        time.sleep(settings.bundle.poll_sec)

def cmd_freeze_state(args, settings) -> int:
    path = Path(args.file) if args.file else settings.state_schema_path(args.ver)
    text, sha = _read_version_file(path)
    doc = json.loads(text)                                           # JSONDecodeError → ConfigError
    if not isinstance(doc, dict) or "$schema" not in doc: raise ConfigError(f"{path}: JSON Schema（object、$schema あり）ではない")
    conn = db.connect(settings.storage.db_path)
    status, sha, ts = freeze.freeze_version(conn, table="state_versions", version=args.ver,
                                            text=text, sha256=sha, now=to_utc_str(now_utc()))
    print(f"{'frozen' if status == 'frozen' else 'already frozen'} state_version={args.ver} sha256={sha} frozen_at={ts}")
    return 0
```

## 8. 受入テスト一覧（`tests/test_cli.py`）

共通 fixture：`tmp_path` に `settings.yaml`（`storage.db_path` を `tmp_path/"db.sqlite"`、`paths.config_dir` をリポジトリの `config/` の絶対パス、`paths.contracts_dir` を `tmp_path/"contracts"` に）を書き、`--config` で渡す。`run(*args) -> (code, out, err)` は `main([...])` と `capsys` の薄いラッパ。

| ID | テスト関数 | 前提・入力 | 期待 | fixture |
|---|---|---|---|---|
| T03-01 | `test_help_lists_all_subcommands` | `run("--help")` | `SystemExit(0)`、stdout に `init-db` `fetch` `bundle` `judge` `heartbeat` `digest` `market-cache` `score` `paper` `report` `freeze-questions` `freeze-state` の12語すべて | — |
| T03-02 | `test_unknown_subcommand_exit_2` | `run("frobnicate")` | `SystemExit(2)`、stderr に `invalid choice` | — |
| T03-03 | `test_no_subcommand_exit_2` | `run()` | `SystemExit(2)` | — |
| T03-04 | `test_stub_subcommands_exit_1_with_milestone` | parametrize 9スタブ（M1 時点。M3 で `bundle` を外して 8 スタブにする） | 戻り値 1、stderr に `未実装` とマイルストーン（`fetch`→`M2`、`bundle`→`M3`（M1 時点のみ）、`judge`→`M4`、`score`→`M6`、`digest`→`M7`、`report`→`M8`） | — |
| T03-05 | `test_version_flag` | `run("--version")` | `SystemExit(0)`、stdout が `jevfwd 0.1.0` で始まる | — |
| T03-06 | `test_init_db_creates_and_is_idempotent` | `run("--config", cfg, "init-db")` を2回 | 両方 0。stdout に `schema_version=1`。DB に `schema_version` 1行、トリガー18本 | — |
| T03-07 | `test_freeze_questions_before_init_db_exit_3` | `init-db` せずに `freeze-questions --version v2` | 3。stderr に `init-db` | `config/questions.v2.json` |
| T03-08 | `test_freeze_questions_v2_inserts_row` | `init-db` 後に `freeze-questions --version v2` | 0。stdout が `frozen question_version=v2 sha256=3f7b661012e0ab94c22f3012bb76a72cc2a03cd086e26b5208fc5b6455f6bcb0 frozen_at=` で始まる。`question_versions` 1行、`json` 列 == `Path("config/questions.v2.json").read_text(encoding="utf-8")`（バイト一致）、`frozen_at` が UTC 書式 | `config/questions.v2.json` |
| T03-09 | `test_freeze_questions_rerun_is_noop` | T03-08 の後にもう1回 | 0。stdout が `already frozen` で始まり `frozen_at` が1回目と同じ。行数 1 | `config/questions.v2.json` |
| T03-10 | `test_freeze_questions_v1_too` | `freeze-questions --version v1` | 0、`sha256=14a8baac5898235be756d1c4265fc39541adf13108d9bbc04a445cabf65bd2e7`。v1 は `_subject_prefix` 無しでも通る | `config/questions.v1.json` |
| T03-11 | `test_freeze_questions_mismatch_exit_1_no_insert` | v2 凍結後、v2 の本文の `_notes` を1文字変えた JSON を `tmp_path/"questions.v2.json"` に置き `--file` で渡す | 1。stderr に `凍結済み` と両方の sha256。行数 1 のまま、`json` 列は元のまま | `config/questions.v2.json` |
| T03-12 | `test_freeze_questions_missing_file_exit_1` | `freeze-questions --version v9` | 1。stderr に `questions.v9.json`。行数 0 | — |
| T03-13 | `test_freeze_questions_version_mismatch_exit_1` | v2 本文を `tmp_path/"questions.v3.json"` にコピーして `--version v3 --file …` | 1（`_version=v2` と不一致）。行数 0 | `config/questions.v2.json` |
| T03-14 | `test_freeze_questions_bom_rejected` | v2 本文の先頭に BOM を付けたファイルを `--file` | 1。行数 0 | `config/questions.v2.json` |
| T03-15 | `test_freeze_state_v2_real_schema` | `paths.contracts_dir` をリポジトリの `docs/contracts/` にして `freeze-state --version v2` | 0。stdout が `frozen state_version=v2 sha256=` で始まる。`state_versions` の `spec` が `docs/contracts/state.v2.schema.json` の本文とバイト一致。2回目は `already frozen` | `docs/contracts/state.v2.schema.json` |
| T03-16 | `test_freeze_state_with_tmp_schema` | `tmp_path/"contracts"/"state.v2.schema.json"` に `{"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}` を置き `freeze-state --version v2` を2回 | 1回目 0 `frozen state_version=v2 sha256=<ファイルの sha>`、2回目 0 `already frozen`。`state_versions` 1行、`spec` がファイル本文と一致 | — |
| T03-17 | `test_freeze_state_rejects_non_schema` | `[]` だけのファイル／`$schema` の無い `{}` | 1、行数 0 | — |
| T03-18 | `test_missing_config_exit_1` | `--config /nonexistent.yaml init-db` | 1、stderr にパス | — |
| T03-19 | `test_env_config_used_when_flag_absent` | `monkeypatch.setenv("JEVFWD_CONFIG", cfg)`、`run("init-db")` | 0。DB が cfg の `db_path` に作られる | — |
| T03-20 | `test_freeze_concurrent_conflict_surfaces_as_already` | `store.freeze.freeze_version` の内部リトライは T01-27 で検証済み。ここでは `freeze_version` を monkeypatch して `("already", sha, U)` を返させる | 戻り値 0、stdout が `already frozen` で始まる | `config/questions.v2.json` |
| T03-21 | `test_module_entry_point` | `subprocess.run([sys.executable, "-m", "jevfwd.cli", "--version"])` | returncode 0 | — |
| T03-22 | `test_logging_masks_secrets` | `TYPESAFE_API_KEY=sk-test-XYZ` を env に置き、`--log-level DEBUG init-db` の後に `logging.getLogger().info("key=%s", "sk-test-XYZ")` | `caplog` / stdout に `sk-test-XYZ` が現れず `***` に置換 | — |

## 9. 完了条件

- T03-01〜T03-22 が通る（`docker compose -f deploy/docker-compose.yml run --rm dev pytest`）
- `python -m jevfwd.cli --help` と `jevfwd --help`（`dev` イメージは `pip install -e .[dev]` 済み）が同じ出力
- M3 完了時：`jevfwd bundle --once` が 3.8 のとおり動き、T03-04 が 8 スタブに更新されている
- `docs/事前宣言.md` に貼る `frozen question_version=v2 …` の行が `freeze-questions` の stdout から得られる（実行は段階2開始時、人が行う）

## 10. 基本設計からの差分

| ★ | 変更 | 基本設計書の修正箇所 |
|---|---|---|
| 1 | サブコマンド `init-db` を追加（明示マイグレーション。ワーカーは自動マイグレーションしない） | 2章 `cli.py` のコメント、8章 M1 |
| 4 | サブコマンド `bundle` を追加（M3 の束ね〜state〜判定キューのプロセス） | 2章 `cli.py` のコメント、8章 M3 |
| 2 | 終了コード 3（スキーマ不一致）を予約 | — |
| 3 | `freeze-*` の既定パスは `settings.yaml` の `paths.*` から。`--config-dir` 引数は設けない | — |
| 5 | `bundle` は `cli` が `state_of` を組み立てて `runner.run_once` に注入する。`cli` は `bundles` に INSERT しない（task 017） | 3.2 の 8、3.4 冒頭 |
| 6 | 開発・テストは Docker の `dev` ターゲットで行う。`deploy/Dockerfile` と compose の `dev` 分は M1 で作る | 6章、8章 M1 |
