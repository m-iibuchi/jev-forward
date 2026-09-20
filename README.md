# jev-forward

Jev判定フォワードテスト基盤。凍結ログ（追記専用のSQLite）を `src/jevfwd/` に実装中。Playground検証用のスクリプトは `scripts/` に残してある。

## セットアップ

開発・テストはすべて Docker コンテナ内で行う。ホストに要るのは Docker と Compose だけ（Python も venv も要らない）。

```bash
cp .env.example .env                                            # APIキーを書く（git管理外）
docker compose -f deploy/docker-compose.yml build dev
docker compose -f deploy/docker-compose.yml run --rm dev pytest  # テスト
docker compose -f deploy/docker-compose.yml run --rm dev jevfwd --help
```

依存は `pyproject.toml`（`requirements.txt` は `scripts/` の旧スクリプト用に残している）。

## 現状

2026-09-19 Playground検証52回を完了。2026-09-20 に要件定義書v3・基本設計書・ADR（`docs/adr/`）・M1/M3 の詳細設計（`docs/detailed/00〜05`）・state v2 の契約（`docs/contracts/`）が揃った。同日、M1 前半（`common/` と `store/`：追記専用の凍結ログ）を実装（task 018、受入テスト T00-01〜19・T01-01〜27）。次は M1 後半（設定と CLI、task 019）。実装は `docs/実装セッション指示.md` の順、作業の指示は `docs/tasks/` の番号で行う。

## 使い方（Playgroundで試す段階、検証用スクリプト）

1. TDnetからPDFを `data/raw/pdf/<公開日>/` に保存する。ファイル名は `<コード>_<短い説明>.pdf` にしておくと後で追いやすい
2. テキスト化（旧スクリプトもコンテナ内で実行する）
   ```bash
   docker compose -f deploy/docker-compose.yml run --rm dev python scripts/pdf2txt.py data/raw/pdf
   ```
   `data/text/<公開日>/<同名>.txt` と、台帳 `data/text/manifest.jsonl` ができる。変換済みは飛ばす（やり直すなら `--force`）
3. stateにまとめる（1件ならそのまま標準出力に出るのでPlaygroundのStateに貼る）
   ```bash
   docker compose -f deploy/docker-compose.yml run --rm dev \
     python scripts/make_state.py data/text/2026-09-17/35600_forecast.txt \
     --code 35600 --company "ほぼ日" --title "業績予想の修正に関するお知らせ" \
     --published 2026-09-17T17:30:00+09:00 --strip-formfeed
   ```
   会社の従来予想などを足すなら `--extra '{"prior_forecast": {...}}'`
4. Questionsには `config/questions.v1.json` の中身を貼る

## ディレクトリ

```
config/           問いの版。中身を変えたら v2 を作り、v1 は残す
scripts/
  pdf2txt.py      PDF → テキスト（一括、台帳付き）
  make_state.py   テキスト → state JSON
data/             git管理外
  raw/pdf/<日付>/ 原本。変更しない
  text/<日付>/    テキスト化した本文
  state/          Playground用のstate
  db/             凍結ログのSQLite（jevfwd.sqlite）
src/jevfwd/       本体。common / store は実装済み、以降は docs/実装セッション指示.md の順
tests/
```

## 決めごと

- 原本のPDFは変更しない。テキストは改行の整理以外いじらない
- `manifest.jsonl` は追記のみ。同じPDFを変換し直しても行は消さない
- 問いの文言を変えたら版を上げる。版をまたいだ判定は同じ件数に数えない
- 画像スキャンのPDF（台帳で `scan_suspect: true`）はOCRが要る。今は対象外
