# 006: state v2 JSON Schema の作成と凍結

- Status: open
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
