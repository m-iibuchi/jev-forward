# 027: superseding bundle が旧 bundle から引き継ぐ flags は `event_note:` だけにする

- Status: Accepted
- Date: 2026-09-20
- Related: ADR 019・022・024（補足）、task 024、詳細設計 04-束ね 4.8・4.11

## Context
ADR 024（04-束ね 4.8）は「旧 bundle の `flags` は引き継ぎ、新 bundle に `supersedes:provisional` を足す」と書いた。しかし `flags_json` の語彙（04-束ね 4.11）は性質の違うものが混ざっている。

- その周期の事実：`catchup`（障害明けの一斉確定）、`late_arrival`、`supersede_capped`、`state_error:*`
- 表題・社名・コードから毎回同じ答えが出るもの：`low_priority:*`、`tob_buyer`、`sequence_mismatch`、`filters:vN`、`calendar:vN`
- state 構築の結果：`truncated`、`provisional_only`、`scan_suspect`（05-state構築 が付ける）
- 人が後から書いた注記：`event_note:*`（01-凍結ログ 4.5）

そのまま全部引き継ぐと、1番目は「新 bundle を作ったときには起きていない事実」を、2・3番目は「新しい入力で計算し直した答え」を上書きしかねない値で二重に持つことになる。追記専用なので、間違って入れた flag は後から消せない。

## Decision
- superseding bundle の `flags_json` は**その周期の入力から作り直す**。旧 bundle から引き継ぐのは `event_note:` で始まるものだけ
- 引き継いだ flag は新しく計算した flag の**後ろ**に、重複を除いて並べる
- `supersedes:provisional`（4.8）と `supersede_capped`（4.9-4）は、その周期の判断として新 bundle に付ける。引き継ぎではない
- 旧 bundle の flags は旧 bundle の行に残っているので、失われる情報は無い（追跡は `supersedes_id` の連鎖で行う）

## Alternatives
- **全部引き継ぐ**（ADR 024 の文面どおり）：`catchup` や `state_error:*` が、そうでない周期に作った bundle に付く。`state_error:*` は「この bundle の state 列が NULL である理由」なので、state が入った新 bundle に付くと矛盾する
- **何も引き継がない**：人が付けた `event_note:*`（「TDnet の表題が誤っていた」等の注記）が新 bundle から消える。注記は分析時に `current_bundle` しか見ない読み手に届かないと意味がない
- **列を足して引き継ぎ元を持つ**：凍結テーブルの列が増える。`supersedes_id` で辿れるので不要

## Consequences
- `bundle/grouper.py` は引き継ぎ可能な接頭辞の許可リスト（`event_note:`）を持つ。語彙を増やすときは 04-束ね 4.11 の表と一緒に見直す
- `ExistingBundle`（04-束ね 3.1）が `flags` を持つ。`load_coverage` が `flags_json` を Python 側で読む
- 新しい flag を 4.11 に足すときは「その周期の事実か、人の注記か」を決めてから足す
