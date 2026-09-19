#!/usr/bin/env python3
"""TDnet等の開示PDFを一括でテキスト化する。

使い方:
    python scripts/pdf2txt.py data/raw/pdf                 # フォルダ以下のPDFを全部
    python scripts/pdf2txt.py a.pdf b.pdf                  # 個別指定
    python scripts/pdf2txt.py data/raw/pdf --out data/text # 出力先を指定
    python scripts/pdf2txt.py data/raw/pdf --force         # 変換済みも上書き

出力:
    <out>/<PDFと同じ相対パス>.txt   本文テキスト
    <out>/manifest.jsonl            1行1PDFの台帳（ハッシュ、ページ数、文字数、変換時刻）

方針:
    - 原本のPDFは一切変更しない
    - 本文は改行の正規化以外いじらない（後で判断基準を変えたときに再変換できるよう、生に近い形で残す）
    - 1ページあたりの文字数が極端に少ないPDFは、画像スキャンの可能性があるので警告する
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import pymupdf
except ImportError:  # 旧名
    import fitz as pymupdf  # type: ignore

SCAN_SUSPECT_CHARS_PER_PAGE = 50  # これ未満なら画像スキャンの疑い


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_text(pdf_path: Path) -> tuple[str, int]:
    """PDF全ページのテキストと、ページ数を返す。ページ区切りは改ページ文字で残す。"""
    pages: list[str] = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            # sort=True で読み順（上→下、左→右）に並べ替える。2段組の短信で効く
            pages.append(page.get_text("text", sort=True))
        n = doc.page_count
    text = "\f".join(pages)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)      # 行末の空白
    text = re.sub(r"\n{3,}", "\n\n", text)       # 3連以上の空行は1つに
    return text, n


def iter_pdfs(inputs: list[Path]) -> list[Path]:
    found: list[Path] = []
    for p in inputs:
        if p.is_dir():
            found.extend(sorted(p.rglob("*.pdf")))
            found.extend(sorted(p.rglob("*.PDF")))
        elif p.suffix.lower() == ".pdf":
            found.append(p)
        else:
            print(f"skip (PDFではない): {p}", file=sys.stderr)
    # 重複除去（大文字小文字違いで二重に拾った場合など）
    seen: set[Path] = set()
    uniq: list[Path] = []
    for p in found:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            uniq.append(p)
    return uniq


def out_path_for(pdf: Path, root: Path | None, out_dir: Path) -> Path:
    """入力がフォルダ指定なら相対パスを保って出力する。個別指定ならファイル名だけ。"""
    if root is not None:
        try:
            rel = pdf.resolve().relative_to(root.resolve())
        except ValueError:
            rel = Path(pdf.name)
    else:
        rel = Path(pdf.name)
    return out_dir / rel.with_suffix(".txt")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", type=Path, help="PDFファイルまたはフォルダ")
    ap.add_argument("--out", type=Path, default=Path("data/text"), help="出力先フォルダ（既定: data/text）")
    ap.add_argument("--force", action="store_true", help="変換済みのファイルも上書きする")
    args = ap.parse_args()

    pdfs = iter_pdfs(args.inputs)
    if not pdfs:
        print("PDFが見つかりません", file=sys.stderr)
        return 1

    # フォルダを1つだけ指定した場合は、その中の構造を出力側にも写す
    root = args.inputs[0] if len(args.inputs) == 1 and args.inputs[0].is_dir() else None

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = args.out / "manifest.jsonl"

    done = skipped = failed = 0
    with manifest.open("a", encoding="utf-8") as mf:
        for pdf in pdfs:
            dst = out_path_for(pdf, root, args.out)
            if dst.exists() and not args.force:
                skipped += 1
                continue
            try:
                text, n_pages = extract_text(pdf)
            except Exception as e:  # 壊れたPDFで全体を止めない
                failed += 1
                print(f"NG  {pdf}: {e}", file=sys.stderr)
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8")

            n_chars = len(text.replace("\f", "").strip())
            suspect = n_pages > 0 and n_chars / n_pages < SCAN_SUSPECT_CHARS_PER_PAGE
            rec = {
                "pdf": str(pdf),
                "txt": str(dst),
                "sha256": sha256_of(pdf),
                "pages": n_pages,
                "chars": n_chars,
                "scan_suspect": suspect,
                "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            mf.write(json.dumps(rec, ensure_ascii=False) + "\n")
            done += 1
            flag = "  [画像スキャンの疑い: 文字がほぼ取れていない]" if suspect else ""
            print(f"OK  {pdf.name}  {n_pages}p  {n_chars:,}字{flag}")

    print(f"\n変換 {done} / スキップ {skipped} / 失敗 {failed}   台帳: {manifest}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
