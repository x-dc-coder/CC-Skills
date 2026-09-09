#!/usr/bin/env python3
"""
check_engine_updates.py
以 Paper-reader（Marker / MinerU）为核心的重型开源库体验级更新与风险评估工具。
纯只读、零副作用、零本地模型显存加载。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parent.parent
PAPER_READER_ROOT = SKILLS_ROOT / "paper-reader"

# 待监控的重型开源库定义与本地环境映射
WATCHED_ENGINES = {
    "marker-pdf": {
        "venv_path": PAPER_READER_ROOT / "venvs" / "marker",
        "dist_name": "marker_pdf",
        "description": "Marker PDF 高保真学术文档解析器（双引擎之一）",
        "known_breaking": {
            "2.0.0": {
                "summary": "架构推倒重构：引入 Surya OCR 2 + pdftext 直读 + 局部按需 VLM（吞吐提速约 3 倍）",
                "breaking_api": "废弃了 convert_single_cli 与旧 CLI 入口",
                "code_anchor": "paper-reader/scripts/paper_reader.py:461 硬编码了 convert_single_cli",
                "model_weights": "需下载新版 Surya 2 与 20M Layout 权重（约 2.4 GB）",
                "risk_level": "CRITICAL",
                "risk_msg": "严禁直接原地 upgrade！现有调用代码与 2.0.0 不兼容，必须编写适配器。"
            }
        }
    },
    "mineru": {
        "venv_path": PAPER_READER_ROOT / "venvs" / "mineru",
        "dist_name": "mineru",
        "description": "MinerU 综合版面分析与公式提取引擎（双引擎之一）",
        "known_breaking": {}
    }
}


def get_local_version(venv_path: Path, dist_name: str) -> str | None:
    """零子进程开销：直接通过扫描 site-packages/*.dist-info 提取版本（<1ms）"""
    if not venv_path.exists():
        return None
    sp_dirs = list(venv_path.glob("lib/python*/site-packages"))
    if not sp_dirs:
        return None
    sp = sp_dirs[0]
    # 匹配 <dist_name>-<version>.dist-info
    pattern = re.compile(rf"^{re.escape(dist_name)}-([0-9a-zA-Z\.\_\-]+)\.dist-info$")
    for item in sp.iterdir():
        if item.is_dir():
            m = pattern.match(item.name)
            if m:
                return m.group(1)
    return None


def fetch_pypi_latest(package_name: str, timeout: int = 5) -> dict | None:
    """只读查询 PyPI JSON API"""
    url = f"https://pypi.org/pypi/{package_name}/json"
    proxies = {}
    if os.environ.get("http_proxy") or os.environ.get("https_proxy"):
        # 使用当前环境变量代理
        proxies = None
    else:
        # 默认 WSL 本机代理兜底
        proxies = {
            "http": "http://127.0.0.1:7890",
            "https": "http://127.0.0.1:7890"
        }

    handler = urllib.request.ProxyHandler(proxies) if proxies else urllib.request.ProxyHandler()
    opener = urllib.request.build_opener(handler)
    req = urllib.request.Request(url, headers={"User-Agent": "skill-engine-doctor/1.0"})

    try:
        with opener.open(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                info = data.get("info", {})
                releases = data.get("releases", {})
                latest_ver = info.get("version")
                rel_files = releases.get(latest_ver, [])
                upload_time = rel_files[0].get("upload_time") if rel_files else "未知"
                return {
                    "latest_version": latest_ver,
                    "summary": info.get("summary", ""),
                    "requires_python": info.get("requires_python", ""),
                    "upload_time": upload_time[:10] if upload_time else "未知",
                    "project_url": info.get("project_url", "")
                }
    except Exception as e:
        return {"error": str(e)}
    return None


def inspect_all_engines() -> list[dict]:
    """全量检测所有监控库"""
    reports = []
    for pkg, conf in WATCHED_ENGINES.items():
        local_ver = get_local_version(conf["venv_path"], conf["dist_name"])
        pypi_info = fetch_pypi_latest(pkg)
        
        has_update = False
        breaking_info = None
        latest_ver = pypi_info.get("latest_version") if pypi_info else None

        if local_ver and latest_ver and local_ver != latest_ver:
            has_update = True
            # 检测是否触发已知的重大破坏性变更
            if latest_ver in conf.get("known_breaking", {}):
                breaking_info = conf["known_breaking"][latest_ver]
            else:
                # 检查 major 跨度
                loc_major = local_ver.split(".")[0]
                lat_major = latest_ver.split(".")[0]
                if loc_major != lat_major:
                    breaking_info = {
                        "risk_level": "WARNING",
                        "risk_msg": f"Major 主版本发生跨越 ({loc_major}.x -> {lat_major}.x)，可能存在 API 或权重变更！"
                    }

        reports.append({
            "package": pkg,
            "description": conf["description"],
            "local_version": local_ver or "未安装",
            "latest_version": latest_ver or "查询失败",
            "has_update": has_update,
            "upload_time": pypi_info.get("upload_time") if pypi_info else "-",
            "breaking": breaking_info,
            "pypi_info": pypi_info
        })
    return reports


def print_cli_report(reports: list[dict]):
    """打印精美人类可读终端报告"""
    print(f"\n⚡ Paper-Reader 开源引擎体验级更新与风险评估")
    print(f"================================================================================")
    
    for r in reports:
        pkg = r["package"]
        loc = r["local_version"]
        lat = r["latest_version"]
        up_icon = "🆙 发现新版" if r["has_update"] else "✅ 已是最新"
        
        print(f"📦 引擎库: {pkg:<12} [当前: {loc:<8}] -> [最新: {lat:<8}] ({up_icon})")
        print(f"   定位: {r['description']}")
        
        if r["has_update"]:
            print(f"   发布时间: {r['upload_time']}")
            b = r.get("breaking")
            if b:
                level = b.get("risk_level", "WARNING")
                color_tag = "🚨 【CRITICAL 阻断警示】" if level == "CRITICAL" else "⚠️ 【更新风险】"
                print(f"   {color_tag} {b.get('risk_msg')}")
                if "summary" in b:
                    print(f"   • 体验升级亮点: {b['summary']}")
                if "breaking_api" in b:
                    print(f"   • 破坏性破坏项: {b['breaking_api']}")
                if "code_anchor" in b:
                    print(f"   • 现有代码受阻点: {b['code_anchor']}")
                if "model_weights" in b:
                    print(f"   • 资产与显存影响: {b['model_weights']}")
            else:
                print(f"   • 建议: Minor/Patch 级别更新，可在沙箱中验证后平滑升级。")
        print(f"--------------------------------------------------------------------------------")

    print(f"💡 蓝绿安全升级工作流规程（建议）：")
    print(f"   1. 绝不原地 upgrade 生产环境：保持现有 venvs/marker 与 venvs/mineru 完好。")
    print(f"   2. 创建候选沙箱: uv venv venvs/marker-candidate --python 3.10")
    print(f"   3. 在沙箱安装并编写适配器: scripts/adapters/marker_v2.py 抹平新老 CLI 参数差异。")
    print(f"   4. 在 tests/benchmark_corpus/ 跑 4 篇典型论文对比时延与保真度后再决定切换。\n")


def main():
    parser = argparse.ArgumentParser(description="Paper-reader 开源库更新与体验评估工具")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON 格式")
    args = parser.parse_args()

    reports = inspect_all_engines()

    if args.json:
        print(json.dumps({
            "scanned_at": datetime.now().isoformat(),
            "engines": reports
        }, indent=2, ensure_ascii=False))
    else:
        print_cli_report(reports)


if __name__ == "__main__":
    main()
