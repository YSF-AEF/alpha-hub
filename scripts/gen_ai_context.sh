#!/usr/bin/env bash
# 如果被 sh 误调用，自动切换到 bash 重新执行
if [ -z "${BASH_VERSION:-}" ]; then
  if command -v bash >/dev/null 2>&1; then
    exec bash "$0" "$@"
  else
    echo "错误：未找到 bash，请先安装 bash。" >&2
    exit 1
  fi
fi

set -euo pipefail

#!/usr/bin/env bash
set -euo pipefail

# 生成 AI 上下文（支持项目仓库 + Obsidian 契约仓库）
#
# 用法示例：
#   bash scripts/gen_ai_context.sh
#   bash scripts/gen_ai_context.sh -d "/Users/you/Obsidian/你的契约目录"
#   OBSIDIAN_CONTRACTS_DIR="/Users/you/Obsidian/你的契约目录" bash scripts/gen_ai_context.sh
#
# 可选环境变量：
#   MAX_DIFF_LINES=400 PREVIEW_LINES=30

OUT_FILE=".ai/ai_context.md"
CONTRACTS_DIR="${OBSIDIAN_CONTRACTS_DIR:-}"
MAX_DIFF_LINES="${MAX_DIFF_LINES:-300}"
PREVIEW_LINES="${PREVIEW_LINES:-25}"

usage() {
  cat <<'EOF'
用法:
  gen_ai_context.sh [-o 输出文件] [-d 契约目录]

参数:
  -o, --out             输出文件路径（默认 .ai/ai_context.md）
  -d, --contracts-dir   Obsidian 契约目录
  -h, --help            显示帮助
EOF
}

need_arg() {
  local flag="$1"
  local val="${2:-}"
  if [[ -z "$val" ]]; then
    echo "错误：$flag 缺少参数值" >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -o|--out)
      need_arg "$1" "${2:-}"
      OUT_FILE="$2"
      shift 2
      ;;
    -d|--contracts-dir)
      need_arg "$1" "${2:-}"
      CONTRACTS_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      usage
      exit 1
      ;;
  esac
done

# 必须在项目 Git 仓库中运行
if ! GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  echo "错误：当前目录不是 Git 仓库，请进入项目目录后再运行。"
  exit 1
fi

if [[ -n "$CONTRACTS_DIR" && ! -d "$CONTRACTS_DIR" ]]; then
  echo "错误：契约目录不存在: $CONTRACTS_DIR"
  exit 1
fi

cd "$GIT_ROOT"
mkdir -p "$(dirname "$OUT_FILE")"

hash_file() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  else
    shasum -a 256 "$file" | awk '{print $1}'
  fi
}

# 解析契约文件路径：
# 1) 先找 CONTRACTS_DIR/文件名
# 2) 再在 CONTRACTS_DIR 里递归找同名文件
# 3) 最后回退到项目根目录
resolve_contract_file() {
  local name="$1"

  if [[ -n "$CONTRACTS_DIR" && -f "$CONTRACTS_DIR/$name" ]]; then
    printf '%s\n' "$CONTRACTS_DIR/$name"
    return 0
  fi

  if [[ -n "$CONTRACTS_DIR" ]]; then
    local found=""
    found="$(find "$CONTRACTS_DIR" -type f -name "$name" -print -quit 2>/dev/null || true)"
    if [[ -n "$found" ]]; then
      printf '%s\n' "$found"
      return 0
    fi
  fi

  if [[ -f "$GIT_ROOT/$name" ]]; then
    printf '%s\n' "$GIT_ROOT/$name"
    return 0
  fi

  return 1
}

TIMESTAMP_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
TIMESTAMP_LOCAL="$(date +"%Y-%m-%d %H:%M:%S %z")"
REPO_NAME="$(basename "$GIT_ROOT")"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
HEAD_SHORT="$(git rev-parse --short HEAD)"
REMOTE_URL="$(git remote get-url origin 2>/dev/null || echo "N/A")"

KEY_FILES=(
  "0. 阿尔法总览.md"
  "1. 需求笔记.md"
  "2. MiraMate-v2.md"
  "3. 开发约定.md"
  "4. API 契约.md"
  "5. 事件契约.md"
  "6. 架构契约.md"
  "7. 开发日志.md"
)

{
  echo "# AI 代码上下文"
  echo
  echo "- 生成时间(UTC): ${TIMESTAMP_UTC}"
  echo "- 本地时间: ${TIMESTAMP_LOCAL}"
  echo "- 项目仓库: ${REPO_NAME}"
  echo "- 分支: ${BRANCH}"
  echo "- HEAD: ${HEAD_SHORT}"
  echo "- 远程: ${REMOTE_URL}"
  echo "- 契约目录: ${CONTRACTS_DIR:-未指定（仅在项目根目录查找）}"
  echo

  echo "## 工作区状态"
  echo '```text'
  git status --short --branch
  echo '```'
  echo

  echo "## 最近提交（最近 8 条）"
  echo '```text'
  git log --oneline --decorate -n 8
  echo '```'
  echo

  echo "## 变更文件（去重）"
  echo '```text'
  {
    git diff --name-only
    git diff --cached --name-only
    git ls-files --others --exclude-standard
  } | awk 'NF' | sort -u
  echo '```'
  echo
} > "$OUT_FILE"

if git diff --quiet; then
  {
    echo "## 未暂存 diff"
    echo '```diff'
    echo "(无未暂存改动)"
    echo '```'
    echo
  } >> "$OUT_FILE"
else
  {
    echo "## 未暂存 diff（最多 ${MAX_DIFF_LINES} 行）"
    echo '```diff'
    git diff --no-color | sed -n "1,${MAX_DIFF_LINES}p"
    echo '```'
    echo
  } >> "$OUT_FILE"
fi

if git diff --cached --quiet; then
  {
    echo "## 已暂存 diff"
    echo '```diff'
    echo "(无已暂存改动)"
    echo '```'
    echo
  } >> "$OUT_FILE"
else
  {
    echo "## 已暂存 diff（最多 ${MAX_DIFF_LINES} 行）"
    echo '```diff'
    git diff --cached --no-color | sed -n "1,${MAX_DIFF_LINES}p"
    echo '```'
    echo
  } >> "$OUT_FILE"
fi

{
  echo "## 关键文档快照"
  for name in "${KEY_FILES[@]}"; do
    echo
    echo "### ${name}"
    if path="$(resolve_contract_file "$name")"; then
      echo "- 来源: ${path}"
      echo "- sha256: $(hash_file "$path")"
      echo "- 行数: $(wc -l < "$path" | tr -d ' ')"
      echo "- 预览（前 ${PREVIEW_LINES} 行）:"
      echo '```text'
      sed -n "1,${PREVIEW_LINES}p" "$path"
      echo '```'
    else
      echo "- (未找到：已在契约目录和项目根目录中查找)"
    fi
  done

  # 如果 Obsidian 契约目录本身也是 Git 仓库，附带其状态
  if [[ -n "$CONTRACTS_DIR" ]] && git -C "$CONTRACTS_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo
    echo "## 契约仓库状态（Obsidian）"
    echo '```text'
    echo "repo: $CONTRACTS_DIR"
    git -C "$CONTRACTS_DIR" status --short --branch
    git -C "$CONTRACTS_DIR" log --oneline -n 3
    echo '```'
  fi

  echo
  echo "## 本次任务（手动补充）"
  echo "- 目标："
  echo "- 需要新建/修改的文件："
  echo "- 明确不允许修改的文件："
  echo "- 验收标准："
} >> "$OUT_FILE"

echo "已生成上下文文件：$OUT_FILE"
echo "下一步：把该文件内容 + 你的任务需求一起发给 AI。"


