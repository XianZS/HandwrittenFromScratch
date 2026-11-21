import subprocess
from dotenv import load_dotenv
from openai import OpenAI
import os
import json
import sys

load_dotenv()


def read_file(path: str) -> str:
    with open(path, encoding="utf-8") as file:
        return file.read()


def write_file(path: str, content: str) -> str:
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)
    return f"已写入({path})-({len(content)})字符"


def run_shell(command: str) -> str:
    if input(f"\n[需要确认] 执行命令: {command}\n允许？(y/n)").strip().lower() != "y":
        return "用户已经拒绝执行该命令"
    try:
        print("已允许执行命令，默认执行时间为60秒")
        p = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "命令超出执行时间"
    except Exception as e:
        return f"[Error]:{e}"
    return (p.stdout + p.stderr)[-4000:] or "(无输出)"


TOOL_FUNCS = {
    "read_file": read_file,
    "write_file": write_file,
    "run_shell": run_shell,
}


def _tool(name, desc, props):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": {
                    k: {
                        "type": "string",
                        "description": v,
                    }
                    for k, v in props.items()
                },
                "required": list(props),
            },
        },
    }


TOOLS = [
    _tool("read_file", "读取文件内容", {"path": "文件路径"}),
    _tool(
        "write_file", "写入文件(覆盖)", {"path": "文件路径", "content": "完整文件内容"}
    ),
    _tool("run_shell", "执行shell命令并返回输出", {"command": "要执行的命令"}),
]

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
    now_step = 1
    while True:
        print(f"=== 当前任务:{task} ===")
        # 是否查看当前上下文
        if input("是否查看当前上下文[y/n]:\n").strip().lower() in ("y", "yes"):
            print(f"[当前上下文]:{messages}")
        else:
            pass
        model_response = client.chat.completions.create(
            model=os.getenv("MODEL_NAME"),
            messages=messages,
            tools=TOOLS,
        )
        msg = model_response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            return f"[result]: {msg}"
        for tool_call in msg.tool_calls:
            print(f"===[tool_call]: {tool_call}===")
            tool_func = TOOL_FUNCS[tool_call.function.name]
            print(f"正在调用{tool_func}函数")
            try:
                args = json.loads(tool_call.function.arguments)
                tool_response = tool_func(**args)
            except Exception as error:
                print(f"[Error]: {error}")
                return f"[Error]: {error}"
            messages.append(
                {"role": "tool", "content": tool_response, "tool_call_id": tool_call.id}
            )
        now_step += 1
        if now_step >= MAX_STEPS:
            break
    print(f"\n[达到 {MAX_STEPS}] 步骤上限，已经自动停止")


if __name__ == "__main__":
    print(run(sys.argv[1]))
