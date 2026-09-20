"""bundle 1件から Jev に渡す state を組み立てる（05-state構築 3.1・4.1・7章）。

副作用は無く、現在時刻も取らない（時刻は anchor と context が持つ）。
**評価軸になる語を state に足さない**（CLAUDE.md ルール3）。事実だけを置く。
"""

import json
import re
from dataclasses import dataclass
from typing import Sequence

from ..common.codes import display_code
from ..common.errors import JevfwdError
from ..common.timeutil import parse_utc, to_jst
from ..settings import Settings
from .context import DisclosureContext, MarketContextProvider
from .truncate import TRUNCATE_REV, fit, measure, normalize_body

ISSUER_ROLE = "発行者"                  # ADR 002。判定対象は開示の発行者自身
BODY_SEPARATOR = "\n\n"                 # 連番の論理開示を連結する区切り（4.3）

# schema の issuer.code / published_at と同じ書式（state.v2.schema.json）
_CODE_RE = re.compile(r"[0-9A-Z]{4,5}")
_JST_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+09:00")


@dataclass(frozen=True, slots=True)
class IssuerInput:
    """発行者。`cli.cmd_bundle` が `BundlePlan` と events から組む（03-CLI 3.8）。"""

    code5: str                     # TDnet 5文字。state には display_code で4文字にして入れる
    company: str                   # 市場区分の接頭辞を剥がした社名。空は ValueError
    market: str | None             # filters.market_of_company の結果（4.2）
    event_ids: tuple[int, ...]     # forecast_context の引数


@dataclass(frozen=True, slots=True)
class DocInput:
    """1論理開示。連番は `join_bodies` で連結済みの本文を渡す。"""

    title: str
    body: str | None               # PDF 取得失敗・未着なら None（表題のみ）
    rank: int


@dataclass(frozen=True, slots=True)
class StateResult:
    """`bundle/runner.py` が `bundles` の state 列に入れる一式（task 017）。"""

    state_json: str                # Jev に送る文字列そのもの（生のまま保存する）
    state: dict                    # 検証・テスト用
    state_chars: int               # len(state_json)
    completeness: dict             # bundles.state_completeness_json
    flags: tuple[str, ...]         # truncated / provisional_only


def join_bodies(bodies: Sequence[str | None]) -> str | None:
    """連番の本文を `logical_docs_json` の順に連結する（4.3）。全件 None なら None。"""
    present = [b for b in bodies if b]
    if not present:
        return None
    return BODY_SEPARATOR.join(present)


def build_state(
    *,
    issuer: IssuerInput,
    anchor_published_at: str,
    session: str,
    docs: Sequence[DocInput],
    market_ctx: MarketContextProvider,
    disc_ctx: DisclosureContext,
    cfg: Settings,
) -> StateResult:
    """docs は rank 昇順に並べ直してから組む（先頭が主開示）。"""
    if not issuer.company.strip():
        raise ValueError("issuer.company が空（問いの主語が作れない。ADR 002）")
    if not docs:
        raise ValueError("論理開示が1件も無い")
    ordered = sorted(docs, key=lambda d: d.rank)
    market, missing = market_ctx.market_context(issuer.code5, anchor_published_at, session)
    forecast = disc_ctx.forecast_context(issuer.code5, issuer.event_ids)
    cap = cfg.state.max_secondary_bodies

    state = {
        "issuer": {
            "company": issuer.company,
            "code": display_code(issuer.code5),
            "market": issuer.market,
            "role": ISSUER_ROLE,
        },
        "published_at": to_jst(parse_utc(anchor_published_at)).isoformat(timespec="seconds"),
        "market_context": market,
        "forecast_context": forecast,
        "recent_disclosures_30d": disc_ctx.recent_titles(
            issuer.code5, anchor_published_at, cfg.state.recent_days
        ),
        "same_time_disclosures": [d.title for d in ordered[1:]],
        "primary": {
            "title": ordered[0].title,
            "body": normalize_body(ordered[0].body or ""),
        },
        "secondary": [
            {"title": d.title, "body": normalize_body(d.body) if d.body else None}
            for d in ordered[1:1 + cap]
        ],
        "other_titles": [d.title for d in ordered[1 + cap:]],
        "state_version": cfg.judge.state_version,
    }
    state, report = fit(state, cfg.judge.max_state_chars, cfg.state)
    _self_check(state, cfg)

    text = json.dumps(state, ensure_ascii=False)
    flags: tuple[str, ...] = ()
    if report["applied"]:
        flags += ("truncated",)
    if all(d.body is None for d in ordered):
        flags += ("provisional_only",)          # 表題のみの暫定判定（ADR 015・024）

    return StateResult(
        state_json=text,
        state=state,
        state_chars=len(text),
        completeness=_completeness(state, missing, market_ctx, forecast, report, cfg),
        flags=flags,
    )


def _completeness(
    state: dict,
    missing: list[str],
    market_ctx: MarketContextProvider,
    forecast: dict | None,
    report: dict,
    cfg: Settings,
) -> dict:
    """`$defs/state_completeness`（4.6）。Jev に送る state には入れない。"""
    gaps = list(missing)
    if state["issuer"]["market"] is None:
        gaps.append("issuer.market")
    if forecast is None:
        gaps.append("forecast_context")
    return {
        "missing": gaps,
        "sources": {
            "market_context": market_ctx.source,
            "issuer.market": "tdnet_prefix",          # M6 以降は listed_master（4.2）
            "recent_disclosures_30d": "db",
            "forecast_context": "xbrl" if forecast is not None else "null",
        },
        "truncate": report,
        "rules": {
            "state_version": cfg.judge.state_version,
            "truncate_rev": TRUNCATE_REV,
            "filters_version": cfg.filters_version,
            "calendar_version": cfg.calendar_version,
        },
    }


def _self_check(state: dict, cfg: Settings) -> None:
    """builder が作る不変条件だけを検査する（5章）。schema 全文の検証は受入テストと M4。"""
    code = state["issuer"]["code"]
    if _CODE_RE.fullmatch(code) is None:
        raise JevfwdError(f"issuer.code が表示用コードでない: {code!r}")
    if _JST_RE.fullmatch(state["published_at"]) is None:
        raise JevfwdError(f"published_at が JST 表記でない: {state['published_at']!r}")
    if state["state_version"] != cfg.judge.state_version:
        raise JevfwdError(f"state_version が設定と違う: {state['state_version']!r}")
    if not state["primary"]["title"]:
        raise JevfwdError("primary.title が空")
    if measure(state) > cfg.judge.max_state_chars:
        raise JevfwdError(f"予算を超えた state: {measure(state)}")
