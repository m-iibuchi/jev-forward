"""追記する1行の入力型。列名と同じフィールドを持ち、主キーは持たない（自動採番）。

M1 は凍結9テーブルのみ。採点系（prices / listed_master / outcomes / paper_trades）は M6。
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NewEvent:
    code: str                      # TDnet 5文字
    title: str
    published_at: str              # UTC 文字列
    received_at: str
    pdf_status: str                # ok / failed / none
    company: str | None = None
    fetch_lag_sec: int | None = None
    pdf_url: str | None = None
    pdf_path: str | None = None
    pdf_sha256: str | None = None
    body_text: str | None = None
    body_chars: int | None = None
    scan_suspect: int | None = None
    xbrl_json: str | None = None
    source: str = "tdnet"          # tdnet / fixture


@dataclass(frozen=True, slots=True)
class NewBundle:
    code: str
    anchor_published_at: str
    session: str                   # after_close / pre_open / intraday
    primary_event_id: int
    event_ids_json: str
    logical_docs_json: str
    bundle_role: str               # normal / tob_primary / tob_attached / excluded / fixture
    created_at: str
    skip_reason: str | None = None
    flags_json: str = "[]"
    state_json: str | None = None
    state_version: str | None = None
    state_chars: int | None = None
    state_completeness_json: str | None = None
    supersedes_id: int | None = None


@dataclass(frozen=True, slots=True)
class NewJudgment:
    bundle_id: int
    purpose: str                   # full / provisional / recheck
    model: str
    question_version: str          # 凍結済みの版のみ（外部キー）
    request_json: str              # 生保存
    requested_at: str
    model_version: str | None = None
    state_version: str | None = None
    response_json: str | None = None   # 生保存
    responded_at: str | None = None
    latency_ms: int | None = None
    process_lag_sec: int | None = None
    error_type: str | None = None
    input_chars: int | None = None
    delayed: int = 0


@dataclass(frozen=True, slots=True)
class NewAnswer:
    judgment_id: int
    question_id: str
    qtype: str                     # noul / score / choice
    value: str | None = None
    probability: float | None = None
    confidence: float | None = None
    distribution_json: str | None = None


@dataclass(frozen=True, slots=True)
class NewHeartbeat:
    ts: str
    process: str
    ok: int
    queue_depth: int | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class NewLedgerEntry:
    day: str                       # JST 暦日
    rows_added: int
    prev_hash: str
    chain_hash: str
    schema_version: int
    detail_json: str
    computed_at: str


@dataclass(frozen=True, slots=True)
class NewQuestionVersion:
    version: str
    json: str                      # 版ファイルの本文そのまま
    sha256: str
    frozen_at: str


@dataclass(frozen=True, slots=True)
class NewStateVersion:
    version: str
    spec: str                      # JSON Schema の本文そのまま
    sha256: str
    frozen_at: str


@dataclass(frozen=True, slots=True)
class NewMyCall:
    bundle_id: int
    decision: str                  # buy / skip
    decided_at: str
