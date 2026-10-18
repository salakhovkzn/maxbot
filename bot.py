# -*- coding: utf-8 -*-
import os, requests, uuid, urllib3, pathlib, time
urllib3.disable_warnings()

MAX_TOKEN = os.environ["MAX_TOKEN"]
GIGA_KEY  = os.environ["GIGA_KEY"]
MAX_BASE  = "https://botapi.max.ru"
MAX_H     = {"Authorization": MAX_TOKEN}
OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL  = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

MIN_LEN = 50
GROUP_CMD = "встреча"

# Основной промт (стандартная встреча)
PROMPT_MAIN = """Ты — бизнес-аналитик DENKIRS (светотехника, divine-light.ru).
Из расшифровки сделай краткий протокол без воды.

Формат:
1. КЛИЕНТ: название, адрес/город, сегмент.
2. КОНТАКТ: ФИО, должность.
3. ЧТО ОБСУДИЛИ: 5-8 коротких пунктов с фактами, цифрами, поставщиками, реакцией клиента.
4. ДОГОВОРЕННОСТИ: пронумерованный список.
5. СЛЕДУЮЩИЕ ШАГИ: пронумерованный список задач со сроками (иначе — "уточнить").

Правила:
- Удали слова-паразиты, междометия, проверки микрофона.
- Не добавляй фактов, которых нет в тексте.
- Не упоминай системы DENKIRS, если их не называли в тексте.

Расшифровка:
"""

# Промт для дополнения (второе аудио)
PROMPT_ADD = """Ты — бизнес-аналитик DENKIRS.
Ниже — дополнительная расшифровка к уже оформленной встрече.
Выдели ТОЛЬКО новые факты, договоренности и задачи, которых не было в основном протоколе.
Оформи кратко блоком "ДОПОЛНЕНИЕ К ПРОТОКОЛУ" с подпунктами.

Дополнение:
"""

HELP = ("Отправь расшифровку встречи текстом.\n"
        "В группе начни со слова «встреча».\n"
        "Если это дополнение к уже обработанной встрече — начни текст со слова «дополнение».")

def giga_token():
    r = requests.post(OAUTH_URL,
        headers={"Authorization": "Basic " + GIGA_KEY,
                 "RqUID": str(uuid.uuid4()),
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"scope": "GIGACHAT_API_PERS"},
        timeout=20, verify=False)
    r.raise_for_status()
    return r.json()["access_token"]

def process(text, token):
    low = text.lower().lstrip()
    if low.startswith("дополнение") or low.startswith("доп."):
        content = PROMPT_ADD + text
        max_tok = 1500
    else:
        content = PROMPT_MAIN + text
        max_tok = 2500

    r = requests.post(CHAT_URL,
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"},
        json={"model": "GigaChat",
              "messages": [{"role": "user", "content": content}],
              "max_tokens": max_tok},
        timeout=180, verify=False)
    r.raise_for_status()
    j = r.json()
    usage = j.get("usage", {})
    print(f"  usage: prompt={usage.get('prompt_tokens','?')}, "
          f"completion={usage.get('completion_tokens','?')}, "
          f"total={usage.get('total_tokens','?')}")
    return j["choices"][0]["message"]["content"]

def send(chat_id, text):
    for i in range(0, len(text), 3800):
        r = requests.post(f"{MAX_BASE}/messages?chat_id={chat_id}",
            headers=MAX_H, json={"text": text[i:i+3800]}, timeout=20)
        print("send ->", r.status_code, r.text[:200])

def main():
    state = pathlib.Path("state.txt")
    marker = state.read_text().strip() if state.exists() else ""
    params = {"limit": 100, "timeout": 0}
    if marker:
        params["marker"] = marker

    r = requests.get(f"{MAX_BASE}/updates", headers=MAX_H, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    new_marker = str(data.get("marker", marker))
    pending = []

    for upd in data.get("updates", []):
        msg = upd.get("message")
        if not msg:
            continue
        body = msg.get("body", {})
        text = body.get("text", "").strip()
        if upd.get("update_type") != "message_created" or not text:
            continue
        if msg.get("sender", {}).get("is_bot"):
            continue

        chat_id = msg["recipient"]["chat_id"]
        is_group = chat_id < 0

        if is_group:
            low = text.lower()
            if not low.startswith(GROUP_CMD):
                continue
            text = text[len(GROUP_CMD):].strip()
            if not text:
                send(chat_id, HELP)
                continue

        if len(text) < MIN_LEN:
            send(chat_id, HELP)
            continue

        pending.append((chat_id, text))

    if pending:
        print(f"Новых: {len(pending)}")
        token = giga_token()
        for chat_id, text in pending:
            try:
                t0 = time.time()
                result = process(text, token)
                print(f"  обработано за {round(time.time()-t0,1)} сек")
                send(chat_id, result)
            except Exception as e:
                print("ОШИБКА:", e)
                send(chat_id, "Не получилось обработать, попробуй ещё раз.")
    else:
        print("Новых сообщений нет.")

    state.write_text(new_marker, encoding="utf-8")

main()
