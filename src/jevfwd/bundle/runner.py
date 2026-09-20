"""1周期分の束ね（04-束ね 3.4・5章・7章）。DB に触るのはこのモジュールだけ。

`state` は import できない（00-共通規約 8章）ので、state の構築は `state_of` として
注入される（`cli.cmd_bundle` が組み立てる。task 017）。
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Callable, Sequence

from ..common.errors import JevfwdError
from ..common.jsonutil import canonical
from ..common.timeutil import parse_utc, to_utc_str
from ..settings import Calendar, Filters, Settings
from ..store import db, queries, repo
from ..store.rows import NewBundle, NewHeartbeat
from .grouper import BundlePlan, Coverage, EventView, ExistingBundle, plan_bundles

log = logging.getLogger(__name__)

PROCESS = "bundler"

# 05-state構築 3.1 の StateResult。型は import せず構造だけを使う（8章の境界）
StateOf = Callable[[BundlePlan], "object | None"]


def load_coverage(conn, now: datetime, cfg: Settings) -> Coverage:
    """`bundle.scan_lookback_sec` の範囲の bundles を読む。superseded な行も含める（4.1）。"""
    anchor_from = to_utc_str(now - timedelta(seconds=cfg.bundle.scan_lookback_sec))
    rows = queries.bundles_since(conn, anchor_from)
    judged = queries.bundles_with_full_judgment(conn, [r["bundle_id"] for r in rows])
    covered: set[int] = set()
    depth_of: dict[int, int] = {}
    bundles: list[ExistingBundle] = []
    for row in rows:                                # bundle_id 昇順なので親が先に決まる
        bundle_id = int(row["bundle_id"])
        event_ids = frozenset(int(i) for i in json.loads(row["event_ids_json"]))
        covered |= event_ids
        parent = row["supersedes_id"]
        depth_of[bundle_id] = 0 if parent is None else depth_of.get(int(parent), 0) + 1
        bundles.append(
            ExistingBundle(
                bundle_id=bundle_id,
                code=row["code"],
                anchor_published_at=row["anchor_published_at"],
                event_ids=event_ids,
                primary_event_id=int(row["primary_event_id"]),
                bundle_role=row["bundle_role"],
                skip_reason=row["skip_reason"],
                flags=tuple(json.loads(row["flags_json"])),
                supersede_depth=depth_of[bundle_id],
                has_full_judgment=bundle_id in judged,
            )
        )
    return Coverage(covered=frozenset(covered), bundles=tuple(bundles))


def run_once(
    conn,
    now: datetime,
    cfg: Settings,
    filters: Filters,
    calendar: Calendar,
    state_of: StateOf,
) -> list[int]:
    """1周期分。返り値は INSERT した bundle_id（3.4）。"""
    coverage = load_coverage(conn, now, cfg)
    pending = _pending_events(conn, now, cfg, coverage)
    events = pending + _members_of_overlapping(conn, pending, coverage, cfg)
    events.sort(key=lambda e: e.event_id)
    plans = plan_bundles(events, coverage, now, cfg, filters, calendar)

    staged: list[tuple[BundlePlan, object | None, tuple[str, ...]]] = []
    for plan in plans:                              # 切り詰めが重いのでトランザクションの外で組む
        if plan.bundle_role == "excluded":
            staged.append((plan, None, ()))
            continue
        try:
            staged.append((plan, state_of(plan), ()))
        except JevfwdError as e:
            log.warning("state 構築に失敗。state 無しで bundle を残す: %s %s", plan.event_ids, e)
            staged.append((plan, None, (f"state_error:{type(e).__name__}",)))

    inserted: list[int] = []
    covered_now = set(coverage.covered)
    with db.transaction(conn):
        fresh = load_coverage(conn, now, cfg)       # BEGIN IMMEDIATE の下で読み直す
        for plan, state, extra in staged:
            if plan.supersedes_id is None and any(i in fresh.covered for i in plan.event_ids):
                log.info("既にカバー済みのため作らない: %s", plan.event_ids)
                continue
            inserted.append(repo.insert_bundle(conn, _to_row(plan, state, extra, now, cfg)))
            covered_now.update(plan.event_ids)
    _report_backlog(conn, now, cfg, events, covered_now)
    return inserted


def _pending_events(
    conn, now: datetime, cfg: Settings, coverage: Coverage
) -> list[EventView]:
    """未カバーの最小 event_id から昇順に読む。時刻の窓では探さない（ADR 022）。"""
    since = to_utc_str(now - timedelta(seconds=cfg.bundle.scan_lookback_sec))
    low = queries.min_uncovered_event_id(conn, coverage.covered, since)
    if low is None:
        return []
    rows = queries.events_after(conn, low - 1, limit=cfg.bundle.max_per_cycle * 20)
    return [_view(r) for r in rows]


def _members_of_overlapping(
    conn, pending: Sequence[EventView], coverage: Coverage, cfg: Settings
) -> list[EventView]:
    """未カバー event の窓に重なる既存 bundle の member を読み直す（4.8・4.9 の突き合わせ用）。

    仕掛かりは未カバーの最小 event_id から追う（4.1）ので、それより前に確定した
    bundle の event はそのままでは読み込まれない。
    """
    known = {e.event_id for e in pending}
    wanted: set[int] = set()
    for bundle in coverage.bundles:
        anchor_at = parse_utc(bundle.anchor_published_at)
        overlaps = any(
            e.code == bundle.code
            and abs((parse_utc(e.published_at) - anchor_at).total_seconds())
            <= cfg.bundle.window_sec
            for e in pending
        )
        if overlaps:
            wanted |= bundle.event_ids - known
    if not wanted:
        return []
    return [_view(r) for r in queries.events_by_ids(conn, wanted)]


def _view(row) -> EventView:
    return EventView(
        event_id=int(row["event_id"]),
        code=row["code"],
        company=row["company"],
        title=row["title"],
        published_at=row["published_at"],
        received_at=row["received_at"],
        pdf_status=row["pdf_status"],
    )


def _to_row(
    plan: BundlePlan,
    state: object | None,
    extra: tuple[str, ...],
    now: datetime,
    cfg: Settings,
) -> NewBundle:
    """`NewBundle`（01-凍結ログ 3.2）。state_json は生のまま入れる（05 ★6）。"""
    state_flags = list(state.flags) if state is not None else []
    flags = list(plan.flags) + state_flags + list(extra)
    return NewBundle(
        code=plan.code,
        anchor_published_at=plan.anchor_published_at,
        session=plan.session,
        primary_event_id=plan.primary_event_id,
        event_ids_json=canonical(list(plan.event_ids)),
        logical_docs_json=canonical(
            [{"title": d.title, "event_ids": list(d.event_ids)} for d in plan.logical_docs]
        ),
        bundle_role=plan.bundle_role,
        skip_reason=plan.skip_reason,
        flags_json=canonical(list(dict.fromkeys(flags))),
        state_json=state.state_json if state is not None else None,
        state_version=cfg.judge.state_version if state is not None else None,
        state_chars=state.state_chars if state is not None else None,
        state_completeness_json=(
            canonical(state.completeness) if state is not None else None
        ),
        supersedes_id=plan.supersedes_id,
        created_at=to_utc_str(now),
    )


def _report_backlog(
    conn, now: datetime, cfg: Settings, events: Sequence[EventView], covered: set[int]
) -> None:
    """滞留は障害であって順番待ちではない（5章）。heartbeat に1行残す。"""
    pending = [e for e in events if e.event_id not in covered]
    if not pending:
        return
    limit = cfg.bundle.grace_sec + cfg.bundle.stuck_margin_sec
    stuck = [
        e for e in pending
        if (now - parse_utc(e.received_at)).total_seconds() > limit
    ]
    if not stuck:
        return
    note = f"bundler stuck: event_id={stuck[0].event_id} pending={len(pending)}"
    log.warning("%s", note)
    with db.transaction(conn):
        repo.insert_heartbeat(
            conn,
            NewHeartbeat(
                ts=to_utc_str(now),
                process=PROCESS,
                ok=0,
                queue_depth=len(pending),
                note=note,
            ),
        )
