from __future__ import annotations
import os
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from textwrap import indent

WORKSPACE = Path(os.environ.get("NAMI_WORKSPACE", os.getcwd())).resolve()
SKILLS_DIR = WORKSPACE / "skills"


class Risk(Enum):
    SAFE = "safe"  # 只读：直接放行
    CONFIRM = "confirm"  # 有副作用：询问用户
    DENY = "deny"


@dataclass
class Decision:
    allowed: bool
    reason: str = ""


TOOL_RISK = {
    "list_dir": Risk.SAFE,
    "read_file": Risk.SAFE,
    "write_file": Risk.CONFIRM,
    "run_shell": Risk.CONFIRM,
    "fetch_url": Risk.CONFIRM,
    "load_skill": Risk.SAFE,
}
REMEMBERABLE = {"write_file"}

SHELL_DENY_PATTERNS = [
    r"\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+(/|~|\*)",
    r"\bsudo\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r":\(\)\s*\{",
    r"(curl|wget)\b.*\|\s*(sh|bash)\b",
    r">\s*/dev/sd",
]
print(SHELL_DENY_PATTERNS)


def resolve_in_workspace(path_str: str) -> Path | None:
    """
    先得到当前指向的完整绝对路径，然后再判断该绝对路径是否在工作区之内。
    """
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = WORKSPACE / p
    p = p.resolve()
    return p if p.is_relative_to(WORKSPACE) else None


def render_call(name: str, args: dict, max_chars: int = 400) -> str:
    """
    确认界面：展示将要执行的真实内容，而不是模型的自述。
    """
    if name == "run_shell":
        # [命令行执行工具]
        # 如果是执行命令工具，那么就需要特殊判断一下，然后再输入执行命令的参数。
        return f"   $ {args.get('command', '')}"
    if name == "write_file":
        # [文件写入工具]
        content = args.get("content", "")
        preview = (
            content
            if len(content) <= max_chars
            else content[:max_chars] + f"已截断，共{len(content)}个字符"
        )
        return f"   路径: {args.get('path')}\n" + indent(preview, "    ")
    return f"   {args}"


class PermissionManager:
    def __init__(self, ask=None):
        self.always_allowed: set[str] = set()
        self.ask = ask or self._ask_terminal

    def check(self, name: str, args: dict) -> Decision:
        """
        权限判断规则：
            硬规则 -> 风险等级 -> 人工判断
        越往前，越是人同意也不能执行，越往后，越依赖人工判断。
        """
        # [step 1]先判断是否是“极度危险”且“不可被触碰”的底线。
        reason = self._hard_limits(name, args)
        if reason:
            return Decision(False, reason)
        # [step 2]风险分级
        risk = TOOL_RISK.get(name, Risk.CONFIRM)  # 查看当前的风险等级
        if risk is Risk.DENY:  # 工具被禁用的情况
            return Decision(False, f"工具 {name} 被策略禁用")
        if risk is Risk.SAFE or name in self.always_allowed:
            return Decision(True)  # 工具是安全的 或 被允许一直执行
        # [step 3]人工确认
        return self._confirm(name, args)

    def _hard_limits(self, name: str, args: dict) -> str | None:
        if name in (
            "read_file",
            "write_file",
            "list_dir",
        ):  # 查看当前工具是否涉及文件读写
            path = args.get("path", ".")  # 默认设置为当前目录
            p = resolve_in_workspace(path)
            if p is None:
                return f"路径 {path!r} 在工作区 {WORKSPACE} 之外，禁止访问。"
            if name == "write_file" and p.is_relative_to(SKILLS_DIR):
                return "技能目录是只读的，Agent不可以修改自己的技能"
        if name == "run_shell":
            # 执行shell的工作才查命令
            cmd = args.get("command", "")
            for pat in SHELL_DENY_PATTERNS:
                if re.search(pat, cmd):
                    return f"命令命中危险模式，已经被策略拦截: {cmd!r}"
        return None

    def _confirm(self, name: str, args: dict) -> Decision:
        answer, note = self.ask(name, args)  # y/n/a (允许/拒绝/一直允许)
        if answer == "a" and name in REMEMBERABLE:
            self.always_allowed.add(name)
            return Decision(True)
        if answer in ("y", "a"):
            return Decision(True)
        msg = "用户拒绝了这次操作。"
        if note:
            msg += f"原因: {note}"
        msg += "不要重试同一个操作，请更换一种方式，或者向用户说明你想做什么，以及这样做的原因。"
        return Decision(False, msg)

    @staticmethod
    def _ask_terminal(name: str, args: dict):
        if not sys.stdin.isatty():
            # 不是交互终端
            return "n", "当前是非交互终端，无法确认"
        print(f"\n Agent 想执行：{name}")
        print(render_call(name, args))
        options = (
            "[y]允许 / [n]拒绝" + " / [a]本次会话一直允许"
            if name in REMEMBERABLE
            else ""
        )
        while True:
            ans = input(f"{options} >").strip().lower()
            if ans in ("y", "n") or (ans == "a" and name in REMEMBERABLE):
                break
        note = input("拒绝原因(可选，回车跳过) > ").strip() if ans == "n" else ""
        return ans, note
