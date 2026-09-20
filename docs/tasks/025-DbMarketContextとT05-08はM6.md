# 025: `DbMarketContext`（と受入テスト T05-08）は M6 に送る

- Status: open
- Owner: claude
- Blocks: M6（09-市場データ、`market_cache`）
- Created: 2026-09-20
- Related: `docs/detailed/05-state構築.md` 3.2・4.7・8章（T05-08）、`docs/実装セッション指示.md` セッション 3b、ADR 017、task 003

## 内容
task 021（セッション 3b）の受入テスト T05-08（`test_prev_close_uses_last_completed_bar`）は `DbMarketContext` と `prices` の行を前提にしているが、
`docs/実装セッション指示.md` のセッション 3b は「`state/context.py`：… `NullMarketContext`、`DbDisclosureContext`（`DbMarketContext` は M6）」と明記していて、食い違う。

M3 で `DbMarketContext` を書かない理由：

- 段階1は `market_cache.enabled: false`（ADR 017）なので、書いても動かない死んだコードになる
- `prices` は `PRIMARY KEY (code, date, source_version)` で、同じ日に複数の `source_version` が入りうる。どれを採るかは J-Quants のプラン（task 003）と 09-市場データ の詳細設計が決めることで、いま決め打ちすると契約を先に固めてしまう
- 「`published_at` より前に確定している日足」の定義（当日の引け後でも当日分を使わないか）は 4.7 に文章としてはあるが、`market_cache` の走る時刻（06:30）と合わせて 09 で確定させたい

## 完了条件
- 09-市場データ の詳細設計で `prices` の読み方（`source_version` の選び方、確定済み日足の定義）を決める
- `state/context.py` に `DbMarketContext` を実装し、T05-08 を `tests/test_state.py` に足して通す
- `completeness.sources["market_context"]` が `db` になることを確認する

## メモ
- 2026-09-20：起票。task 021 では T05-01〜07・T05-09〜25（24件）を実装し、T05-08 だけ M6 に送った。05-state構築 8章の表の該当行にもそう書いた
- `MarketContextProvider` には `source`（`"null"` / `"db"`）を持たせた。`completeness.sources` を推測で埋めないため（05 3.2）
