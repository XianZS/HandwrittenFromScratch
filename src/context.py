"""
每一轮循环，我们都在往 messages 里追加内容：assistant 的回复、tool_calls、tool 的返回。
而每次调用 API，整个 messages 都要重新发一遍。
核心思路：
    层          做什么                  代价
    第一层      工具结果入库前截断      几乎为零
    第二层      清理旧的工具结果        为零，但是会丢失细节
    第三层      把早期对话压缩成摘要    多一次模型调用
"""

import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

STATE_DIR = Path(os.environ.get("NAMI_STATE_DIR", Path.home() / ".nami-agent"))
SESSION_DIR = STATE_DIR / "sessions"

MAX_TOOL_CHARS = 4000  # 单次工具调用结果最多保留的字符数

KEEP_RECENT_TOOL_RESULTS = 3  # 清理时，最多保留最近几条工具结果
KEEP_LAST_TURNS = 2  # 压缩时，原样保留最近几轮用户对话
KEEP_PREFIXES = ("[skill]",)
PLACEHOLDER = "[旧工具结果已清理，如需要请重新调用工具]"

SUMMARY_PROMPT = """
    你是对话摘要器。把下面这段Agent的历史对话压缩成摘要，要求：
    1.保留：用户的目标、已完成的步骤、关键结论、重要的文件路径和参数、尚未解决的问题。
    2.丢弃：寒暄、重复内容和工具返回的大段原文。
    3.用简洁的条目写，不要超过500字。
    只输出摘要本身。
"""


# --- 第一层：截断工具结果 ---
# 截断工具结果，大文件或者长命令输出，最好在进去messages之前就被截断，保留头和尾，因为报错信息、命令结果通常在末尾。
def truncate_tool_result(text, limit=MAX_TOOL_CHARS):
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n...[中间省略 {len(text)-limit}] 字符 ...\n{text[-half:]}"


# --- 第二层：清理旧工具的结果 ---
def clear_old_tool_results(messages, keep=KEEP_RECENT_TOOL_RESULTS):
    # 找到所有的工具调用
    tool_idx = []
    for index, message in enumerate(messages):
        if message["role"] == "tool" and not message["content"].startwith(
            KEEP_PREFIXES
        ):
            tool_idx.append(index)
    # 只保留最近keep个工具调用结果
    L = len(tool_idx)
    for x in range(L - keep):
        messages[tool_idx[x]]["content"] = PLACEHOLDER


# --- 第三层：摘要级压缩 ---
def split_for_compact(messages, keep_turns=KEEP_LAST_TURNS):
    """
    返回（要被压缩的就消息，原样保留的新消息）；没有可压缩的内容返回None。
    约定messages[0].role 是 system。
    主要有三个角色，user，tool，assistant，那么在这个里面，我们应该从user开始切分，因为其他两个有id对应。
    """
    user_idx = [i for i, message in enumerate(messages) if message["role"] == "user"]
    if len(user_idx) <= keep_turns:
        return None
    cut = user_idx[-keep_turns]
    return messages[1:cut], messages[cut:]


def render_for_summary(messages):
    """
    把带结构化 tool_calls 的对话历史，压平成人类可读的、带角色标签的纯文本，方便交给摘要模型。
    """
    lines = []
    for message in messages:
        if message["role"] == "assistant" and message.get("tool_calls"):
            calls = ", ".join(
                f"{c['function']['name']}({c['function']['arguments']})"
                for c in message["tool_calls"]
            )
            if message.get("content"):
                lines.append(f"[assistant] {message['content']}")
            lines.append(f"[assistant 调用工具] {calls}")
        else:
            lines.append(f"[{message['role']}] {message.get('content') or ""}")
    return "\n".join(lines)


def compact(client, model, messages):
    parts = split_for_compact(messages)
    if parts is None:
        return messages
    old, recent = parts
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": render_for_summary(old)},
        ],
    )
    summary = resp.choices[0].message.content
    # 拼接 = system + 压缩 + 没有压缩的内容
    return [
        messages[0],
        {"role": "user", "content": f"[以下是此前对话的摘要\n{summary}]"},
        {"role": "assistant", "content": "好的，我已经了解之前的进展，继续。"},
        *recent,
    ]


def save_session(name, messages):
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    (SESSION_DIR / f"{name}.json").write_text(
        json.dumps(messages, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_session(name):
    path = SESSION_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def test_clear_old_tool_results():
    """
     /opt/miniconda3/envs/cc/bin/python /Users/byqh/Desktop/code/py_items/HandwrittenFromScratch/src/context.py
    {"role": "system", "content": "system-prompt"},
    {'role': 'user', 'content': 'where?'}
    {'role': 'tool', 'content': '[旧工具结果已清理，如需要请重新调用工具]', 'tool_call_id': 'xxx1'}
    {'role': 'tool', 'content': '[旧工具结果已清理，如需要请重新调用工具]', 'tool_call_id': 'xxx2'}
    {'role': 'tool', 'content': 'I see see.', 'tool_call_id': 'xxx3'}
    {'role': 'tool', 'content': 'I see see.', 'tool_call_id': 'xxx4'}
    """
    msgs = [
        {"role": "system", "content": "system-prompt"},
        {"role": "user", "content": "where?"},
        {"role": "tool", "content": "I see see.", "tool_call_id": "xxx1"},
        {"role": "tool", "content": "I see see.", "tool_call_id": "xxx2"},
        {"role": "tool", "content": "I see see.", "tool_call_id": "xxx3"},
        {"role": "tool", "content": "I see see.", "tool_call_id": "xxx4"},
    ]
    clear_old_tool_results(msgs, 2)
    print("\n".join(str(child) for child in msgs))


if __name__ == "__main__":
    test_clear_old_tool_results()
