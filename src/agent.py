from dotenv import load_dotenv
from openai import OpenAI
import os
import json
from tools import get_schemas, execute
from pathlib import Path

load_dotenv()


client = OpenAI(
    base_url=os.getenv("BASE_URL"),
    api_key=os.getenv("API_KEY"),
)
SYSTEM = """
    你是一名代码工程师，在得到用户的任务之后，你需要完成用户的任务。
    可以在必要的时候调用相关工具。
"""
MAX_STEPS = 20


def run(task: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": task},
    ]
    for _ in range(MAX_STEPS):
        model_response = client.chat.completions.create(
            model=os.getenv("MODEL_NAME"),
            messages=messages,
            tools=get_schemas(),
        )
        msg = model_response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            return f"[result]: {msg.content}"
        for tool_call in msg.tool_calls:
            tool_func = tool_call.function.name
            print(f"正在调用{tool_func}函数")
            try:
                args = json.loads(tool_call.function.arguments or "{}")
            except Exception as error:
                return f"[Error]: {error}"
            else:
                tool_response = execute(tool_func, args)
            messages.append(
                {"role": "tool", "content": tool_response, "tool_call_id": tool_call.id}
            )
    print(f"\n[达到 {MAX_STEPS}] 步骤上限，已经自动停止")


if __name__ == "__main__":
    while True:
        q = input("me > ").strip()
        if q in ("exit", "quit", "q", "Ctrl+C"):
            break
        result = run(q)
        print(f"\n{result}+\n")
