import json
import urllib.request
from permissions import render_call
import time
from permissions import REMEMBERABLE
from dotenv import load_dotenv

CONFIRM_WAIT = 120

MAX_LEN = 4000  # telegram 单条上限 4096，留一点余量
load_dotenv()


class Telegram:
    def __init__(self, token, timeout=30):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.timeout = timeout
        self.offset = 0
        self.pending = []  # 等待确认期间收到的"别的消息"，稍后处理

    def _call(self, method, **params):
        req = urllib.request.Request(
            self.base + method,
            data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout + 10) as r:
            body = json.loads(r.read())
        if not body.get("ok"):
            raise RuntimeError(f"Telegram API 错误：{body}")
        return body["result"]

    def fetch(self, timeout=None):
        """只拉新消息。返回 [(chat_id, user_id, text)]，只要私聊文本。"""
        updates = self._call(
            "getUpdates",
            offset=self.offset,
            timeout=self.timeout if timeout is None else timeout,
        )
        out = []
        for u in updates:
            self.offset = u["update_id"] + 1  # 确认已收到，下次不再返回
            m = u.get("message")
            if m and "text" in m and m["chat"]["type"] == "private":
                out.append((m["chat"]["id"], m["from"]["id"], m["text"]))
        return out

    def poll(self, timeout=None):
        """先交出积压的消息，没有积压再去拉新的。"""
        if self.pending:
            out, self.pending = self.pending, []
            return out
        return self.fetch(timeout)

    def send(self, chat_id, text):
        text = text or "（空回复）"
        for i in range(0, len(text), MAX_LEN):
            self._call("sendMessage", chat_id=chat_id, text=text[i : i + MAX_LEN])


def make_chat_ask(channel, chat_id, wait=CONFIRM_WAIT):
    def ask(name, args):
        opts = "y 允许 / n 拒绝（可附原因，如：n 先列出来给我看）"
        if name in REMEMBERABLE:
            opts += " / a 本会话一直允许"
        channel.send(
            chat_id,
            f"⚠️ Agent 想执行：{name}\n{render_call(name, args)}\n\n"
            f"回复 {opts}\n{wait} 秒内不回复视为拒绝。",
        )
        deadline = time.time() + wait
        while time.time() < deadline:
            left = max(1, int(deadline - time.time()))
            for c, u, text in channel.fetch(timeout=min(20, left)):
                ans, _, note = text.strip().partition(" ")
                if c == chat_id and ans.lower() in ("y", "n", "a"):
                    return ans.lower(), note.strip()
                channel.pending.append((c, u, text))
        return "n", "确认超时"

    return ask
