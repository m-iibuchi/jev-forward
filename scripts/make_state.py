#!/usr/bin/env python3
"""テキスト化した開示を、Jevに渡すstate（JSON）にまとめる。

使い方:
    # 1件：Playgroundに貼る用
    python scripts/make_state.py data/text/schoo_lawsuit.txt \
        --code 264A --company "Schoo" --title "訴訟提起に関するお知らせ" \
        --published 2026-09-18T15:30:00+09:00

    # フォルダごと：data/state/ に <同名>.json を作る
    python scripts/make_state.py data/text --out data/state

    # 会社の従来予想など、追加の文脈を足す（JSON文字列）
    python scripts/make_state.py x.txt --extra '{"prior_forecast": {"営業利益": 1000}}'

出力はJSON1個。1件指定のときは標準出力にも出すので、そのままコピーできる。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MAX_CHARS_WARN = 40_000  # これを超えたら警告（入力上限は要確認。判明したら更新する）


def build_state(body: str, meta: dict, extra: dict | None) -> dict:
    state: dict = {}
    # 判断に効く順に並べる。本文は最後
    for k in ("company", "code", "title", "published_at"):
        if meta.get(k):
            state[k] = meta[k]
    if extra:
        state.update(extra)
    state["body"] = body.strip()
    return state


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", type=Path, help=".txt ファイルまたはフォルダ")
    ap.add_argument("--out", type=Path, default=Path("data/state"), help="出力先フォルダ")
    ap.add_argument("--code", help="銘柄コード")
    ap.add_argument("--company", help="会社名")
    ap.add_argument("--title", help="開示の表題")
    ap.add_argument("--published", dest="published_at", help="公表時刻（ISO 8601、例 2026-09-18T15:30:00+09:00）")
    ap.add_argument("--extra", help="stateに足す項目（JSON文字列）")
    ap.add_argument("--strip-formfeed", action="store_true", help="改ページ文字を改行に置き換える")
    args = ap.parse_args()

    extra = json.loads(args.extra) if args.extra else None
    meta = {k: getattr(args, k) for k in ("code", "company", "title", "published_at")}

    txts: list[Path] = []
    for p in args.inputs:
        if p.is_dir():
            txts.extend(sorted(p.rglob("*.txt")))
        else:
            txts.append(p)
    if not txts:
        print("テキストが見つかりません", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    single = len(txts) == 1

    for t in txts:
        body = t.read_text(encoding="utf-8")
        if args.strip_formfeed:
            body = body.replace("\f", "\n\n")
        state = build_state(body, meta, extra)
        s = json.dumps(state, ensure_ascii=False, indent=2)
        dst = args.out / (t.stem + ".json")
        dst.write_text(s, encoding="utf-8")
        n = len(state["body"])
        warn = "  [長い: 入力上限に注意]" if n > MAX_CHARS_WARN else ""
        print(f"OK  {dst}  本文 {n:,}字{warn}", file=sys.stderr)
        if single:
            print(s)  # そのままPlaygroundのStateに貼れる
    return 0


if __name__ == "__main__":
    sys.exit(main())
