# tasks — 作業中に挙がったタスクの管理

設計・実装の途中で出てきた「後でやる」「人が確認する」「決めないと進めない」を1タスク1ファイルで残す。
チケットシステムの代わり。Claude Code や他モデルが作業中に見つけた未決事項もここに起票する。

## 命名

- `NNN-短い日本語タイトル.md`。3桁通し番号、欠番・再利用なし。空白は入れない
- `段階0_人手チェックリスト.md` だけは例外で、段階0の人手チェックリストをまとめて持つ

## 書式

```
# NNN: タイトル

- Status: open | blocked | in_progress | done | dropped
- Owner: human | claude | any
- Blocks: このタスクが終わらないと進めないもの（M2詳細設計 等）
- Created: YYYY-MM-DD
- Related: 要件・設計・ADR・検証ログの該当箇所

## 内容
## 完了条件
## メモ（進捗、決まったこと。日付付きで追記）
```

## 運用

- 完了してもファイルは移動・削除しない。Status を `done` にし、メモに結果と日付を書く
- 判断が必要なタスクは、決まったら ADR を作り、タスクのメモから ADR 番号を参照する
- 実装セッション中に見つけた未決は、その場でタスクを起票し、仮定を明示して進める（CLAUDE.md「やってほしいこと」）
- 一覧は下表を手で更新する

## 一覧

| # | タイトル | Status | Owner | Blocks |
|---|---|---|---|---|
| — | [段階0の人手チェックリスト](段階0_人手チェックリスト.md) | open | human | M2/M4詳細設計、段階1 |
| 001 | TDnet新着一覧の機械取得方法と利用条件の確認 | blocked | human | 06-fetch 詳細設計、M2 |
| 002 | Jev生レスポンスの版情報と応答スキーマの採取 | blocked | human | 07-judge 詳細設計、M4、contracts/typesafe |
| 003 | J-Quants Light / Standard の決定 | open | human | 08-score 詳細設計、market_cache |
| 004 | コストモデルの数値確定（TypeSafe単価、J-Quants、手数料） | open | human | settings.yaml、日次コスト監視 |
| 005 | 前回予想・前期実績のXBRL抽出範囲の決定 | open | any | F2-3、SUEベースライン |
| 006 | state v2 JSON Schema の作成と凍結 | open | claude | 05-state 詳細設計 |
| 007 | 詳細設計 M1（00-共通規約, 01-凍結ログ, 02-設定, 03-CLI） | done | claude | セッション1（実装） |
| 008 | 詳細設計 M3（04-bundle, 05-state） | open | claude | セッション3（実装） |
| 009 | kickoff の書き換え（詳細設計参照型） | open | claude | 実装セッション開始 |
| 010 | 特別気配（寄らず）の判定方法 | open | any | F5-2 |
| 011 | 東証営業日カレンダーの取得方法 | open | any | digest 2便、採点 |
| 012 | 9/24以降の答え合わせを検証ログに追記 | open | human | — |
| 013 | 暫定判定→本判定のときの state の置き場 | open | claude | 05-state構築、07-判定 |
| 014 | filters の exclude_code_patterns と listed_master の役割分担 | open | any | 04-束ね、09-市場データ |
| 015 | entry_rules.exit.thesis_broken_categories の値の意味 | open | human | 11-ダイジェスト模擬執行（M7） |
