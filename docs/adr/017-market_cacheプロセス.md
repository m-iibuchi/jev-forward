# 017: VPS上の market_cache プロセスで直前終値等を日次更新

- Status: Accepted
- Date: 2026-09-20
- Related: 要件F2-1、6章「外部データ」、基本設計1章・3.3・3.7

## Context
state の `market_context`（直前終値・時価総額・直近20日リターン・平均売買代金）とダイジェストのエントリー条件（時価総額・流動性・織り込み度）は VPS 側で判定時に必要。基本設計は「VPS側にも銘柄マスタと直近終値の軽量キャッシュを置く」としていたが、誰がいつ更新するかが未定だった。J-Quants の取得は当初ローカルPCのみの想定。

## Decision
- VPS に5番目のプロセス `market_cache` を追加。平日 06:30 JST に J-Quants から (a) 上場銘柄一覧（市場区分・業種・上場日）、(b) 前営業日の全銘柄日足、(c) TOPIX（または代用ETF）を取得し、`prices` と `listed_master` に追記する
- state builder とダイジェストは `prices` の最新営業日を参照。無ければ null で進み `state_completeness_json` に欠損を記録
- 段階1（ロガー）では market_cache を無効化して null 許容で稼働してよい。段階2開始前に有効化
- `JQUANTS_REFRESH_TOKEN` は VPS の環境変数に置く（読み取り専用のデータ取得のみ）

## Alternatives
- ローカルPCで取得して rsync：自宅回線に依存し、ADR 001 の趣旨に反する
- 判定時に都度 J-Quants を叩く：判定の遅れと API 呼び出し数が増える

## Consequences
- J-Quants の呼び出しは日次1回・数リクエスト。Light プランの制限内
- `prices` は追記専用ではないが、同一 (code, date) の再取得は `source_version` を変えた新行として追加し UPDATE しない（ADR 014 の規約）
- 時価総額は日足終値 × 発行済株式数。株式数は J-Quants 財務データ、無ければ null
