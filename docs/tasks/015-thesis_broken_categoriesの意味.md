# 015: entry_rules.exit.thesis_broken_categories の値の意味

- Status: open
- Owner: human
- Blocks: `docs/detailed/11-ダイジェスト模擬執行.md`（M7、出口ルール `thesis_broken`）
- Created: 2026-09-20
- Related: 要件 8章「前提の崩壊」、基本設計 3.9・5章、`config/entry_rules.v1.yaml`、`config/questions.v2.json` の `category`

## 内容
`entry_rules.v1.yaml` の `exit.thesis_broken_categories: [下方修正, 不祥事, 監理]` は日本語の語だが、問い版 v2 の `category` の値は `earnings / dividend / … / misconduct / governance / …` で対応しない。「保有中に下方修正・不祥事・監理指定が出たら翌朝売る」をどう機械判定するか：
1. 後続開示の Jev 判定で `direction=down ≥ X かつ category ∈ {earnings, misconduct}`
2. 表題パターン（「業績予想の修正」＋数値で下方、「監理銘柄」「特設注意市場銘柄」）
3. 両方の OR

## 完了条件
- 判定規則を決め、`entry_rules.v2.yaml` で値を機械可読な形にする（v1 は変更しない。M7 開始前に）
- 詳細設計 02 の `ExitCfg.thesis_broken_categories` の型を確定する

## メモ
- 2026-09-20：M1 では `list[str]` として読み込むだけ（02-設定 3.1）
