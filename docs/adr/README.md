# ADR（Architecture Decision Records）

設計判断を1判断1ファイルで残す。判断の「結果」だけでなく「なぜ他の案を採らなかったか」を書く。
実装者（人・モデルを問わず）が「この制約はなぜあるのか」を辿れることが目的。

## 採番と命名

- `NNN-短い日本語タイトル.md`。NNNは3桁ゼロ埋め、通し番号、欠番・再利用なし。タイトルは空白を入れず、識別子（market_cache、purpose 等）はそのまま使ってよい
- 001〜008 は基本設計書 v1（2026-09-19）9章の判断を起こしたもの
- 009〜 は要件v3の改訂（2026-09-20）以降の判断

## 書式

```
# NNN: タイトル

- Status: Proposed | Accepted | Superseded by NNN | Deprecated
- Date: YYYY-MM-DD
- Related: 要件・設計・検証ログの該当箇所、関連ADR

## Context（何が問題だったか）
## Decision（何を決めたか）
## Alternatives（採らなかった案と理由）
## Consequences（この判断で生じる制約・作業）
```

## 運用

- 既存ADRの Decision は書き換えない。判断を変えるときは新しいADRを作り、旧ADRの Status を `Superseded by NNN` にする
- 要件・設計書の本文には判断の要点だけを書き、根拠はADRへリンクする
- 実装中に判断が必要になったら、まず `docs/tasks/` に起票し、決まったらADRにする

## 一覧

| # | タイトル | Status |
|---|---|---|
| 001 | VPS主・NAS副の構成 | Accepted |
| 002 | 主語固定文を全問いに入れ、評価軸は入れない | Accepted |
| 003 | TOB・MBO・株式交換は束ねの例外 | Accepted |
| 004 | 重複排除はPDFのSHA-256 | Accepted |
| 005 | 採点は翌営業日始値→N営業日後終値 | Accepted |
| 006 | 現物のみ・20営業日時間切れ・△8%損切り・利確なし | Accepted |
| 007 | SUEのみをベースラインに含める | Accepted |
| 008 | 暗号資産での練習を省略 | Accepted |
| 009 | 遅延判定の閾値を300秒にし、取得遅れは別列に記録 | Accepted |
| 010 | ダイジェストは18:30速報便と07:30確定便の2便 | Accepted |
| 011 | 主検証の母集団は引け後開示のみ | Accepted |
| 012 | 決算短信もエントリー対象に含める | Accepted |
| 013 | 関門1の検定は日別ブロック・ブートストラップ | Accepted |
| 014 | 追記専用をSQLiteトリガーで担保 | Accepted |
| 015 | judgments に purpose 列を持ち主分析は full のみ | Accepted |
| 016 | events は1PDF=1行、連番表題の結合は bundle 層 | Accepted |
| 017 | VPS上の market_cache プロセスで直前終値等を日次更新 | Accepted |
| 018 | 原本PDFはNAS移送後30日でVPSから削除可 | Accepted |
| 019 | 除外と重要度低下を分け、低下は flags_json で表す | Accepted |
| 020 | 問い版の凍結は CLI freeze-questions で行い、JSONファイルは不変 | Accepted |
| 021 | ledger のハッシュ連鎖は明示 id の範囲で日次に計算する | Accepted |
| 022 | 束ね待ちの検出は event_id で追い、時刻の窓では探さない | Accepted |
| 023 | TOB の束ね例外は対象者側だけに適用する | Accepted |
| 024 | 暫定判定に本文が届いたら superseding bundle を作る | Accepted |
| 025 | 営業日カレンダーは版付き設定ファイルに持ち settings が読む | Accepted |
| 026 | 切り詰めの予算は送信 JSON の文字数で測り、章の抜粋は別項目に置く | Accepted |
| 027 | superseding bundle が引き継ぐ flags は `event_note:` だけ | Accepted |
