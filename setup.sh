#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
python3 -c 'import sys; sys.exit("需要 Python 3.11 或更新版本") if sys.version_info < (3, 11) else None'
node -e 'if (Number(process.versions.node.split(".")[0]) < 22) { console.error("需要 Node.js 22 或更新版本；使用 nvm 时运行 nvm install && nvm use"); process.exit(1) }'
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -c requirements-lock.txt
(cd cockpit-agent/hmi && npm ci --no-audit --no-fund && npm run build)
printf '\n安装完成。启动：.venv/bin/python start.py\n浏览器：http://127.0.0.1:8787\n'
