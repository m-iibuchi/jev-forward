# 021: ledger のハッシュ連鎖は明示 id の範囲で日次に計算する

- Status: Accepted
- Date: 2026-09-20
- Related: CLAUDE.md ルール1、基本設計 3.5「日次で integrity_check とハッシュ連鎖」、ADR 014、`docs/detailed/01-凍結ログ.md` 4.2 ★1・★5

## Context
ADR 014 のトリガーはアプリや `sqlite3` CLI からの UPDATE / DELETE を止めるが、DB ファイルの差し替えや、トリガーを落として書き換えて戻す操作は止められない。基本設計 3.5 は「当日追加行のハッシュ連鎖を `ledger` に記録」としていたが、何を・どの順で・どう正規化してハッシュするか、前日の値とどう結合するかが未定で、実装者が決めると再計算できない台帳になる。

SQLite の rowid は `INTEGER PRIMARY KEY` を持たないテーブルでは `VACUUM` で振り直されるため、rowid 範囲で「当日追加行」を定義すると後から検証できなくなる。

## Decision
1. **対象**：凍結9テーブルを固定順 `events, bundles, judgments, answers, heartbeat, ledger, question_versions, state_versions, my_calls` で扱う。すべて明示の `<table>_id INTEGER PRIMARY KEY` を持つ（詳細設計 01 ★1）。`ledger` 自身も対象（前日の ledger 行は当日の連鎖に含まれる）
2. **範囲**：テーブルごとに `from` = 前回 ledger 行の `detail_json.tables.<t>.to`（初回は 0）、`to` = 計算時点の `MAX(<t>_id)`（行が無ければ `from`）。対象行は `from < id <= to`
3. **行の正規化**：`PRAGMA table_info(<t>)` の列順で値を JSON 配列にする。TEXT は文字列、INTEGER は整数、REAL は Python `float` の `repr`、NULL は `null`、BLOB は `"hex:" + 16進小文字`。`json.dumps(ensure_ascii=False, separators=(",", ":"))`。行は id 昇順に `\n` で連結し UTF-8 でエンコード
4. **テーブルハッシュ**：`table_hash = sha256(連結バイト列)`。行が無ければ `sha256(b"")`
5. **連鎖**：`chain_hash = sha256((prev_hash + "\n" + str(schema_version) + "\n" + "\n".join(f"{t}:{from}:{to}:{table_hash}" for t in 固定順)).encode())`。`prev_hash` は前回行の `chain_hash`、初回は `"0" * 64`。`schema_version` は計算時点の値（列追加でハッシュが変わることを明示する）
6. **記録**：`ledger(day, rows_added, prev_hash, chain_hash, schema_version, detail_json, computed_at)`。`day` は計算時刻の JST 暦日、`rows_added` は全テーブルの対象行数の合計、`detail_json` は `{"tables": {"<t>": {"from": .., "to": .., "hash": ".."}}}` の正規 JSON
7. **原子性**：`to` の採取・ハッシュ計算・INSERT を同一 `BEGIN IMMEDIATE` トランザクションで行う（heartbeat 等が並行して追記しても範囲とハッシュがずれない）
8. **実行**：日次1回、`deploy/backup_to_nas.sh` が `sqlite3 .backup` の直前に `jevfwd ledger-append` を呼ぶ（M5）。検証は NAS 側のコピーで `jevfwd ledger-verify` が全行を再計算して一致を見る（M5）。`day` の UNIQUE 違反（同日2回）は `IntegrityError` にして2回目を捨てる

## Alternatives
- rowid 範囲：`VACUUM` で崩れる。却下
- DB ファイル全体のハッシュ：追記のたびに変わり、どこが変わったか分からない。却下
- 時刻列（`received_at` 等）で範囲を切る：テーブルごとに時刻列が違い、fixture 行のように過去の時刻を持つ行が漏れる。id 範囲は「追記された順」そのものなので単純
- 外部 WORM（S3 Object Lock 等）：月額と鍵管理が増える。ledger の `chain_hash` を ntfy の通知本文に含めて外部に痕跡を残す案は M5 で検討（任意）

## Consequences
- 凍結テーブルの追加・列追加（`ALTER TABLE ADD COLUMN`）は `schema_version` が上がるので連鎖の途中でハッシュ規則が変わっても再計算できる（旧行は旧版の列で計算していたことが分かる）
- テーブル再構築（詳細設計 01 4.4）は id を保つことが条件
- M1 では `ledger` テーブルと `insert_ledger_entry` のみ。計算・検証コマンドは M5（`docs/detailed/08-監視通知.md`）
