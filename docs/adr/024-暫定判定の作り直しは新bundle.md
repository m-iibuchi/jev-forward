# 024: 暫定判定に本文が届いたら、同じ bundle を使わず superseding bundle を作る

- Status: Accepted
- Date: 2026-09-20
- Related: ADR 014・015（補足）、task 013、詳細設計 04-束ね 4.8、05-state構築 4.8、01-凍結ログ 4.5

## Context
ADR 015 は「表題のみで暫定判定した bundle に PDF が後から到着したら、同じ bundle に `purpose='full'` の行を追加する」と書いた。しかし `events` は追記専用なので、表題だけで登録した行に本文を足すことはできない（UPDATE はトリガーが拒否する）。後から届いた PDF は**新しい event 行**になる。

その結果、同じ bundle を使い回すと次の不整合が起きる。

- `bundles.event_ids_json` に新しい event が入らない（列は書き換えられない）
- `bundles.state_json` は暫定時点の state のまま。本判定に使った state は `judgments.request_json` の中にしか残らず、`state_completeness` は失われる（task 013 の問題そのもの）
- 束ね層から見ると新しい event は「未カバー」なので、放っておくと別 bundle ができて二重計上になる

## Decision
- 後から届いた本文つき event が既存 bundle の窓に入り、かつ連番を除いた表題が一致するなら、**全 event を含む新しい bundle** を `supersedes_id=<旧 bundle_id>` で作る
- 新 bundle で state を組み直し、`purpose='full'` で判定する。旧 bundle と `purpose='provisional'` の判定はそのまま残る
- 新 bundle の `flags_json` に `supersedes:provisional` を付ける
- 主検証・ダイジェスト・採点は `queries.current_bundle`（superseded でない方）だけを使う（01-凍結ログ 4.5）
- task 013 の選択肢（judgments に state 列を足す／`bundle_states` 表を作る／現状のまま）はどれも採らない。列も表も増えない

## Alternatives
- `judgments.state_json` 等を追加（task 013 の選択肢1）：`ALTER TABLE ADD COLUMN` で足せるが、state の置き場が2か所になり、`bundles.state_*` と意味が重なる
- `bundle_states` 表（選択肢2）：凍結テーブルが増え、トリガー本数が変わる（ADR 022 と同じ理由で却下）
- 現状のまま（選択肢3）：`state_completeness` が失われ、暫定と本判定の差を測れない

## Consequences
- 1つの出来事に対し bundle が2行（暫定・本判定）残る。件数の数え方は「現在の bundle のみ」（`docs/事前宣言.md` の1件の定義と整合）
- 作り直しの歯止め（ADR 022 の5条件）がそのまま適用される。特に「判定済みなら意味が変わるときだけ」に該当するので、PDF 到着は (c) role 変更ではなく (a) 本文の有無として扱う——`provisional_only` フラグの消滅を意味の変化とみなす
- task 013 は done（結論はこの ADR）
