#!/usr/bin/env python3
"""Fetch catalogued official manuals explicitly; require exact SHA256 matches."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "data" / "manuals"
MAX_BYTES = 80 * 1024 * 1024


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(document: dict, directory: Path, *, verify_only: bool, timeout: int) -> None:
    name = document["filename"]
    if Path(name).name != name or not name.endswith(".pdf"):
        raise ValueError("清单文件名无效")
    target = directory / name
    expected = document["sha256"]
    if target.exists():
        if digest(target) != expected:
            raise ValueError("已有文件指纹不符；保留原文件，请核对清单或通过界面导入新版 PDF")
        print(f"OK  {name}（SHA256 匹配）")
        return
    if verify_only:
        raise ValueError("文件尚未下载")
    url = document["source_url"]
    if not url.startswith("https://"):
        raise ValueError("仅接受清单中的 HTTPS 来源")
    temporary = None
    try:
        request = Request(url, headers={"User-Agent": "TrustedCockpitAgent/1.0 manual-download"})
        with urlopen(request, timeout=timeout) as response:
            with tempfile.NamedTemporaryFile(dir=directory, suffix=".part", delete=False) as output:
                temporary = Path(output.name)
                size = 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("下载超过 80 MiB 限制")
                    output.write(chunk)
        if digest(temporary) != expected:
            raise ValueError("下载内容指纹与历史清单不同；官网可能已更新文件，请通过界面导入新版 PDF")
        with temporary.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise ValueError("下载内容不是 PDF")
        temporary.replace(target)
        print(f"OK  {name}（已下载，SHA256 匹配）")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    documents = json.loads((DIRECTORY / "catalog.json").read_text(encoding="utf-8"))["documents"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=[d["filename"] for d in documents], help="只处理指定手册")
    parser.add_argument("--verify-only", action="store_true", help="仅校验已下载文件，不联网")
    parser.add_argument("--timeout", type=int, default=60, help="网络请求超时秒数")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout 必须大于 0")
    failures = 0
    for document in documents:
        if args.only and document["filename"] != args.only:
            continue
        try:
            fetch(document, DIRECTORY, verify_only=args.verify_only, timeout=args.timeout)
        except (OSError, URLError, ValueError) as exc:
            failures += 1
            print(f"FAIL  {document['filename']}：{exc}")
    if failures:
        print("未成功的手册不会导入。可稍后重试，或在车辆知识页面上传适用的 PDF。")
    else:
        print("全部校验通过。启动或重启 start.py 后自动建立本地索引。")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
