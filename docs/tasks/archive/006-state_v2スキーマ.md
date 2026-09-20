# 006: state v2 JSON Schema の作成と凍結

- Status: done
- Owner: claude
- Blocks: `docs/detailed/05-state構築.md`、`freeze-state --version v2`
- Created: 2026-09-20
- Related: 要件F2-5、基本設計3.3、ADR 020

## 内容
基本設計3.3の例 JSON を正として `docs/contracts/state.v2.schema.json`（JSON Schema draft 2020-12）を書く。null 許容項目（market_context、forecast_context）と `state_completeness` の形も含める。

## 完了条件
- 基本設計3.3の例 JSON が valid
- `tests/fixtures` の本文から作った state が valid
- 詳細設計 05-state から参照される

## メモ
- 2026-09-20：`docs/contracts/state.v2.schema.json` を作成（draft 2020-12）。基本設計3.3 の例と段階1（全 null）の例で valid、未知キーを弾くことを確認。`state_completeness` は `$defs` に入れ、**Jev に送る state には含めない**（`bundles.state_completeness_json` 専用）。`primary.excerpts`（報告書型の章抜粋、ADR 026）を追加。詳細設計 05-state構築 4.1・4.6 から参照。done。
