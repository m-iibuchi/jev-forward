# 013: 暫定判定→本判定のときの state の置き場

- Status: done
- Owner: claude
- Blocks: `docs/detailed/05-state構築.md`、`docs/detailed/07-判定.md`（M3 / M4）
- Created: 2026-09-20
- Related: ADR 015、基本設計 3.4・4章 `bundles.state_*`、詳細設計 01 4.2

## 内容
ADR 015 は「表題のみで暫定判定した bundle に PDF が後から到着したら、同じ bundle に `purpose='full'` の行を追加する」としている。しかし state（`state_json` `state_version` `state_chars` `state_completeness_json`）は `bundles` に1組しか無く、暫定時の state で凍結される。full 判定の state は `judgments.request_json`（生リクエスト）の中にしか残らない。

選択肢：
1. state 列を `judgments` 側に持つ（`judgments.state_json` 等を追加、`bundles.state_*` は「最初の state」として残す）
2. `bundle_states` テーブルを追加（bundle_id, purpose, state_json, …）
3. 現状のまま（full の state は `request_json` から取り出す。`state_completeness` は失われる）

## 完了条件
- 選択肢を1つ決め ADR を書く
- M1 の DDL は変えない。必要な列は `store/migrations/002_*.sql` の `ALTER TABLE ADD COLUMN` か新表で足す（01-凍結ログ 4.4）

## メモ
- 2026-09-20：詳細設計 01 の DDL は基本設計4章の列構成を保った。暫定判定の頻度（PDF 取得失敗率）を M2 で見てから決めてよい
- 2026-09-20：選択肢1〜3のいずれも採らず、**superseding bundle**（ADR 024）に決めた。`events` が追記専用である以上、後から届く PDF は新しい event 行になるので、同じ bundle を使い回せない。暫定 state は旧 bundle の `state_json`、本判定の state は新 bundle の `state_json`。列も表も増えない。詳細設計 04-束ね 4.8、05-state構築 4.8。done。
