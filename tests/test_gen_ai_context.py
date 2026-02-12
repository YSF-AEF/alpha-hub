#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用于验证 scripts/gen_ai_context.py 是否有效的集成测试。
- 不依赖 pytest，只用 Python 内置 unittest。
- 测试时会自动创建临时 Git 仓库，不污染你的真实项目。
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "gen_ai_context.py"
PYTHON = sys.executable


def run_cmd(cmd, cwd, env=None, check=True):
    """执行命令并返回 CompletedProcess；失败时抛出清晰错误。"""
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            "命令执行失败:\n"
            f"cmd: {' '.join(str(x) for x in cmd)}\n"
            f"cwd: {cwd}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    return proc


class TestGenAiContext(unittest.TestCase):
    """gen_ai_context.py 的端到端测试。"""

    @classmethod
    def setUpClass(cls):
        # 如果主脚本不存在，直接跳过测试，避免误报。
        if not SCRIPT_PATH.is_file():
            raise unittest.SkipTest(f"未找到脚本文件: {SCRIPT_PATH}")

    def setUp(self):
        # 每个测试用例都创建独立临时目录，确保互不影响。
        self._tmp = tempfile.TemporaryDirectory(prefix="ai-context-test-")
        self.tmp = Path(self._tmp.name)

        # 构造临时项目仓库（Git）
        self.repo = self.tmp / "repo"
        self.repo.mkdir(parents=True)

        # 构造临时 Obsidian 契约目录
        self.contracts = self.tmp / "contracts"
        self.contracts.mkdir(parents=True)

        self._git(["init"])
        self._git(["config", "user.name", "ci-bot"])
        self._git(["config", "user.email", "ci@example.com"])

        # 初始提交，避免某些 git 命令在空仓库行为不稳定
        (self.repo / "README.md").write_text("# demo\n", encoding="utf-8")
        self._git(["add", "README.md"])
        self._git(["commit", "-m", "chore: init"])

    def tearDown(self):
        self._tmp.cleanup()

    def _git(self, args, check=True):
        return run_cmd(["git", *args], cwd=self.repo, check=check)

    def _run_script(self, *args, cwd=None, env=None, check=True):
        # 默认在临时仓库内执行脚本
        actual_cwd = cwd or self.repo
        return run_cmd([PYTHON, str(SCRIPT_PATH), *args], cwd=actual_cwd, env=env, check=check)

    def test_generate_context_with_contracts_and_fallback(self):
        """验证：能读取契约目录文件，也能回退读取项目根目录同名文件。"""
        # 契约目录直达文件
        api_file = self.contracts / "4. API 契约.md"
        api_file.write_text(
            "# API 契约（测试）\n"
            "## GET /health\n"
            "- 出参：{\"ok\": true}\n",
            encoding="utf-8",
        )

        # 契约目录嵌套文件（测试递归查找）
        nested = self.contracts / "nested"
        nested.mkdir(parents=True)
        event_file = nested / "5. 事件契约.md"
        event_file.write_text(
            "# 事件契约（测试）\n"
            "## event.user.created\n"
            "- payload: {\"userId\": \"u_001\"}\n",
            encoding="utf-8",
        )

        # 项目根目录 fallback 文件
        local_rule = self.repo / "3. 开发约定.md"
        local_rule.write_text(
            "# 开发约定（项目本地 fallback）\n"
            "- 仅用于测试脚本回退逻辑\n",
            encoding="utf-8",
        )

        env = os.environ.copy()
        env["PREVIEW_LINES"] = "10"

        self._run_script("-o", ".ai/ai_context.md", "-d", str(self.contracts), env=env)

        out_file = self.repo / ".ai" / "ai_context.md"
        self.assertTrue(out_file.exists(), "应成功生成上下文文件")

        text = out_file.read_text(encoding="utf-8")
        self.assertIn("# AI 代码上下文", text)

        # 验证契约目录来源
        self.assertIn("### 4. API 契约.md", text)
        self.assertIn(f"- 来源: {api_file.resolve()}", text)

        # 验证递归查找来源
        self.assertIn("### 5. 事件契约.md", text)
        self.assertIn(f"- 来源: {event_file.resolve()}", text)

        # 验证 fallback 来源
        self.assertIn("### 3. 开发约定.md", text)
        self.assertIn(f"- 来源: {local_rule.resolve()}", text)

    def test_diff_is_clipped_when_max_lines_small(self):
        """验证：当 diff 过长时，会按 MAX_DIFF_LINES 截断。"""
        target = self.repo / "app.py"
        target.write_text(
            "\n".join(f"print({i})" for i in range(120)) + "\n",
            encoding="utf-8",
        )
        self._git(["add", "app.py"])
        self._git(["commit", "-m", "feat: add app.py"])

        # 制造大量未暂存 diff
        target.write_text(
            "\n".join(f"print('line {i}')  # changed" for i in range(120)) + "\n",
            encoding="utf-8",
        )

        env = os.environ.copy()
        env["MAX_DIFF_LINES"] = "20"
        self._run_script("-o", ".ai/ai_context.md", env=env)

        text = (self.repo / ".ai" / "ai_context.md").read_text(encoding="utf-8")
        self.assertIn("未暂存 diff（最多 20 行）", text)
        self.assertIn("...(已截断，剩余", text)

    def test_fail_outside_git_repo(self):
        """验证：在非 Git 目录执行时，脚本应失败并提示错误。"""
        not_repo = self.tmp / "not_repo"
        not_repo.mkdir(parents=True)

        proc = self._run_script("-o", "x.md", cwd=not_repo, check=False)
        self.assertNotEqual(proc.returncode, 0)
        combined = (proc.stdout or "") + (proc.stderr or "")
        self.assertIn("不是 Git 仓库", combined)

    def test_fail_when_contracts_dir_not_exists(self):
        """验证：契约目录不存在时应报错退出。"""
        missing = self.tmp / "not-exists-contracts-dir"
        proc = self._run_script("-d", str(missing), check=False)
        self.assertNotEqual(proc.returncode, 0)
        combined = (proc.stdout or "") + (proc.stderr or "")
        self.assertIn("契约目录不存在", combined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
