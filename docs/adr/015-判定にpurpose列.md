# 015: judgments に purpose 列を持ち主分析は full のみ

- Status: Accepted
- Date: 2026-09-20
- Related: 要件F1-1（表題のみの暫定判定）、F3-2（2版並走）、F7-3（週次再判定）、基本設計3.4・4章、ADR 024（暫定→本判定は superseding bundle）

## Context
同一 bundle に対して複数の judgment 行が発生する：(1) PDF取得失敗時の表題のみ暫定判定、(2) PDF到着後の本判定、(3) jev-latest / jev-preview の並走、(4) 週次の固定10件再判定。基本設計の主分析条件は `model='jev-latest' AND delayed=0 AND error_type IS NULL` だが、(1) と (4) を区別する列がなく、暫定判定や再判定が主分析に混入する。

## Decision
- `judgments.purpose TEXT NOT NULL` を追加。値は `full`（本判定）/ `provisional`（表題のみ暫定）/ `recheck`（版入れ替わり検知の再判定）
- 主分析は `purpose='full' AND model='jev-latest' AND delayed=0 AND error_type IS NULL`
- 週次再判定の対象10件は `tests/fixtures` 由来の固定 state を bundle として登録し（`bundle_role='fixture'`）、`purpose='recheck'` で判定する。実開示の bundle には recheck を行わない
- 暫定判定後に PDF が到着した場合、同じ bundle に `purpose='full'` の行を追加する。暫定判定の行は残す

## Alternatives
- bundle を分ける：同じ開示に複数 bundle ができ、件数の定義が崩れる
- 再判定を別テーブルに：生レスポンスの保存・エラー記録の仕組みが二重になる

## Consequences
- `answers` はそのまま judgment_id で紐付く
- ダイジェストは `full` を優先し、`full` が無ければ `provisional` を「暫定」と表示して使う
