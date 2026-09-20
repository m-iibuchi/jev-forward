# 028: 生存確認は常駐プロセスがそれぞれ自分の beat を書き、heartbeat プロセスは集約と通知だけを行う

- Status: Accepted
- Date: 2026-09-20
- Related: 要件 F7-1・F7-2、基本設計 1章（プロセス表）・3.6、ADR 014・021、詳細設計 08-監視通知 3.2・4.2、task 027

## Context
基本設計 3.6 は「`heartbeat` は60秒ごとに1行。`monitor` は直近3行が欠けたら ntfy に警告」と書いた。しかし1行を書くのが `heartbeat` プロセスだけだと、分かるのは「heartbeat プロセスが生きているか」だけで、fetcher や bundler が**生きたまま止まっている**（例外を握ったループ、ロック待ち、外部 API の無応答）ことは分からない。supervisord はプロセスの死は拾うが、止まっているだけのプロセスは拾わない。

一方、`heartbeat` テーブルは追記専用（ADR 014）で、行を増やすこと自体は安い（1行 100 バイト程度、bundler の 30 秒周期で 1 日 2,880 行）。`process` 列は最初から「どのプロセスの beat か」を区別するためにある（01-凍結ログ 4.3）。

M2（fetcher）と M4（judge_worker）は人手タスク待ちで保留になっており、段階1の初期は bundler と heartbeat だけで回る。監視対象が固定だと、無いプロセスの途絶を通知し続ける。

## Decision
1. **常駐プロセスは周期ごとに自分の beat を書く**：`heartbeat(process=<自分の名前>, ok=1, queue_depth=<あれば>)` を1周期に1行。失敗した周期は `ok=0` と `note`。`--once` 実行は書かない
2. **`heartbeat` プロセスは監視役**：60秒ごとに自分の beat（`process='heartbeat'`、`note` に集約値の JSON）を書き、`monitor.watch` に列挙されたプロセスの最新 beat の古さ、`ok=0` の note、ディスク使用率、取得・判定の失敗率、時計のずれを見て通知する
3. **監視対象は設定**：`monitor.watch`（既定 `["bundler", "heartbeat"]`）。M2 で `fetcher`、M4 で `judge_worker` を足す。プロセス名から周期の設定キーへの対応は `monitor/heartbeat.py` の定数表に置き、表に無い名前は `ConfigError`
4. **途絶の定義**：最新 beat の古さが `周期 × monitor.missing_beats_alert`（既定3）を超えたら途絶。復旧したら1回だけ「復旧」を通知する
5. **通知は抑制つき**：同じ鍵（`missing:bundler` `disk` 等）の通知は `monitor.notify_cooldown_sec`（既定 1800）の間は1回だけ。通知の失敗は例外にせず、自分の beat の `note` に残す
6. **外部からの死活監視は持たない**（段階1）：コンテナごと落ちた場合は通知できない。NAS のバックアップ（日次）が VPS に届かないことで翌日に分かる。外部の dead-man's-switch（healthchecks.io 等）は秘密が1つ増えるので、段階2までに要否を判断する（task 028 のメモ）

## Alternatives
- **heartbeat プロセスだけが書く**（基本設計 3.6 の文面）：止まっているだけのワーカーを検出できない。却下
- **supervisord の状態を問い合わせる**（XML-RPC）：死は分かるが停止は分からない。ソケットの設定が増える。beat の補助にはなるが主にはしない
- **各ワーカーが直接 ntfy に通知する**：通知の抑制と復旧判定がプロセスごとに散らばる。通知経路は heartbeat プロセスに一本化する
- **heartbeat 行を凍結テーブルから外して間引く**：追記専用の原則を崩す。行数は問題にならない（ADR 021 の台帳にも含める）

## Consequences
- `cli.cmd_bundle` の常駐ループは周期ごとに `ok=1` の beat を書く（03-CLI 7章 `cmd_bundle` を追補）。M2 の fetcher、M4 の judge_worker も同じ形にする（06・07 を書くときに踏襲）
- `heartbeat` テーブルの行数は 1 日あたり数千行。台帳（ledger）の対象なので、`ledger-append` は heartbeat の行も毎日ハッシュする
- `monitor.watch` にプロセスを足し忘れると監視されない。08 の受入テスト T08-10 で「列挙されていないプロセスは通知しない」ことを固定し、配備手順のチェックリストに「watch を確認」を入れる
