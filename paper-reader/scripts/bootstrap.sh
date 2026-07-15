#!/usr/bin/env bash
# 重新创建 paper-reader 的两个 venv（如 venvs/ 被误删或换机重装时用）
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> 创建 venvs/marker"
uv venv venvs/marker --python 3.10
uv pip install --python venvs/marker/bin/python marker-pdf

echo "==> 创建 venvs/mineru"
uv venv venvs/mineru --python 3.10
uv pip install --python venvs/mineru/bin/python "mineru[core]"

echo "==> 完成"
echo "  marker: $(pwd)/venvs/marker/bin/marker_single"
echo "  mineru: $(pwd)/venvs/mineru/bin/mineru"
