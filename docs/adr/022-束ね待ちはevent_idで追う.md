# 022: 束ね待ちの検出は event_id で追い、時刻の窓では探さない

- Status: Accepted
- Date: 2026-09-20
- Related: 基本設計3.2、詳細設計 04-束ね 4.1・4.9、ADR 014・016、要件 F1-3

## Context
基本設計3.2は「同一コードで公表時刻±5分の events を集める」としか書いておらず、「まだ束ねていない event をどう見つけるか」が決まっていなかった。素直な実装は「直近N時間の events を読む」だが、次の欠陥がある。

- `fetch.list_lookback_days: 1` により前日分の event が後から入る。`published_at` の窓が先へ進んでいると、その行は二度と束ねられない（追記専用なので黙って欠損する）
- 窓の境界で、窓の外にアンカーを持つ bundle に入っている event が「未カバー」に見え、重複 bundle を作る。`bundles` に一意制約は無い
- 窓より古い滞留は検出手段が無い

連結表（`bundle_events`）を作れば「未カバー」は SQL で一発だが、凍結テーブルが1つ増えてトリガーが18→20本になり、`db.EXPECTED_TRIGGER_COUNT` と T01-01 を書き換えることになる。派生情報のために凍結ログの形を変えるのは割に合わない。

## Decision
- `events.event_id`（`INTEGER PRIMARY KEY`、`VACUUM` で振り直されない。01-凍結ログ 4.2 ★1）の昇順＝到着順で仕掛かりを追う
- 起動時に `bundle.scan_lookback_sec`（既定3日）ぶんの `bundles.event_ids_json` を Python 側で union し、最小の未カバー `event_id` を求める。以降はプロセス内で前へ進める
- coverage には **superseded な bundle も含める**（`current_bundle` は分析用）
- INSERT は `db.transaction()`（`BEGIN IMMEDIATE`）の中で coverage を読み直してから行う。二重起動時の重複 bundle を防ぐのはこれだけ
- 作り直し（`supersedes_id`）には5つの歯止めを置く：集合が変わること／意味が変わること（論理開示の完成・主開示の変更・role の変更）／期限（既定1時間）／深さ上限（既定2）／判定済みなら意味の変更のみ
- 猶予の起点は `received_at`（`published_at` は分単位かつ取得遅れに左右される）

## Alternatives
- `bundle_events` 連結表：一意制約と `NOT EXISTS` が使えて堅いが、凍結テーブル＋トリガー2本の追加で M1 の DDL とテストを動かす。派生情報のために凍結ログを広げない
- `published_at` の窓：上記の3欠陥。却下
- events に処理済みフラグ：UPDATE になるので絶対ルール1に反する。却下

## Consequences
- `store/queries.py` に `events_after` `bundles_since` `min_uncovered_event_id` `max_event_id` を足す（01-凍結ログ 3.4）
- 3日より長い停止から復帰するときは `bundle.scan_lookback_sec` を一時的に伸ばす運用が要る
- 未カバーのまま `grace_sec + 600` 秒を超えた event は障害として `heartbeat(ok=0)` に出す。`heartbeat.queue_depth` は「未カバー event 数」を持つ
- 障害明けの一斉確定は `flags_json` の `catchup` と `bundle.max_per_cycle` で抑える
