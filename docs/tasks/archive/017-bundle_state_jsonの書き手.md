# 017: `bundles.state_json` を付けて INSERT するのは誰か（04 と 05 の食い違い）

- Status: done
- Owner: claude
- Blocks: 実装セッション 3a（M3）
- Created: 2026-09-20
- Related: 詳細設計 04-束ね 3.4・7章、05-state構築 1章・5章、03-CLI 3.7、00-共通規約 8章（境界表）、01-凍結ログ 4.3（`bundles` の DDL）、ADR 014

## 内容
`bundles` は追記専用で、`state_json` `state_version` `state_chars` `state_completeness_json` はその列。したがって state は bundle 行を INSERT する**前**に組めていなければならない。
ところが 04-束ね の `run_once` は `repo.insert_bundle(conn, _to_row(p, now))` で state 無しに INSERT し、05-state構築 1章は「`bundles` への INSERT は `cli` が `state_json` を付けて書く」と書いていた。`bundle` は `state` を import できない（00 境界表）ので、このままでは M3 で state_json が永久に NULL になるか、bundle 行を二重に作ることになる。

## 完了条件
- 書き手を1つに決め、04・05・03 の該当箇所を追補する
- `run_once` のテスト（T04-32/33）が state 無しでも通る形を保つ

## メモ
- 2026-09-20：**`run_once` に state 構築関数を注入する**ことに決めた（境界表は変えない）。
  - `run_once(conn, now, cfg, filters, calendar, state_of: Callable[[BundlePlan], StateResult | None]) -> list[int]`
  - `runner` は `plan_bundles` の後・`db.transaction` の**前**に `state_of(plan)` を呼ぶ（中部電力 28 万字の切り詰めを書き込みロックの中でやらない）。`bundle_role='excluded'` は呼ばず、state 列は NULL
  - `state_of` が `JevfwdError` を投げたら `state_json=NULL`、`flags` に `state_error:<例外クラス名>` を付けて行を残し WARN ログ（失敗は行として記録する。CLAUDE.md）。判定側（07-判定、M4）は `state_json IS NULL AND bundle_role <> 'excluded'` を「エラー判定行を残す対象」として扱う
  - `state_of` を組むのは `cli.cmd_bundle`（`queries` で events 本文と `logical_docs` を `DocInput` に変換し、`build_state(..., NullMarketContext(), DbDisclosureContext(conn), cfg)` を呼ぶ）
  - テストは T04-32/33 を `state_of=lambda p: None` で通し、T04-35 を追加（返した `state_json` がそのまま行に入る／例外時に `state_error` フラグで行が残る）
  - 採らなかった案：`run_once` を `plan_once` / `commit_plans` に割って `cli` が間で state を組む。runner の API が2つになり、coverage の読み直し（4.1 の「唯一の砦」）が `cli` 側の責務になるので避けた
  - ADR は作らない（00 の境界表の範囲内の接続方法の決定。04 ★11 に残す）。done
