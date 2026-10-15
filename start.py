#!/usr/bin/env python3
"""Run the self-contained local simulator, with the redesigned HMI."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "cockpit-agent"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="经纬 · 可信座舱（仅模拟车）")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    import uvicorn
    print(f"经纬 · 可信座舱 http://{args.host}:{args.port}  /  API文档 /docs")
    uvicorn.run("interview.app:app", host=args.host, port=args.port, access_log=False)
