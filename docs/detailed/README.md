# detailed — モジュール別の詳細設計（契約＋受入テスト）

基本設計書（`docs/基本設計書.md`）の各モジュールを、実装者（人・モデルを問わず）が迷わず書ける粒度に落としたもの。
実装セッションは対応するファイルを読み、**受入テスト一覧を先に `tests/test_*.py` に写してから**実装する（task 009 の kickoff）。

## ファイル一覧

| # | ファイル | 対象 | マイルストーン | 状態 |
|---|---|---|---|---|
| 00 | [00-共通規約.md](00-共通規約.md) | 全モジュール共通（時刻・コード・JSON・例外・境界・テスト規約） | M1 | 2026-09-20 初版 |
| 01 | [01-凍結ログ.md](01-凍結ログ.md) | `store/`（schema.sql 全文、db、rows、repo、queries、freeze、migrations） | M1 | 2026-09-20 初版 |
| 02 | [02-設定.md](02-設定.md) | `settings.py`（settings / entry_rules / filters / 秘密）、`judge/questions.py` | M1 | 2026-09-20 初版 |
| 03 | [03-CLI.md](03-CLI.md) | `cli.py`（`init-db` `freeze-questions` `freeze-state`、未実装スタブ） | M1 | 2026-09-20 初版 |
| 04 | 04-束ね.md | `bundle/`（grouper、filters の分類） | M3 | task 008 |
| 05 | 05-state構築.md | `state/`（builder、truncate、context） | M3 | task 008、task 006 |
| 06 | 06-取得.md | `fetch/` | M2 | task 001 が done になるまで書かない |
| 07 | 07-判定.md | `judge/client.py`、judge_worker | M4 | task 002 が done になるまで書かない |
| 08 | 08-監視通知.md | `monitor/`、ledger 算出、バックアップ | M5 | — |
| 09 | 09-市場データ.md | `market/` | M6 | task 003 |
| 10 | 10-採点.md | `score/` | M6 | — |
| 11 | 11-ダイジェスト模擬執行.md | `digest/`、`paper/` | M7 | — |

## 各ファイルの章構成

1. 責務（何をする・しない）
2. 依存（import してよいモジュール、外部ライブラリ）
3. 公開インターフェース（関数・クラスのシグネチャと意味）
4. データ契約（DDL、JSON、YAML の形。ファイル全文を載せる場合はここ）
5. エラー時の振る舞い（どの例外を投げる／どの行を残す／終了コード）
6. 設定項目（`config/settings.yaml` のどのキーを読むか）
7. 擬似コード（主要関数のみ。実装がそのまま写せる程度）
8. 受入テスト一覧（表：ID / テスト関数名 / 前提・入力 / 期待 / 使う fixture）
9. 完了条件
10. 基本設計からの差分（★ 付きで列挙し、基本設計書のどこを直したかを書く）

## テストID

- `Tnn-mm`：`nn` は詳細設計のファイル番号、`mm` は2桁通し。欠番・再利用なし
- テスト関数は英語名、docstring の1行目に ID を書く（例：`"""T01-07: UPDATE は 9 テーブルすべてで IntegrityError"""`）
- テストは `tests/test_<対象>.py` に置く。01 → `tests/test_store.py`、02 → `tests/test_settings.py` と `tests/test_questions.py`、03 → `tests/test_cli.py`、00 → `tests/test_conventions.py` と `tests/test_common.py`
- fixture は `tests/fixtures/` の実ファイルを使う。受入テストの表にファイル名を書く（存在しないファイルを指さない）

## 写経の手順（実装セッション向け）

1. 対象ファイルの 1〜6 章を読む
2. 8 章の表を上から順に `tests/test_*.py` へ写す（この時点では全部 fail する）
3. 7 章の擬似コードに沿って実装し、テストを通す
4. 実装中に表と食い違う判断をしたら、まず `docs/tasks/` に起票し、詳細設計を直してからコードを直す（コードだけ直さない）
