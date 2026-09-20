# tasks — 作業中に挙がったタスクの管理

設計・実装の途中で出てきた「後でやる」「人が確認する」「決めないと進めない」を1タスク1ファイルで残す。
チケットシステムの代わり。Claude Code や他モデルが作業中に見つけた未決事項もここに起票する。

## 命名

- `NNN-短い日本語タイトル.md`。3桁通し番号、欠番・再利用なし。空白は入れない
- `段階0_人手チェックリスト.md` だけは例外で、段階0の人手チェックリストをまとめて持つ
- 完了したファイルは `archive/` に移す。**番号は archive/ と合わせて通し**（再利用しない）

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

- 完了したら Status を `done`（または `dropped`）にし、メモに結果と日付を書いてから `git mv` で `archive/` へ移す。**削除はしない**
- 一覧は下の2つの表を手で更新する（進行中／完了）。archive/ に移したら「進行中」の行を「完了」の表へ移す
- 判断が必要なタスクは、決まったら ADR を作り、タスクのメモから ADR 番号を参照する
- 実装セッション中に見つけた未決は、その場でタスクを起票し、仮定を明示して進める（CLAUDE.md「やってほしいこと」）
- 他の文書からリンクするときは、完了後に `archive/` へ移ることを見込んで「task NNN」と番号で書く（パス直書きを避ける）

## 進行中

| # | タイトル | Status | Owner | Blocks |
|---|---|---|---|---|
| — | [段階0の人手チェックリスト](段階0_人手チェックリスト.md) | open | human | M2/M4詳細設計、段階1 |
| 001 | [TDnet新着一覧の機械取得方法と利用条件の確認](001-TDnet一覧の取得方法.md) | blocked | human | 06-fetch 詳細設計、M2 |
| 002 | [Jev生レスポンスの版情報と応答スキーマの採取](002-Jev生レスポンスの採取.md) | blocked | human | 07-judge 詳細設計、M4、contracts/typesafe |
| 003 | [J-Quants Light / Standard の決定](003-JQuantsプランの決定.md) | open | human | 08-score 詳細設計、market_cache |
| 004 | [コストモデルの数値確定](004-コストモデルの数値.md) | open | human | settings.yaml、日次コスト監視 |
| 005 | [前回予想・前期実績のXBRL抽出範囲の決定](005-前回予想のXBRL抽出.md) | open | any | F2-3、SUEベースライン |
| 009 | [kickoff の書き換え（詳細設計参照型）](009-実装指示の書き換え.md) | open | claude | 実装セッション開始 |
| 010 | [特別気配（寄らず）の判定方法](010-特別気配の判定.md) | open | any | F5-2 |
| 011 | [東証営業日カレンダーの確定](011-営業日カレンダー.md) | in_progress | human | trading_calendar.v1.yaml の人手突合（段階2まで） |
| 012 | [9/24以降の答え合わせを検証ログに追記](012-答え合わせの追記.md) | open | human | — |
| 015 | [entry_rules.exit.thesis_broken_categories の意味](015-thesis_broken_categoriesの意味.md) | open | human | 11-ダイジェスト模擬執行（M7） |
| 016 | [state v2 のネスト形状は Jev で未検証](016-state_v2のネスト形状は未検証.md) | open | human | M4 の契約テスト、事前宣言の凍結 |

## 完了（`archive/`）

| # | タイトル | 結果 | 完了日 |
|---|---|---|---|
| 006 | [state v2 JSON Schema の作成と凍結](archive/006-state_v2スキーマ.md) | `docs/contracts/state.v2.schema.json` を作成 | 2026-09-20 |
| 007 | [詳細設計 M1](archive/007-詳細設計M1.md) | `docs/detailed/00〜03`、ADR 021 | 2026-09-20 |
| 008 | [詳細設計 M3](archive/008-詳細設計M3.md) | `docs/detailed/04〜05`、ADR 022〜026 | 2026-09-20 |
| 013 | [暫定判定→本判定のときの state の置き場](archive/013-暫定判定のstateの置き場.md) | superseding bundle（ADR 024） | 2026-09-20 |
| 014 | [filters の除外判定と市場区分の役割分担](archive/014-コード除外パターンと市場区分.md) | 判定順序を固定、段階1の穴を許容（04-束ね 4.5・4.6） | 2026-09-20 |
