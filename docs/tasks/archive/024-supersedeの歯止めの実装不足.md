# 024: supersede の歯止め（04-束ね 4.8・4.9）に実装できない条件がある

- Status: done
- Owner: claude
- Blocks: task 020（`bundle/grouper.py` `bundle/runner.py`）
- Created: 2026-09-20
- Related: `docs/detailed/04-束ね.md` 3.1・3.4・4.8・4.9・4.11、`docs/detailed/01-凍結ログ.md` 3.4、ADR 022・024、ADR 027

## 内容
task 020 の実装中に、4.9 の5条件のうち 2 と 5 が書かれたままでは実装できないことが分かった。

1. **条件2に暫定→本判定が無い**：4.9 の「意味が変わること」は (a) 連番の欠けが埋まる / (b) `primary_event_id` が変わる / (c) `bundle_role`・`skip_reason` が変わる の3つ。4.8（ADR 024）が作れと言っている「本文つき event の到着」はどれにも当たらない（同一表題で連番が無ければ論理開示は別扱い、rank も role も同じ）。ADR 024 の Consequences は「`provisional_only` フラグの消滅を意味の変化とみなす」と書いているので、4.9 に (d) として明記する
2. **条件5に要る情報が `ExistingBundle` に無い**：「その bundle に `purpose='full'` の judgment が既にあるときは (b)(c) のときだけ」を判定するには judgments を読む必要があるが、`ExistingBundle`（3.1）にも M3 の `queries`（01-凍結ログ 3.4）にもその手段が無い
3. **4.8 の「旧 bundle の `flags` は引き継ぎ」の範囲が未定義**：そのまま全部引き継ぐと `catchup` `late_arrival` `state_error:*` のような、その周期の事実でしかないフラグまで新 bundle に移る
4. **仕掛かりの読み込み範囲**：仕掛かりは未カバーの最小 `event_id` から追う（4.1）ので、それより前に確定した bundle の member が `plan_bundles` に渡らない。旧 bundle との突き合わせ（4.8・4.9）ができない
5. （軽微）`recent_titles` の返り値が 04-束ね 3.4 では `list[str]`、01-凍結ログ 3.4 では `list[sqlite3.Row]` で食い違う
6. （軽微）滞留の閾値 `grace_sec + 600 秒`（5章）が設定に無く、コードに数値を書くことになる

## 完了条件
- 4.9 の条件2に (d) を足し、4.8 と相互参照する
- `ExistingBundle` に `has_full_judgment` を持たせ、`queries` に読み取りを足して `load_coverage` が埋める
- 引き継ぐフラグの範囲を決めて 4.8・4.11 に書く（ADR）
- `recent_titles` の署名を 01-凍結ログ 3.4（`list[sqlite3.Row]`）に揃える
- 未カバー event の窓に重なる既存 bundle の member を読み直してから `plan_bundles` に渡す
- 600 秒を `bundle.stuck_margin_sec` として設定に出す
- 上を反映した `tests/test_bundle.py` が通る

## メモ
- 2026-09-20：起票。1・2・4・5・6 は詳細設計の補筆で済む（判断が変わらない）ので 04-束ね と 01-凍結ログ を直した。3 は判断が要るので ADR 027（引き継ぐのは `event_note:` だけ）にした
- 2 の読み取りは `queries.bundles_with_full_judgment(conn, bundle_ids)` として足した。M4 までは judgments が空なので常に空集合を返す。条件5 が効くのは M4 以降
- 4 は `queries.events_by_ids` を足し、`runner._members_of_overlapping` が窓に重なる bundle の member だけを読み直す形にした（T04-25・T04-26 がこれを踏む）
- 6 は `bundle.stuck_margin_sec: 600` を `settings.yaml` に足し、`docs/contracts/settings.schema.json` を再生成した（04-束ね 5章・6章）
- 2026-09-20：1〜6 を反映して done。`ExistingBundle` には `primary_event_id` も足した（4.9-2b の突き合わせに要る）
