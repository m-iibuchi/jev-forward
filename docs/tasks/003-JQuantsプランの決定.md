# 003: J-Quants Light / Standard の決定

- Status: open
- Owner: human
- Blocks: `docs/detailed/08-採点.md`、ADR 017 の market_cache 有効化、段階2
- Created: 2026-09-20
- Related: 要件6章「外部データ」、10章、ADR 017

## 内容
- Light（1,650円/月、前営業日まで）：日足・銘柄一覧・財務は取れる。TOPIX 指数四本値は取れないので TOPIX 連動 ETF（1306 等）の日足で代用する
- Standard（3,300円/月）：指数四本値、当日引け後の日足
決め手は (a) TOPIX を指数で取るか ETF で代用するか、(b) 採点の遅れ（1営業日）を許容するか。

## 完了条件
- プランを決め、TOPIX の取得方法（指数 or 代用 ETF コード）を `config/settings.yaml` の `score.topix_source` に反映
- ADR を作る

## メモ
