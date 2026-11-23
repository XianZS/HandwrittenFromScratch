import subprocess
import urllib.request
from pathlib import Path

MAX_OUTPUT = 8000  # 工具 -> 模型；可以返回的最大字符数
TOOLS = {}  # 注册表：name -> {"schema":..., "func": ...}


def tool(name, description, parameters):
    """
    装饰器；
    把一个函数注册为工具
    """

    def decorator(func):
        TOOLS[name] = {
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            },
            "func": func,
        }
        return func

    return decorator


def get_schemas():
    """
    返回给模型看的全部工具说明书
    """
    return [t["schema"] for t in TOOLS.values()]


def _params(**props):
    """
    简写：所有参数都是必填的字符串
    """
    return {
        "type": "object",
        "properties": {
            k: {
                "type": "string",
                "description": v,
            }
            for k, v in props.items()
        },
        "required": list(props),
    }


@tool(
    "list_dir", "列出某个目录下的文件和子目录", _params(path="目录路径，当前目录写 .")
)
def list_dir(path="."):
    p = Path(path)
    return (
        "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir()))
        or "(空目录)"
    )


@tool("read_file", "读取指定路径文件的内容", _params(path="文件路径"))
def read_file(path: str) -> str:
    with open(path, encoding="utf-8") as file:
        return file.read()


@tool(
    "write_file",
    "向指定路径文件之中写入内容，如果文件已经存在，则直接覆盖，如果文件不存在，则创建之中再写入",
    _params(Path="文件路径", content="要写入的完整内容"),
)
def write_file(path: str, content: str) -> str:
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)
    return f"已写入({path})-({len(content)})字符"


@tool("run_shell", "在当前目录下指定命令", _params(command="执行的命令"))
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


@tool(
    "fetch_url", "抓取一个网页或者接口的文本内容。url必须以http或者https开头", _params()
)
def fetch_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": "nami-agent"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def execute(name, args):
    """
    执行工具，永远返回字符串，永远不抛出异常
    """
    if name not in TOOLS:
        return f"Error: 不存在工具 '{name}'，可用工具：{', '.join(TOOLS)}"
    try:
        result = str(TOOLS[name]["func"](**args))
    except Exception as error:
        return f"Error: {type(error).__name__} :{error}"
    if len(result) > MAX_OUTPUT:
        result = result[:MAX_OUTPUT] + f"\n ... 已经截断"
    return result
