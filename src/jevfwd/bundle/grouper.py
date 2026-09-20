"""束ねの純関数と値オブジェクト（04-束ね 3.1・3.2・7章）。

DB には触らず、現在時刻は必ず引数（`now`）で受ける。判断に使う設定値は
`Settings` `Filters` `Calendar` から読み、この中に閾値を直書きしない。
"""

import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Mapping, Sequence

from ..common.timeutil import parse_utc, to_jst
from ..settings import Calendar, Filters, MarketCfg, Settings
from . import filters as classifier

# 旧 bundle から superseding bundle へ引き継ぐ flag の接頭辞（ADR 027）
INHERITED_FLAG_PREFIXES: tuple[str, ...] = ("event_note:",)

_SEQ_NUMBER_RE = re.compile(r"[0-9０-９]+")
_ZENKAKU_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_HHMM_RE = re.compile(r"([0-9]{2}):([0-9]{2})")


@dataclass(frozen=True, slots=True)
class EventView:
    """bundle が判断に使う events の部分集合。body_text は持たない（05 が読む）。"""

    event_id: int
    code: str                      # TDnet 5文字
    company: str | None
    title: str
    published_at: str              # UTC 文字列
    received_at: str
    pdf_status: str                # ok / failed / none


@dataclass(frozen=True, slots=True)
class LogicalDoc:
    """連番表題を1つにまとめた「論理開示」（ADR 016）。"""

    title: str                     # 連番を除いた表題（連番が無ければ表題そのもの）
    event_ids: tuple[int, ...]     # 連結順（4.3 の順序規則）
    rank: int                      # primary_rank の結果（小さいほど主開示に近い）


@dataclass(frozen=True, slots=True)
class ExistingBundle:
    """既存 bundle のうち、突き合わせに要る分だけ。"""

    bundle_id: int
    code: str
    anchor_published_at: str
    event_ids: frozenset[int]
    primary_event_id: int
    bundle_role: str
    skip_reason: str | None
    flags: tuple[str, ...]
    supersede_depth: int           # supersedes_id の連鎖長（0 = 初回）
    has_full_judgment: bool        # purpose='full' の判定が既にあるか（4.9-5）


@dataclass(frozen=True, slots=True)
class Coverage:
    """どの event が既にどの bundle に入っているか。superseded な bundle も含める（4.1）。"""

    covered: frozenset[int]
    bundles: tuple[ExistingBundle, ...]


@dataclass(frozen=True, slots=True)
class BundlePlan:
    """`store.rows.NewBundle` を作るのに足りる計画。DB には触っていない。"""

    code: str
    company: str | None            # members のうち最初に company が入っている event の値
    anchor_published_at: str
    session: str                   # after_close / pre_open / intraday
    primary_event_id: int
    event_ids: tuple[int, ...]     # 昇順
    logical_docs: tuple[LogicalDoc, ...]
    bundle_role: str               # normal / tob_primary / tob_attached / excluded
    skip_reason: str | None
    flags: tuple[str, ...]
    supersedes_id: int | None = None


# --- 連番 -----------------------------------------------------------------

def _numbers(matched: str) -> list[int]:
    return [
        int(m.group(0).translate(_ZENKAKU_DIGITS))
        for m in _SEQ_NUMBER_RE.finditer(matched)
    ]


def sequence_index(matched: str | None) -> int | None:
    """連番の分子。「（１／３）」→ 1、「【2】」→ 2、連番でなければ None。"""
    if not matched:
        return None
    numbers = _numbers(matched)
    return numbers[0] if numbers else None


def sequence_total(matched: str | None) -> int | None:
    """連番の分母。「（１／３）」→ 3、分母を持たない書式（【2】）と連番でなければ None。"""
    if not matched:
        return None
    numbers = _numbers(matched)
    return numbers[1] if len(numbers) >= 2 else None


# --- 論理開示と主開示 -------------------------------------------------------

def logical_docs_of(
    events: Sequence[EventView], filters: Filters
) -> tuple[LogicalDoc, ...]:
    """連番が一致した開示だけを1つの論理開示にまとめる（4.3）。"""
    groups: dict[tuple[str, int | None], list[EventView]] = {}
    for event in events:
        stripped, matched = filters.strip_sequence(event.title)
        # 連番が無ければ1件で1論理開示（同一表題でも別の出来事。リベルタ）
        key = (stripped, sequence_total(matched)) if matched else (event.title, event.event_id)
        groups.setdefault(key, []).append(event)
    docs: list[LogicalDoc] = []
    for (title, _), members in groups.items():
        members.sort(
            key=lambda e: (
                sequence_index(filters.strip_sequence(e.title)[1]) or 0,
                e.published_at,
                e.event_id,
            )
        )
        docs.append(
            LogicalDoc(
                title=title,
                event_ids=tuple(m.event_id for m in members),
                rank=filters.primary_rank(title),
            )
        )
    return tuple(docs)


def primary_of(docs: Sequence[LogicalDoc], events: Mapping[int, EventView]) -> int:
    """主開示の論理開示の先頭 event_id。鍵は (rank, published_at, event_id)（4.4）。"""
    def sort_key(doc: LogicalDoc) -> tuple[int, str, int]:
        head = events[doc.event_ids[0]]
        return (doc.rank, head.published_at, head.event_id)

    return min(docs, key=sort_key).event_ids[0]


def split_tob(
    docs: Sequence[LogicalDoc], filters: Filters
) -> tuple[tuple[LogicalDoc, ...], tuple[LogicalDoc, ...]]:
    """(対象者側 TOB の論理開示, 残り)。束ね例外を適用するのは前者だけ（ADR 023）。"""
    target = tuple(d for d in docs if filters.title_is_tob_target(d.title))
    rest = tuple(d for d in docs if not filters.title_is_tob_target(d.title))
    return target, rest


# --- session --------------------------------------------------------------

def _hhmm(value: str) -> time:
    m = _HHMM_RE.fullmatch(value)
    if m is None:
        raise ValueError(f"'HH:MM' ではない: {value!r}")
    return time(int(m.group(1)), int(m.group(2)))


def session_of(
    anchor_published_at: str, market: MarketCfg, calendar: Calendar
) -> str:
    """JST に直して上から評価する（4.10、ADR 011）。非営業日を先に見る。"""
    jst = to_jst(parse_utc(anchor_published_at))
    day, clock = jst.date(), jst.time()
    if not calendar.is_business_day(day):
        return "after_close"
    if clock >= calendar.close_time(day, _hhmm(market.session_close)):
        return "after_close"
    if _hhmm(market.pre_open_from) <= clock < _hhmm(market.session_open):
        return "pre_open"
    if clock >= _hhmm(market.session_open):
        return "intraday"
    return "after_close"                            # 00:00〜pre_open_from は前営業日の続き


# --- 計画 -----------------------------------------------------------------

def plan_bundles(
    events: Sequence[EventView],
    coverage: Coverage,
    now: datetime,
    cfg: Settings,
    filters: Filters,
    calendar: Calendar,
) -> list[BundlePlan]:
    """未カバーの events から、いま確定してよい bundle の計画を返す（7章）。"""
    by_id = {e.event_id: e for e in events}
    uncovered = [e for e in events if e.event_id not in coverage.covered]
    plans: list[BundlePlan] = []
    used: set[int] = set()
    for anchor in uncovered:                        # event_id 昇順
        if anchor.event_id in used:
            continue
        if (now - parse_utc(anchor.received_at)).total_seconds() < cfg.bundle.grace_sec:
            continue                                # 猶予中。次の周期へ
        anchor_at = parse_utc(anchor.published_at)
        members = [
            e for e in uncovered
            if e.code == anchor.code and e.event_id not in used
            and abs((parse_utc(e.published_at) - anchor_at).total_seconds())
            <= cfg.bundle.window_sec
        ]
        prev = _overlapping_bundle(coverage, anchor, anchor_at, cfg)
        extra_flags: tuple[str, ...] = ()
        supersedes_id: int | None = None
        if prev is not None:
            with_prev = sorted(
                members + [by_id[i] for i in prev.event_ids if i in by_id],
                key=lambda e: e.event_id,
            )
            allowed, extra_flags = _supersede_decision(
                prev, with_prev, anchor_at, now, cfg, filters
            )
            if allowed:
                members, supersedes_id = with_prev, prev.bundle_id
        used.update(e.event_id for e in members)
        for plan in _plans_for(
            anchor, members, supersedes_id, extra_flags, prev, now, cfg, filters, calendar
        ):
            plans.append(plan)
        if len(plans) >= cfg.bundle.max_per_cycle:
            break
    return plans


def _plans_for(
    anchor: EventView,
    members: Sequence[EventView],
    supersedes_id: int | None,
    extra_flags: tuple[str, ...],
    prev: ExistingBundle | None,
    now: datetime,
    cfg: Settings,
    filters: Filters,
    calendar: Calendar,
) -> list[BundlePlan]:
    """1つのアンカーから作る計画。TOB の対象者側があれば2つに割る（4.7）。"""
    evmap = {e.event_id: e for e in members}
    docs = logical_docs_of(members, filters)
    role, skip_reason, flags = classifier.classify(docs, evmap, filters)
    if role == "tob_primary":
        target, rest = split_tob(docs, filters)
        groups: list[tuple[str, str | None, tuple[LogicalDoc, ...]]] = [
            ("tob_primary", None, target)
        ]
        if rest:
            groups.append(("tob_attached", None, rest))
    else:
        groups = [(role, skip_reason, docs)]

    common = _version_flags(filters, calendar) + _catchup_flag(anchor, now, cfg)
    inherited = _inherited_flags(prev) if supersedes_id is not None else ()
    plans: list[BundlePlan] = []
    for index, (group_role, group_skip, group_docs) in enumerate(groups):
        group_ids = [i for d in group_docs for i in d.event_ids]
        group_events = {i: evmap[i] for i in group_ids}
        group_flags = (
            flags if len(groups) == 1
            else classifier.doc_flags(group_docs, group_events, filters)
        )
        plans.append(
            BundlePlan(
                code=anchor.code,
                company=next((e.company for e in members if e.company), None),
                anchor_published_at=anchor.published_at,
                session=session_of(anchor.published_at, cfg.market, calendar),
                primary_event_id=primary_of(group_docs, group_events),
                event_ids=tuple(sorted(group_ids)),
                logical_docs=group_docs,
                bundle_role=group_role,
                skip_reason=group_skip,
                # 作り直しの印は主開示側の bundle にだけ付ける
                flags=_dedupe(
                    group_flags + (extra_flags if index == 0 else ()) + common + inherited
                ),
                supersedes_id=supersedes_id if index == 0 else None,
            )
        )
    return plans


def _dedupe(flags: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(flags))


def _version_flags(filters: Filters, calendar: Calendar) -> tuple[str, ...]:
    """どの版の規則で分類したかを凍結ログだけから辿れるようにする（4.11）。"""
    return (f"filters:{filters.version}", f"calendar:{calendar.version}")


def _catchup_flag(anchor: EventView, now: datetime, cfg: Settings) -> tuple[str, ...]:
    """障害明けの一斉確定（4.2）。judgments.delayed とは別に束ね側で残す。"""
    late = (now - parse_utc(anchor.published_at)).total_seconds()
    if late > cfg.bundle.grace_sec * cfg.bundle.catchup_factor:
        return ("catchup",)
    return ()


def _inherited_flags(prev: ExistingBundle | None) -> tuple[str, ...]:
    """旧 bundle から引き継ぐ flag は人の注記だけ（ADR 027）。"""
    if prev is None:
        return ()
    return tuple(
        f for f in prev.flags if f.startswith(INHERITED_FLAG_PREFIXES)
    )


def _overlapping_bundle(
    coverage: Coverage, anchor: EventView, anchor_at: datetime, cfg: Settings
) -> ExistingBundle | None:
    """アンカーの窓に重なる既存 bundle。連鎖があれば末端（bundle_id 最大）を返す。"""
    matches = [
        b for b in coverage.bundles
        if b.code == anchor.code
        and abs((parse_utc(b.anchor_published_at) - anchor_at).total_seconds())
        <= cfg.bundle.window_sec
    ]
    if not matches:
        return None
    return max(matches, key=lambda b: b.bundle_id)


def _supersede_decision(
    prev: ExistingBundle,
    members: Sequence[EventView],
    anchor_at: datetime,
    now: datetime,
    cfg: Settings,
    filters: Filters,
) -> tuple[bool, tuple[str, ...]]:
    """4.9 の5条件。作り直してよいかと、作らない場合に付ける flag を返す。"""
    if frozenset(e.event_id for e in members) == prev.event_ids:
        return False, ()                            # 4.9-1 集合が変わらない。作らない
    if (now - anchor_at).total_seconds() > cfg.bundle.supersede_deadline_sec:
        return False, ("late_arrival",)             # 4.9-3 期限切れ
    if prev.supersede_depth + 1 > cfg.bundle.max_supersede_depth:
        return False, ("late_arrival", "supersede_capped")   # 4.9-4
    changes = _meaning_changes(prev, members, filters)
    if not changes:
        return False, ("late_arrival",)             # 4.9-2 意味が変わらない
    if prev.has_full_judgment and not (changes & {"primary", "role"}):
        return False, ("late_arrival",)             # 4.9-5 判定済みなら慎重に
    if "provisional" in changes:
        return True, ("supersedes:provisional",)    # 4.8
    return True, ()


def _meaning_changes(
    prev: ExistingBundle, members: Sequence[EventView], filters: Filters
) -> set[str]:
    """4.9-2 の (a)〜(d) のうち成立したもの。"""
    evmap = {e.event_id: e for e in members}
    docs = logical_docs_of(members, filters)
    role, skip_reason, _ = classifier.classify(docs, evmap, filters)
    changes: set[str] = set()
    if role != prev.bundle_role or skip_reason != prev.skip_reason:
        changes.add("role")                         # (c)
    if primary_of(docs, evmap) != prev.primary_event_id:
        changes.add("primary")                      # (b)
    for doc in docs:
        head = evmap[doc.event_ids[0]]
        total = sequence_total(filters.strip_sequence(head.title)[1])
        known = [i for i in doc.event_ids if i in prev.event_ids]
        arrived = [i for i in doc.event_ids if i not in prev.event_ids]
        if total is not None and len(doc.event_ids) == total and arrived and known:
            changes.add("sequence_complete")        # (a) 連番の欠けが埋まった
    # (d) 表題のみで登録した開示に本文つきの行が届いた（4.8）。連番を除いた表題で見る
    by_title: dict[str, list[EventView]] = {}
    for event in members:
        by_title.setdefault(filters.strip_sequence(event.title)[0], []).append(event)
    for group in by_title.values():
        known = [e for e in group if e.event_id in prev.event_ids]
        arrived = [e for e in group if e.event_id not in prev.event_ids]
        if (
            known and arrived
            and all(e.pdf_status != "ok" for e in known)
            and any(e.pdf_status == "ok" for e in arrived)
        ):
            changes.add("provisional")
    return changes
