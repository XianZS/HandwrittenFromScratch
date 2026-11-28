from dotenv import load_dotenv
from openai import OpenAI
import os
import json
from tools import get_schemas, execute
from pathlib import Path
from permissions import PermissionManager
from context import (
    truncate_tool_result,
    clear_old_tool_results,
    compact,
    save_session,
    load_session,
)
import skills

load_dotenv()


client = OpenAI(
    base_url=os.getenv("BASE_URL"),
    api_key=os.getenv("API_KEY"),
)
BASE_SYSTEM = """
    你是一名代码工程师，在得到用户的任务之后，你需要完成用户的任务。
    可以在必要的时候调用相关工具。
    你如果已经被拒绝了权限调用，那么就直接退出当前会话就行，不要再执行额外的操作。
"""
MAX_STEPS = 20
SOFT_LIMIT = 1600
HARD_LIMIT = 2400
usage = {"prompt_tokens": 0}


class Session:
    """
    一个会话 = 一份 messages + 一个权限管理器 + 上一次的token数
    """

    def __init__(self, name, ask=None, persist=True):
        self.name = name
        self.persist = persist
        saved = load_session(name) if persist else None
        self.messages = saved or [{"role": "system", "content": ""}]
        self.messages[0] = {"role": "system", "content": build_system()}
        self.perms = PermissionManager(ask=ask)
        self.prompt_tokens = 0

    def save(self):
        if self.persist:
            save_session(self.name, self.messages)


def build_system():
    return BASE_SYSTEM + skills.project_notes() + skills.skills_section()


def handle_call(call, perms):
    """
    [流程]：
        解析参数 -> 权限检查 -> 执行。
    [位置]：
        Agent主循环 -> 权限校验
                        |
                        --- 通过 -> 执行工具 -> 返回给模型
                        --- 拒绝 -> 返回给模型
    [返回参数]：
        永远返回字符串
    """
    name = call.function.name
    try:
        args = json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError:
        return "Error: 参数不合法，无法解析JSON。"
    decision = perms.check(name, args)
    if not decision.allowed:
        return f"[权限拒绝] {decision.reason}"
    return execute(name, args)


def run(
    session: Session,
    user_input: str,
    client,
    log=print,
) -> str:
    messages = session.messages
    messages.append({"role": "user", "content": user_input})
    for _ in range(MAX_STEPS):
        # 用上一轮调用的真实token数，决定这一轮要不要处理
        if usage["prompt_tokens"] > HARD_LIMIT:
            messages[:] = compact(client, os.getenv("MODEL_NAME"), messages)
        elif usage["prompt_tokens"] > SOFT_LIMIT:
            clear_old_tool_results(messages)

        model_response = client.chat.completions.create(
            model=os.getenv("MODEL_NAME"),
            messages=messages,
            tools=get_schemas(),
        )
        session.prompt_tokens = (
            model_response.usage.prompt_tokens if model_response.usage else 0
        )
        msg = model_response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            return f"[result]: {msg.content}"
        for tool_call in msg.tool_calls:
            log(f"🗜️ {tool_call.function.name}({tool_call.function.arguments[:80]})")
            tool_response = handle_call(tool_call, session.perms)
            messages.append(
                {
                    "role": "tool",
                    "content": truncate_tool_result(tool_response),
                    "tool_call_id": tool_call.id,
                }
            )
    log(f"\n[达到 {MAX_STEPS}] 步骤上限，已经自动停止")
    return f"\n[达到 {MAX_STEPS}] 步骤上限，已经自动停止"


def make_client():
    from openai import OpenAI

    return OpenAI(
        api_key=os.getenv("API_KEY"),
        base_url=os.getenv("BASE_URL"),
    )


def main():
    client = make_client()
    session = Session("default")
    while True:
        q = input("me > ").strip()
        if q in ("exit", "quit"):
            break
        print("\n" + run(session, q, client) + "\n")
        session.save()


if __name__ == "__main__":
    main()
