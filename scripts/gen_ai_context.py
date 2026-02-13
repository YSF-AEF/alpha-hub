#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 AI 代码上下文（项目 Git + Obsidian 契约目录）。
"""

import argparse
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Set, Tuple

KEY_FILES = [
    "0. 阿尔法总览.md",
    "1. 需求笔记.md",
    "2. MiraMate-v2.md",
    "3. 开发约定.md",
    "4. API 契约.md",
    "5. 事件契约.md",
    "6. 架构契约.md",
    "7. 开发日志.md",
    "8. 核心模块.md",
]


def run_cmd(cmd: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    """执行命令并返回 (返回码, stdout, stderr)。"""
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout, proc.stderr


def cmd_out(cmd: List[str], cwd: Optional[Path] = None, default: str = "") -> str:
    """命令成功时返回 stdout，失败时返回默认值。"""
    code, out, _ = run_cmd(cmd, cwd=cwd)
    return out if code == 0 else default


def is_git_repo(path: Path) -> bool:
    """判断目录是否为 Git 仓库。"""
    code, _, _ = run_cmd(["git", "rev-parse", "--is-inside-work-tree"], cwd=path)
    return code == 0


def get_git_root() -> Optional[Path]:
    """获取当前目录所在仓库根目录。"""
    code, out, _ = run_cmd(["git", "rev-parse", "--show-toplevel"])
    if code != 0:
        return None
    return Path(out.strip()).resolve()


def env_positive_int(name: str, default: int) -> int:
    """读取正整数环境变量，非法时回退默认值。"""
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
        if value <= 0:
            raise ValueError
        return value
    except ValueError:
        print(f"警告：环境变量 {name}={raw!r} 非法，使用默认值 {default}", file=sys.stderr)
        return default


def clip_lines(text: str, max_lines: int) -> str:
    """按行截断文本，避免上下文过长。"""
    lines = text.splitlines()
    if not lines:
        return ""
    if len(lines) <= max_lines:
        return "\n".join(lines)
    remain = len(lines) - max_lines
    return "\n".join(lines[:max_lines] + [f"...(已截断，剩余 {remain} 行)"])


def find_file_in_tree(root: Path, filename: str) -> Optional[Path]:
    """在目录树中按“文件名完全匹配”查找第一个文件。"""
    try:
        for dirpath, _, filenames in os.walk(root):
            if filename in filenames:
                return (Path(dirpath) / filename).resolve()
    except OSError:
        return None
    return None


def resolve_contract_file(name: str, contracts_dir: Optional[Path], git_root: Path) -> Optional[Path]:
    """
    解析契约文件路径：
    1) contracts_dir/文件名
    2) contracts_dir 递归查找同名文件
    3) git_root/文件名
    """
    if contracts_dir:
        direct = contracts_dir / name
        if direct.is_file():
            return direct.resolve()

        found = find_file_in_tree(contracts_dir, name)
        if found and found.is_file():
            return found

    fallback = git_root / name
    if fallback.is_file():
        return fallback.resolve()

    return None


def sha256_file(path: Path) -> str:
    """计算文件 sha256。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def count_file_lines(path: Path) -> int:
    """统计文件行数。"""
    count = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for _ in f:
            count += 1
    return count


def read_preview(path: Path, preview_lines: int) -> str:
    """读取文件前 N 行作为预览。"""
    lines: List[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if i >= preview_lines:
                break
            lines.append(line.rstrip("\n"))
    return "\n".join(lines)


def collect_changed_files(git_root: Path) -> str:
    """收集未暂存、已暂存、未跟踪文件并去重。"""
    files: Set[str] = set()
    cmds = [
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    for cmd in cmds:
        out = cmd_out(cmd, cwd=git_root, default="")
        for line in out.splitlines():
            line = line.strip()
            if line:
                files.add(line)
    if not files:
        return "(无)"
    return "\n".join(sorted(files))


def add_block(lines: List[str], title: str, content: str, lang: str = "text") -> None:
    """向 Markdown 追加一个代码块段落。"""
    lines.append(f"## {title}")
    lines.append(f"```{lang}")
    text = content.rstrip("\n")
    lines.append(text if text.strip() else "(空)")
    lines.append("```")
    lines.append("")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 AI 代码上下文（Markdown）")
    parser.add_argument("-o", "--out", default=".ai/ai_context.md", help="输出文件路径（默认 .ai/ai_context.md）")
    parser.add_argument(
        "-d",
        "--contracts-dir",
        default=os.getenv("OBSIDIAN_CONTRACTS_DIR", ""),
        help="Obsidian 契约目录（可用环境变量 OBSIDIAN_CONTRACTS_DIR）",
    )
    args = parser.parse_args()

    max_diff_lines = env_positive_int("MAX_DIFF_LINES", 300)
    preview_lines = env_positive_int("PREVIEW_LINES", 25)

    git_root = get_git_root()
    if not git_root:
        print("错误：当前目录不是 Git 仓库，请进入项目目录后再运行。", file=sys.stderr)
        return 1

    contracts_dir: Optional[Path] = None
    if args.contracts_dir:
        contracts_dir = Path(args.contracts_dir).expanduser()
        if not contracts_dir.is_dir():
            print(f"错误：契约目录不存在: {contracts_dir}", file=sys.stderr)
            return 1
        contracts_dir = contracts_dir.resolve()

    out_path = Path(args.out).expanduser()
    if not out_path.is_absolute():
        out_path = (git_root / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Git 基础信息
    branch = cmd_out(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=git_root, default="N/A").strip() or "N/A"
    head_short = cmd_out(["git", "rev-parse", "--short", "HEAD"], cwd=git_root, default="N/A").strip() or "N/A"
    remote_url = cmd_out(["git", "remote", "get-url", "origin"], cwd=git_root, default="N/A").strip() or "N/A"
    status_text = cmd_out(["git", "status", "--short", "--branch"], cwd=git_root, default="")
    log_text = cmd_out(["git", "log", "--oneline", "--decorate", "-n", "8"], cwd=git_root, default="")
    changed_text = collect_changed_files(git_root)

    # Diff 信息
    unstaged_raw = cmd_out(["git", "diff", "--no-color"], cwd=git_root, default="")
    staged_raw = cmd_out(["git", "diff", "--cached", "--no-color"], cwd=git_root, default="")

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    now_local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    contracts_dir_display = str(contracts_dir) if contracts_dir else "未指定（仅在项目根目录查找）"

    lines: List[str] = []
    lines.append("# AI 代码上下文")
    lines.append("")
    lines.append(f"- 生成时间(UTC): {now_utc}")
    lines.append(f"- 本地时间: {now_local}")
    lines.append(f"- 项目仓库: {git_root.name}")
    lines.append(f"- 分支: {branch}")
    lines.append(f"- HEAD: {head_short}")
    lines.append(f"- 远程: {remote_url}")
    lines.append(f"- 契约目录: {contracts_dir_display}")
    lines.append("")

    add_block(lines, "工作区状态", status_text, "text")
    add_block(lines, "最近提交（最近 8 条）", log_text, "text")
    add_block(lines, "变更文件（去重）", changed_text, "text")

    if unstaged_raw.strip():
        add_block(lines, f"未暂存 diff（最多 {max_diff_lines} 行）", clip_lines(unstaged_raw, max_diff_lines), "diff")
    else:
        add_block(lines, "未暂存 diff", "(无未暂存改动)", "diff")

    if staged_raw.strip():
        add_block(lines, f"已暂存 diff（最多 {max_diff_lines} 行）", clip_lines(staged_raw, max_diff_lines), "diff")
    else:
        add_block(lines, "已暂存 diff", "(无已暂存改动)", "diff")

    lines.append("## 关键文档快照")
    for name in KEY_FILES:
        lines.append("")
        lines.append(f"### {name}")
        path = resolve_contract_file(name, contracts_dir, git_root)
        if path:
            lines.append(f"- 来源: {path}")
            lines.append(f"- sha256: {sha256_file(path)}")
            lines.append(f"- 行数: {count_file_lines(path)}")
            lines.append(f"- 预览（前 {preview_lines} 行）:")
            lines.append("```text")
            preview = read_preview(path, preview_lines)
            lines.append(preview if preview.strip() else "(文件为空)")
            lines.append("```")
        else:
            lines.append("- (未找到：已在契约目录和项目根目录中查找)")

    # 如果契约目录本身也是 Git 仓 仓库，则附带其状态
    if contracts_dir and is_git_repo(contracts_dir):
        contract_status = cmd_out(["git", "status", "--short", "--branch"], cwd=contracts_dir, default="")
        contract_log = cmd_out(["git", "log", "--oneline", "-n", "3"], cwd=contracts_dir, default="")
        lines.append("")
        lines.append("## 契约仓库状态（Obsidian）")
        lines.append("```text")
        lines.append(f"repo: {contracts_dir}")
        lines.append(contract_status.strip() if contract_status.strip() else "(status 为空)")
        lines.append(contract_log.strip() if contract_log.strip() else "(log 为空)")
        lines.append("```")

    lines.append("")
    lines.append("## 本次任务（手动补充）")
    lines.append("- 目标：")
    lines.append("- 需要新建/修改的文件：")
    lines.append("- 明确不允许修改的文件：")
    lines.append("- 验收标准：")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"已生成上下文文件：{out_path}")
    print("下一步：把该文件内容 + 你的任务需求一起发给 AI。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
