"""Adoption strategy — heuristic layered-commit plan for existing projects."""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Sequence

from .common import (
    infer_scope_from_path,
    is_doc_path,
    is_source_path,
    is_test_path,
)
from .git import detect_stacks, resolve_commit_rules
from .safety import (
    HIGH_RISK_PATTERNS,
    WARNING_PATTERNS,
    classify_sensitive_files,
    walk_project_files,
)


def sample_project_paths(project: Path, limit: int = 2000) -> List[str]:
    paths: List[str] = []
    for path in walk_project_files(project):
        rel = str(path.relative_to(project))
        paths.append(rel)
        if len(paths) >= limit:
            break
    return sorted(paths)


def top_level_summary(paths: Sequence[str]) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for rel in paths:
        first = PurePosixPath(rel).parts[0] if PurePosixPath(rel).parts else rel
        counts[first] += 1
    return dict(counts)


def classify_path_bucket(path: str) -> str:
    pure = PurePosixPath(path)
    name = pure.name.lower()
    first = pure.parts[0].lower() if pure.parts else ""
    if name in {
        "pom.xml", "build.gradle", "build.gradle.kts", "requirements.txt",
        "pyproject.toml", "setup.py", "go.mod", "go.sum",
        ".gitignore", "dockerfile", "makefile",
    }:
        return "bootstrap"
    if is_doc_path(path):
        return "docs"
    if is_test_path(path):
        return "tests"
    if first in {".github", "ci", "scripts", "deploy", "ops"}:
        return "ops"
    if (
        first in {"config", "configs"}
        or name.startswith("application")
        or pure.suffix.lower() in {".yml", ".yaml", ".properties", ".toml", ".ini"}
    ):
        return "config"
    if first in {"src", "cmd", "pkg", "internal", "app", "apps"} or is_source_path(path):
        return "source"
    return "assets"


def choose_primary_scope(paths: Sequence[str]) -> str:
    counter: Counter[str] = Counter(infer_scope_from_path(p) for p in paths)
    return counter.most_common(1)[0][0] if counter else "core"


def strategy_message(commit_type: str, scope: str, subject: str) -> str:
    return f"{commit_type}({scope}): {subject}"


def build_adoption_strategy(
    project: Path, config: Dict[str, Any], max_layers: int = 6
) -> Dict[str, Any]:
    project = project.resolve()
    paths = sample_project_paths(project)
    stacks = detect_stacks(project)
    commit_rules = resolve_commit_rules(project, config["git"]["commit_rules_path"])
    safety = classify_sensitive_files(project)
    bucket_map: Dict[str, List[str]] = defaultdict(list)
    for rel in paths:
        bucket_map[classify_path_bucket(rel)].append(rel)
    layers: List[Dict[str, Any]] = []

    def add_layer(
        name: str, goal: str, include_paths: List[str],
        exclude_patterns: List[str], commit_type: str, subject: str,
    ) -> None:
        if not include_paths or len(layers) >= max_layers:
            return
        sample = include_paths[:12]
        scope = choose_primary_scope(include_paths)
        layers.append({
            "name": name,
            "goal": goal,
            "include_samples": sample,
            "include_count": len(include_paths),
            "exclude_patterns": exclude_patterns,
            "confidence": "medium",
            "classification_method": "heuristic path-and-filename grouping",
            "commit_candidates": [
                strategy_message(commit_type, scope, subject),
                strategy_message(
                    "chore" if commit_type != "docs" else "docs",
                    "repo" if scope == "global" else scope,
                    "整理现有项目并准备分层提交"
                    if commit_type != "docs"
                    else "完善项目文档与提交说明",
                ),
            ],
            "manual_checks": [
                "确认本层不混入敏感配置或本地产物",
                "确认本层只覆盖一个明确主题",
                "若 scripts、ops、config 被误分层，按实际业务边界手工调整",
            ],
        })

    add_layer(
        "bootstrap", "先提交构建声明、仓库基础文件和忽略规则",
        bucket_map["bootstrap"], ["业务源码", "测试代码", "本地敏感配置"],
        "chore", "初始化项目构建与仓库基础配置",
    )
    add_layer(
        "docs", "单独提交 README、接口说明和设计文档",
        bucket_map["docs"], ["源码实现", "测试修复"],
        "docs", "补充项目文档与使用说明",
    )
    add_layer(
        "config", "单独审查可提交的非敏感配置模板",
        bucket_map["config"], list(HIGH_RISK_PATTERNS) + list(WARNING_PATTERNS),
        "chore", "整理可提交的配置模板与环境说明",
    )
    add_layer(
        "source", "按核心业务或公共基础设施逐层纳入源码",
        bucket_map["source"], ["docs/", "tests/", "*.env", "*.pem"],
        "feat", "纳入核心源码与基础能力实现",
    )
    add_layer(
        "tests", "最后补充测试与验证代码",
        bucket_map["tests"], ["业务重构", "本地测试数据"],
        "test", "补充测试用例与验证脚本",
    )
    add_layer(
        "ops", "最后处理部署、脚本和 CI 相关内容",
        bucket_map["ops"], ["业务逻辑改动"],
        "chore", "整理脚本与自动化配置",
    )
    add_layer(
        "assets", "将资源文件作为最后一层纳入，避免首提过重",
        bucket_map["assets"], ["大型二进制", "导出文件", "本地缓存"],
        "chore", "整理资源文件与辅助素材",
    )

    recommended_order = [layer["name"] for layer in layers]
    return {
        "project_path": str(project),
        "strategy_type": "heuristic",
        "manual_review_required": True,
        "detected_stacks": stacks,
        "commit_rules": commit_rules,
        "top_level_summary": top_level_summary(paths),
        "safety_candidates": safety,
        "recommend_ignore_first": sorted(
            set(safety["high_risk"] + safety["warnings"])
        )[:30],
        "recommended_layers": layers,
        "recommended_order": recommended_order,
        "heuristic_caveats": [
            "目录名、扩展名和常见工程约定只用于提供初稿，不等同于真实业务边界",
            "scripts、ops、config、resources 等目录最容易出现误分层，提交前必须人工复核",
            "若同一目录同时包含源码、配置和部署脚本，应按真实意图继续拆层",
        ],
        "notes": [
            "该模式只输出分层提交建议，不会初始化仓库、配置远程、预览、提交或推送",
            "建议先人工确认 .gitignore 和 .git/info/exclude，再按层次逐次提交",
            "若某层包含过多目录，建议继续按模块或业务域再拆分",
        ],
    }
