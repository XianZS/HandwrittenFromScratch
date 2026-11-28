import os
import sys
import time
from agent import Session, run, make_client
from context import SESSION_DIR
from permissions import REMEMBERABLE, render_call
from telegram import Telegram, make_chat_ask
from dotenv import load_dotenv

ALLOWED = {
    int(x) for x in os.environ.get("TG_ALLOWED_USERS", "").split(",") if x.strip()
}
CONFIRM_WAIT = 120
load_dotenv()


def handle_message(tg, client, sessions, chat_id, user_id, text):
    if user_id not in ALLOWED:
        print(f"[忽略] 非白名单用户 {user_id}")
        return
    if text.strip() == "/reset":
        sessions.pop(chat_id, None)
        (SESSION_DIR / f"tg-{chat_id}.json").unlink(missing_ok=True)
        tg.send(chat_id, "会话已经重置")
        return
    s = sessions.get(chat_id)
    if s is None:
        s = sessions[chat_id] = Session(f"tg-{chat_id}", ask=make_chat_ask(tg, chat_id))
    backup = list(s.messages)
    try:
        reply = run(s, text, client)
    except Exception as e:
        s.messages[:] = backup  # 事务回滚，避免留下没有配对的tool_calls
        reply = f"[出错，本轮已撤销] {type(e).__name__}: {e}"
    s.save()
    tg.send(chat_id, reply)


def main():
    if not ALLOWED:
        sys.exit(
            "必须设置 TG_ALLOWED_USERS （逗号分隔的 Telegram 用户 ID），否则任何人都可以操作当前智能体"
        )
    tg = Telegram(os.environ["TG_BOT_TOKEN"])
    client = make_client()
    sessions = {}
    while True:
        try:
            batch = tg.poll()
        except Exception as e:
            print(f"[轮训查询出错]: {e}")
            time.sleep(5)
            continue
        for chat_id, user_id, text in batch:
            handle_message(tg, client, sessions, chat_id, user_id, text)


if __name__ == "__main__":
    main()
