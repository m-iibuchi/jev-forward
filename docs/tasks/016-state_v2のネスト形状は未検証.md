# 016: state v2 のネスト形状は Jev で未検証

- Status: open
- Owner: human
- Blocks: M4 の契約テスト（`judge --once`）、`docs/事前宣言.md` の凍結
- Created: 2026-09-20
- Related: 要件2章「Playground検証で確認したこと」、基本設計3.3、詳細設計 05-state構築、ADR 002・003、`scripts/make_state.py`

## 内容
Playground 検証52回（問い版 v2、主語固定文、TOB の束ね例外、再現性の確認）は、`scripts/make_state.py` が作る**平坦な state**（`company` / `code` / `title` / `published_at` / `body`）で行った。
一方、基本設計3.3 と `docs/contracts/state.v2.schema.json` の v2 は**入れ子**（`issuer` / `market_context` / `forecast_context` / `primary` / `secondary` / `other_titles`）で、この形で Jev に投げたことは一度も無い。

形が変われば出力も変わりうる。変わった場合、ADR 002・003 の根拠（主語固定文の効果、束ねで判定が割れること）は平坦な state でのものなので、そのまま持ち越せるとは限らない。

## 完了条件
- M4 の最初の `jevfwd judge --once --bundle <id>`（人が手で実行）で、入れ子の state に対する応答を採る
- Playground で使った同じ開示（ほぼ日、フェローテック、レオパレス）を入れ子の state で投げ直し、direction / impact が検証ログの値と大きく違わないことを確かめる
- 違った場合は、state の形を平坦に戻すか、ADR 002・003 の根拠を採り直すかを決めて ADR を書く

## メモ
- 2026-09-20：詳細設計 05 を書く過程で判明。段階2の開始（事前宣言の凍結）前に必ず潰す
