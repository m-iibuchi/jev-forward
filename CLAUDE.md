# CLAUDE.md — jev-forward

日本株の適時開示をJev（TypeSafe AI）で判定し、結果が出る前に凍結記録して後から採点する、個人用のフォワードテスト基盤。詳細は `docs/要件定義書.md`（要件）と `docs/基本設計書.md`（設計）。実装前に両方を読むこと。モジュールを実装するときは `docs/detailed/` の該当ファイル（契約＋受入テスト）も読み、テストを先に写す。

## ドキュメントの置き場所

ドキュメント系ファイル（`docs/` 配下の .md）の名前は日本語にする。`README.md` と `CLAUDE.md` は慣例名のまま。コードや設定から参照するファイル（JSON Schema、YAML、.py、fixtures）は英語のまま。

- `docs/adr/`：設計判断の記録。1判断1ファイル、`NNN-日本語タイトル.md`、書式と一覧は `docs/adr/README.md`。既存ADRの Decision は書き換えず、変えるときは新ADRで Supersede する
- `docs/tasks/`：作業中に挙がった未決・後回し・人手確認。1件1ファイル、書式と一覧は `docs/tasks/README.md`。完了したものは `docs/tasks/archive/` に移す（削除はしない。番号は通し）。実装中に判断が要る箇所を見つけたら、まずここに起票し、仮定を明示して進める
- `docs/detailed/`：モジュール別の詳細設計（責務・公開インターフェース・データ契約・エラー時の振る舞い・受入テスト一覧）
- `docs/contracts/`：JSON Schema 等のデータ契約。state の書式は `state.v2.schema.json` が正

## このプロジェクトの絶対ルール

1. **凍結ログは追記専用**。`events / bundles / judgments / answers / heartbeat / ledger / question_versions / state_versions / my_calls` に対する UPDATE / DELETE をアプリコードに書かない。`store/repo.py` はINSERTしか公開しない（読み取りは `store/queries.py`）。DB 側にも UPDATE/DELETE を拒否するトリガーを置き、外さない（ADR 014）。訂正が必要なら新しい行を追加して旧行を参照する
2. **問い・state書式・エントリー条件は版管理**。`config/questions.vN.json` 等を編集して上書きしない。変更は新しい版ファイルを作り、CLI `freeze-questions` で `question_versions` に凍結する（ADR 020）。既存の版ファイルは絶対に変更しない（テストが SHA-256 で検知する）
3. **問いの文言に評価軸を入れない**。主語固定文（誰の株価かの明示）は入れるが、「割高さで判断」「収益性で判断」のような方向を含意する語句は誘導になる。文言を変えたいときは提案に留め、人の承認を得てから新版を作る
4. **過去データでの検証をしない**。Jevに2026-09-15より前の開示を判定させて成績を測る機能は作らない。バックテスト用のコードを頼まれたら、その理由（学習データ汚染・先読み）を説明して断る
5. **秘密情報をコードに書かない**。`TYPESAFE_API_KEY`, `JQUANTS_REFRESH_TOKEN`, `NTFY_TOPIC` は環境変数。ログにも出さない
6. **時刻はUTCで保存**。表示だけJST。公表時刻・受信時刻・Jev応答時刻の3点を必ず残す
7. **売買を実行するコードは書かない**（段階4まで）。`executor` インターフェースの `paper` と `manual` 実装のみ。証券会社APIの実装は明示的な指示があるまで作らない

## 技術スタック

- Python 3.11+、標準ライブラリ優先。外部依存は `pymupdf`, `httpx`, `pyyaml`, `pydantic` 程度に抑える
- SQLite（WALモード）。ORMは使わず `sqlite3` 直接。DDLは `src/jevfwd/store/schema.sql`
- テストは `pytest`。`tests/fixtures/` にPlayground検証で使った実際の開示本文がある。束ね・切り詰め・主語埋め込みのテストはこれを使う
- Docker + supervisord でVPS常駐。ローカル実行は `python -m jevfwd.cli <subcommand>`

## コーディング規約

- 1モジュール1責務。`fetch / bundle / state / judge / store / market / monitor / digest / score / paper` の境界を越えて直接importしない（`store` は全員が使ってよい。`market` は `state` `digest` `score` が使ってよい）
- 外部I/O（TDnet、TypeSafe、J-Quants、ntfy）は必ず薄いクライアントに閉じ込め、テストではモックする
- 失敗は握りつぶさない。取得失敗・判定エラーも**行として記録**する（欠損の相関分析のため）。例外は上位で捕まえてheartbeatに書く
- 設定値（周期、閾値、パス）は `config/*.yaml` から読む。コードにマジックナンバーを書かない
- 日本語のログメッセージ・コメントで構わない。識別子は英語

## 検証で分かっている事実（設計の前提）

- Jevの入力上限は約5万字。4万字超は `state/truncate.py` で切り詰める
- 同一入力の判定は再現する。再判定は版の入れ替わり検知（週次・固定10件）のためだけに行う
- TOB・MBO・株式交換の開示は束ねない（無配等を束ねると判定が割れる）
- 同一表題の開示が別内容のことがある（リベルタ）。重複判定はPDFのSHA-256で行う
- ETF・ETN・REIT・インフラ投資法人・整理監理銘柄は判定しない（統計を汚す）
- 応答時間は最大762msを観測。タイムアウトは10秒、リトライ3回

## やってほしいこと / やらないでほしいこと

- 設計と要件に矛盾を見つけたら、実装を進める前に指摘する
- 不明点は `docs/tasks/NNN-*.md` に起票し（一覧も更新）、仮定を明示して進める
- 設計判断は `docs/adr/NNN-*.md` にADRとして残す（一覧も更新）
- 「とりあえず動く」ために追記専用や版管理を崩さない。崩す必要があると感じたら、その場で止めて相談する
