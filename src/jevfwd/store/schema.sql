-- src/jevfwd/store/schema.sql — 凍結ログ DDL（版1）
-- 正本は docs/detailed/01-凍結ログ.md。変更は store/migrations/NNN_*.sql で前進のみ。
-- 時刻列（*_at, ts）は UTC 'YYYY-MM-DDTHH:MM:SS+00:00'、日付列（day, date, as_of, listed_on）は JST 暦日 'YYYY-MM-DD'。
-- PRAGMA（WAL, foreign_keys, recursive_triggers 等）は db.connect() が接続ごとに設定する。ここには書かない。

BEGIN IMMEDIATE;

CREATE TABLE schema_version (
  version    INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL CHECK (applied_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00')
);

-- ---------------------------------------------------------------
-- 凍結テーブル（追記専用。末尾のトリガーで UPDATE / DELETE を拒否）
-- ---------------------------------------------------------------

CREATE TABLE events (
  event_id      INTEGER PRIMARY KEY,
  code          TEXT NOT NULL CHECK (length(code) = 5),            -- TDnet 5文字（35600, 590A0, 13264）
  company       TEXT,
  title         TEXT NOT NULL,
  published_at  TEXT NOT NULL CHECK (published_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00'),
  received_at   TEXT NOT NULL CHECK (received_at  GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00'),
  fetch_lag_sec INTEGER,                                             -- received_at - published_at（ADR 009）
  pdf_url       TEXT,
  pdf_path      TEXT,
  pdf_sha256    TEXT UNIQUE CHECK (pdf_sha256 IS NULL OR (length(pdf_sha256) = 64 AND pdf_sha256 NOT GLOB '*[^0-9a-f]*')),
  pdf_status    TEXT NOT NULL CHECK (pdf_status IN ('ok', 'failed', 'none')),
  body_text     TEXT,
  body_chars    INTEGER,
  scan_suspect  INTEGER CHECK (scan_suspect IN (0, 1)),
  xbrl_json     TEXT,
  source        TEXT NOT NULL DEFAULT 'tdnet' CHECK (source IN ('tdnet', 'fixture'))  -- fixture: 週次再判定用の合成行（ADR 015）
);
CREATE INDEX idx_events_code_published ON events (code, published_at);
CREATE INDEX idx_events_published      ON events (published_at);

CREATE TABLE bundles (
  bundle_id               INTEGER PRIMARY KEY,
  code                    TEXT NOT NULL CHECK (length(code) = 5),
  anchor_published_at     TEXT NOT NULL CHECK (anchor_published_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00'),
  session                 TEXT NOT NULL CHECK (session IN ('after_close', 'pre_open', 'intraday')),   -- ADR 011
  primary_event_id        INTEGER NOT NULL REFERENCES events (event_id),
  event_ids_json          TEXT NOT NULL,                              -- 束ねた全 event_id の配列
  logical_docs_json       TEXT NOT NULL,                              -- [{title, event_ids}]（ADR 016）
  bundle_role             TEXT NOT NULL CHECK (bundle_role IN ('normal', 'tob_primary', 'tob_attached', 'excluded', 'fixture')),
  skip_reason             TEXT CHECK (skip_reason IS NULL OR skip_reason IN ('excluded_instrument', 'excluded_supervised', 'excluded_new_listing', 'excluded_title')),
  flags_json              TEXT NOT NULL DEFAULT '[]',                 -- low_priority:*, truncated, provisional_only, scan_suspect（ADR 019）
  state_json              TEXT,
  state_version           TEXT REFERENCES state_versions (version),
  state_chars             INTEGER,
  state_completeness_json TEXT,
  supersedes_id           INTEGER REFERENCES bundles (bundle_id),     -- 訂正時に旧 bundle を指す（ADR 014）
  created_at              TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00'),
  CHECK ((bundle_role = 'excluded') = (skip_reason IS NOT NULL))
);
CREATE INDEX idx_bundles_code_anchor ON bundles (code, anchor_published_at);
CREATE INDEX idx_bundles_supersedes  ON bundles (supersedes_id);

CREATE TABLE judgments (
  judgment_id      INTEGER PRIMARY KEY,
  bundle_id        INTEGER NOT NULL REFERENCES bundles (bundle_id),
  purpose          TEXT NOT NULL CHECK (purpose IN ('full', 'provisional', 'recheck')),   -- ADR 015
  model            TEXT NOT NULL,                                    -- 設定由来。CHECK しない
  model_version    TEXT,
  question_version TEXT NOT NULL REFERENCES question_versions (version),  -- 凍結済みの版しか参照できない（ADR 020）
  state_version    TEXT REFERENCES state_versions (version),
  request_json     TEXT NOT NULL,                                    -- 生保存
  response_json    TEXT,                                             -- 生保存
  requested_at     TEXT NOT NULL CHECK (requested_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00'),
  responded_at     TEXT CHECK (responded_at IS NULL OR responded_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00'),
  latency_ms       INTEGER,
  process_lag_sec  INTEGER,                                          -- responded_at - events.received_at（ADR 009）
  error_type       TEXT,
  input_chars      INTEGER,
  delayed          INTEGER NOT NULL DEFAULT 0 CHECK (delayed IN (0, 1))   -- responded_at - published_at > judge.delayed_threshold_sec
);
CREATE INDEX idx_judgments_bundle ON judgments (bundle_id);

CREATE TABLE answers (
  answer_id         INTEGER PRIMARY KEY,
  judgment_id       INTEGER NOT NULL REFERENCES judgments (judgment_id),
  question_id       TEXT NOT NULL,
  qtype             TEXT NOT NULL CHECK (qtype IN ('noul', 'score', 'choice')),
  value             TEXT,
  probability       REAL,
  confidence        REAL,
  distribution_json TEXT,
  UNIQUE (judgment_id, question_id)
);

CREATE TABLE heartbeat (
  heartbeat_id INTEGER PRIMARY KEY,
  ts           TEXT NOT NULL CHECK (ts GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00'),
  process      TEXT NOT NULL,
  ok           INTEGER NOT NULL CHECK (ok IN (0, 1)),
  queue_depth  INTEGER,
  note         TEXT
);
CREATE INDEX idx_heartbeat_process_ts ON heartbeat (process, ts);   -- 同一秒の複数行を許す（UNIQUE にしない）

CREATE TABLE ledger (
  ledger_id      INTEGER PRIMARY KEY,
  day            TEXT NOT NULL UNIQUE CHECK (day GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),   -- JST 暦日
  rows_added     INTEGER NOT NULL,
  prev_hash      TEXT NOT NULL CHECK (length(prev_hash) = 64),
  chain_hash     TEXT NOT NULL CHECK (length(chain_hash) = 64),
  schema_version INTEGER NOT NULL,
  detail_json    TEXT NOT NULL,                                      -- {"tables": {"events": {"from": 101, "to": 250, "hash": "..."}, ...}}（ADR 021）
  computed_at    TEXT NOT NULL CHECK (computed_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00')
);

CREATE TABLE question_versions (
  question_version_id INTEGER PRIMARY KEY,
  version   TEXT NOT NULL UNIQUE,
  json      TEXT NOT NULL,                                           -- config/questions.vN.json の本文そのまま
  sha256    TEXT NOT NULL CHECK (length(sha256) = 64),
  frozen_at TEXT NOT NULL CHECK (frozen_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00')
);

CREATE TABLE state_versions (
  state_version_id INTEGER PRIMARY KEY,
  version   TEXT NOT NULL UNIQUE,
  spec      TEXT NOT NULL,                                           -- docs/contracts/state.vN.schema.json の本文そのまま
  sha256    TEXT NOT NULL CHECK (length(sha256) = 64),
  frozen_at TEXT NOT NULL CHECK (frozen_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00')
);

CREATE TABLE my_calls (
  my_call_id INTEGER PRIMARY KEY,
  bundle_id  INTEGER NOT NULL REFERENCES bundles (bundle_id),
  decision   TEXT NOT NULL CHECK (decision IN ('buy', 'skip')),
  decided_at TEXT NOT NULL CHECK (decided_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00'),
  UNIQUE (bundle_id, decided_at)
);

-- ---------------------------------------------------------------
-- 採点・キャッシュ（トリガーなし。再計算は新行追加、UPDATE は規約で禁止。ADR 014）
-- ---------------------------------------------------------------

CREATE TABLE listed_master (
  code               TEXT NOT NULL CHECK (length(code) = 5),
  as_of              TEXT NOT NULL CHECK (as_of GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  company            TEXT,
  market             TEXT,
  sector             TEXT,
  listed_on          TEXT CHECK (listed_on IS NULL OR listed_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  shares_outstanding INTEGER,
  source_version     TEXT,
  PRIMARY KEY (code, as_of)
);

CREATE TABLE prices (
  code           TEXT NOT NULL CHECK (length(code) = 5),
  date           TEXT NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  open REAL, high REAL, low REAL, close REAL,
  volume         INTEGER,
  turnover       REAL,
  source_version TEXT NOT NULL,
  PRIMARY KEY (code, date, source_version)
);
CREATE INDEX idx_prices_date ON prices (date);

CREATE TABLE outcomes (
  bundle_id            INTEGER NOT NULL REFERENCES bundles (bundle_id),
  horizon              TEXT NOT NULL,
  scored_at            TEXT NOT NULL CHECK (scored_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00'),
  entry_date           TEXT CHECK (entry_date IS NULL OR entry_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  entry_price          REAL,
  exit_date            TEXT CHECK (exit_date IS NULL OR exit_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  exit_price           REAL,
  ret                  REAL,
  topix_ret            REAL,
  excess_ret           REAL,
  filled               INTEGER CHECK (filled IS NULL OR filled IN (0, 1)),
  cost                 REAL,
  overlap_excluded     INTEGER NOT NULL DEFAULT 0 CHECK (overlap_excluded IN (0, 1)),
  random_seed          INTEGER,
  price_source_version TEXT,
  PRIMARY KEY (bundle_id, horizon, scored_at)
);

CREATE TABLE paper_trades (
  trade_id      INTEGER PRIMARY KEY,
  bundle_id     INTEGER REFERENCES bundles (bundle_id),
  executor      TEXT,
  side          TEXT,
  qty           INTEGER,
  entry_date    TEXT, entry_price REAL,
  exit_date     TEXT, exit_price  REAL,
  exit_reason   TEXT,
  pnl           REAL,
  rules_version TEXT
);

-- ---------------------------------------------------------------
-- 追記専用トリガー（ADR 014）。9テーブル × UPDATE/DELETE = 18本。
-- db.connect() は本数が 18 でなければ StoreError にする。名前は trg_<table>_no_update / trg_<table>_no_delete。
-- ---------------------------------------------------------------

CREATE TRIGGER trg_events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'append-only: events'); END;
CREATE TRIGGER trg_events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'append-only: events'); END;
CREATE TRIGGER trg_bundles_no_update BEFORE UPDATE ON bundles BEGIN SELECT RAISE(ABORT, 'append-only: bundles'); END;
CREATE TRIGGER trg_bundles_no_delete BEFORE DELETE ON bundles BEGIN SELECT RAISE(ABORT, 'append-only: bundles'); END;
CREATE TRIGGER trg_judgments_no_update BEFORE UPDATE ON judgments BEGIN SELECT RAISE(ABORT, 'append-only: judgments'); END;
CREATE TRIGGER trg_judgments_no_delete BEFORE DELETE ON judgments BEGIN SELECT RAISE(ABORT, 'append-only: judgments'); END;
CREATE TRIGGER trg_answers_no_update BEFORE UPDATE ON answers BEGIN SELECT RAISE(ABORT, 'append-only: answers'); END;
CREATE TRIGGER trg_answers_no_delete BEFORE DELETE ON answers BEGIN SELECT RAISE(ABORT, 'append-only: answers'); END;
CREATE TRIGGER trg_heartbeat_no_update BEFORE UPDATE ON heartbeat BEGIN SELECT RAISE(ABORT, 'append-only: heartbeat'); END;
CREATE TRIGGER trg_heartbeat_no_delete BEFORE DELETE ON heartbeat BEGIN SELECT RAISE(ABORT, 'append-only: heartbeat'); END;
CREATE TRIGGER trg_ledger_no_update BEFORE UPDATE ON ledger BEGIN SELECT RAISE(ABORT, 'append-only: ledger'); END;
CREATE TRIGGER trg_ledger_no_delete BEFORE DELETE ON ledger BEGIN SELECT RAISE(ABORT, 'append-only: ledger'); END;
CREATE TRIGGER trg_question_versions_no_update BEFORE UPDATE ON question_versions BEGIN SELECT RAISE(ABORT, 'append-only: question_versions'); END;
CREATE TRIGGER trg_question_versions_no_delete BEFORE DELETE ON question_versions BEGIN SELECT RAISE(ABORT, 'append-only: question_versions'); END;
CREATE TRIGGER trg_state_versions_no_update BEFORE UPDATE ON state_versions BEGIN SELECT RAISE(ABORT, 'append-only: state_versions'); END;
CREATE TRIGGER trg_state_versions_no_delete BEFORE DELETE ON state_versions BEGIN SELECT RAISE(ABORT, 'append-only: state_versions'); END;
CREATE TRIGGER trg_my_calls_no_update BEFORE UPDATE ON my_calls BEGIN SELECT RAISE(ABORT, 'append-only: my_calls'); END;
CREATE TRIGGER trg_my_calls_no_delete BEFORE DELETE ON my_calls BEGIN SELECT RAISE(ABORT, 'append-only: my_calls'); END;

INSERT INTO schema_version (version, applied_at) VALUES (1, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'));

COMMIT;
