"""bundle_role / skip_reason / flags の分類（04-束ね 4.5、7章）。

`settings.Filters`（表題・社名・コードの規則）を組み合わせるだけの層で、
設定ファイルは読まず、DB にも触らない。判定順序は 4.5 の表のとおり上から。
"""

from typing import TYPE_CHECKING, Mapping, Sequence

if TYPE_CHECKING:                                   # 実行時は import しない（循環を避ける）
    from ..settings import Filters
    from .grouper import EventView, LogicalDoc


def classify(
    docs: "Sequence[LogicalDoc]",
    events: "Mapping[int, EventView]",
    filters: "Filters",
) -> tuple[str, str | None, tuple[str, ...]]:
    """(bundle_role, skip_reason, flags) を返す。4.5 の順に評価し最初に成立したものを採る。"""
    company = next((e.company for e in events.values() if e.company), "") or ""
    code = events[min(events)].code
    if filters.has_excluded_name_prefix(company):
        return "excluded", "excluded_instrument", ()
    if filters.code_excluded(code):
        return "excluded", "excluded_instrument", ()
    if docs and all(filters.title_excluded(d.title) for d in docs):
        return "excluded", "excluded_title", ()
    # listed_master（整理・監理・上場60日未満）は M6。段階1は判定しない（4.6）
    flags = doc_flags(docs, events, filters)
    if any(filters.title_is_tob_target(d.title) for d in docs):
        return "tob_primary", None, flags          # 残りの論理開示は grouper が tob_attached にする
    if any(
        filters.title_is_tob(d.title) and not filters.title_is_tob_target(d.title)
        for d in docs
    ):
        return "normal", None, flags + ("tob_buyer",)
    return "normal", None, flags


def doc_flags(
    docs: "Sequence[LogicalDoc]",
    events: "Mapping[int, EventView]",
    filters: "Filters",
) -> tuple[str, ...]:
    """論理開示の集合だけから決まる flags（重要度低下・連番の分母不一致）。"""
    flags: list[str] = []
    for doc in docs:
        key = filters.low_priority_key(doc.title)
        if key is not None:
            flags.append(f"low_priority:{key}")
    if _sequence_mismatch(docs, events, filters):
        flags.append("sequence_mismatch")
    return tuple(dict.fromkeys(flags))


def _sequence_mismatch(
    docs: "Sequence[LogicalDoc]",
    events: "Mapping[int, EventView]",
    filters: "Filters",
) -> bool:
    """連番つきの論理開示が同じ表題で2つ以上あるか（（１／３）と（２／４）。4.3）。"""
    counts: dict[str, int] = {}
    for doc in docs:
        head = events[doc.event_ids[0]]
        if filters.strip_sequence(head.title)[1] is None:
            continue                                # 連番の無い同一表題は別の出来事（リベルタ）
        counts[doc.title] = counts.get(doc.title, 0) + 1
    return any(n > 1 for n in counts.values())
