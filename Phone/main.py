# -*- coding: utf-8 -*-
import asyncio
import html
import os
import re
from dataclasses import dataclass
from typing import Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError, PhoneCodeInvalidError, SessionPasswordNeededError
from telethon.helpers import add_surrogate
from telethon.tl.functions.messages import GetForumTopicsRequest, SendMessageRequest
from telethon.tl.types import InputReplyToMessage, MessageEntityCustomEmoji


API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_NAME = os.getenv("SESSION_NAME", "termux_auto_piar")
COLOR_ENABLED = os.getenv("NO_COLOR", "").strip() == ""

TG_EMOJI_RE = re.compile(
    r'<tg-emoji\b[^>]*\bemoji-id\s*=\s*(?:"(\d+)"|\'(\d+)\'|(\d+))[^>]*>(.*?)</tg-emoji>',
    re.IGNORECASE | re.DOTALL,
)


class Style:
    reset = "\033[0m"
    bold = "\033[1m"
    dim = "\033[2m"
    violet = "\033[38;2;82;39;255m"
    violet_bg = "\033[48;2;82;39;255m"
    pink = "\033[38;2;255;159;252m"
    white = "\033[38;2;245;247;255m"
    muted = "\033[38;2;174;168;220m"
    ok = "\033[38;2;155;255;212m"
    warn = "\033[38;2;255;214;128m"
    err = "\033[38;2;255;128;166m"


def c(text: str, *styles: str) -> str:
    if not COLOR_ENABLED:
        return text
    return "".join(styles) + text + Style.reset


def banner():
    line = "═" * 44
    print(c("\n" + line, Style.violet))
    print(c("  AutoPiar Phone", Style.bold, Style.violet) + c("  Termux CLI", Style.pink))
    print(c(line, Style.pink))


def section(title: str):
    print(c(f"\n╭─ {title}", Style.bold, Style.violet))


def info(text: str):
    print(c("• ", Style.violet) + c(text, Style.white))


def success(text: str):
    print(c("✓ ", Style.ok) + c(text, Style.white))


def warn(text: str):
    print(c("! ", Style.warn) + c(text, Style.white))


def error(text: str):
    print(c("× ", Style.err) + c(text, Style.white))


@dataclass
class ChatItem:
    title: str
    peer_id: int
    is_user: bool
    is_group: bool
    is_channel: bool


@dataclass
class ForumTopicItem:
    chat_peer_id: int
    chat_title: str
    topic_id: int
    top_message_id: int
    title: str


def parse_tg_emoji_html(text: str):
    parts = []
    entities = []
    pos = 0
    utf16_offset = 0

    for match in TG_EMOJI_RE.finditer(text):
        before = text[pos:match.start()]
        if before:
            parts.append(before)
            utf16_offset += len(add_surrogate(before))

        doc_id_raw = match.group(1) or match.group(2) or match.group(3)
        emoji_text = html.unescape(match.group(4) or "").strip() or " "
        emoji_len = len(add_surrogate(emoji_text))

        parts.append(emoji_text)
        entities.append(
            MessageEntityCustomEmoji(
                offset=utf16_offset,
                length=emoji_len,
                document_id=int(doc_id_raw),
            )
        )
        utf16_offset += emoji_len
        pos = match.end()

    tail = text[pos:]
    if tail:
        parts.append(tail)

    return "".join(parts), entities


def ask(prompt: str, default: Optional[str] = None) -> str:
    suffix = c(f" [{default}]", Style.muted) if default is not None else ""
    value = input(c("› ", Style.pink) + c(prompt, Style.white) + suffix + c(": ", Style.violet)).strip()
    return value if value else (default or "")


def ask_indexes(prompt: str, max_count: int) -> list[int]:
    raw = ask(prompt)
    result = []
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            if start.isdigit() and end.isdigit():
                result.extend(range(int(start), int(end) + 1))
            continue
        if part.isdigit():
            result.append(int(part))
    return sorted({i for i in result if 1 <= i <= max_count})


def read_message() -> str:
    section("Текст сообщения")
    info("Вставьте текст сообщения. Завершите ввод строкой /done")
    lines = []
    while True:
        line = input()
        if line.strip() == "/done":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def print_qr_login_url(url: str):
    section("QR-вход")
    info("QR-ссылка для входа:")
    print(c(url, Style.pink))
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        print()
        qr.print_ascii(invert=True)
        print()
    except Exception:
        warn("Модуль qrcode недоступен, откройте ссылку вручную или установите qrcode.")


async def ensure_login(client: TelegramClient):
    await client.connect()
    if await client.is_user_authorized():
        success("Аккаунт уже авторизован.")
        return

    while True:
        section("Авторизация")
        print(c("  1", Style.violet) + c("  Войти по номеру телефона", Style.white))
        print(c("  2", Style.violet) + c("  Войти по QR", Style.white))
        choice = ask("Выбор", "1")

        if choice == "2":
            qr_login = await client.qr_login()
            print_qr_login_url(qr_login.url)
            info("Сканируйте QR в Telegram: Настройки -> Устройства -> Подключить устройство")
            try:
                await qr_login.wait(timeout=60)
                if await client.is_user_authorized():
                    success("Вход по QR выполнен.")
                    return
            except SessionPasswordNeededError:
                password = ask("Введите пароль 2FA")
                await client.sign_in(password=password)
                success("Авторизация успешна.")
                return
            except asyncio.TimeoutError:
                warn("QR истек. Можно запросить новый.")
            except Exception as exc:
                error(f"Ошибка QR-входа: {type(exc).__name__}: {exc}")
            continue

        phone = ask("Телефон в формате +79991234567")
        if not phone:
            warn("Номер пуст.")
            continue

        await client.send_code_request(phone)
        while True:
            code = ask("Код из Telegram")
            if not code:
                warn("Код пуст.")
                continue
            try:
                await client.sign_in(phone=phone, code=code)
                success("Авторизация успешна.")
                return
            except PhoneCodeInvalidError:
                error("Неверный код, попробуйте снова.")
            except SessionPasswordNeededError:
                password = ask("Введите пароль 2FA")
                await client.sign_in(password=password)
                success("Авторизация успешна.")
                return


async def load_chats(client: TelegramClient) -> list[ChatItem]:
    section("Чаты")
    info("Загружаю чаты...")
    dialogs = await client.get_dialogs(limit=200)
    items = []
    for dialog in dialogs:
        ent = dialog.entity
        title = dialog.name or getattr(ent, "title", None) or getattr(ent, "first_name", "") or "Без названия"
        peer_id = getattr(ent, "id", None)
        if peer_id is None:
            continue
        cls_name = ent.__class__.__name__.lower()
        is_user = cls_name.endswith("user")
        is_channel = cls_name.endswith("channel")
        is_group = ("chat" in cls_name) or (is_channel and getattr(ent, "megagroup", False))
        items.append(ChatItem(str(title), int(peer_id), bool(is_user), bool(is_group), bool(is_channel)))
    return items


def show_chats(chats: list[ChatItem]):
    section("Список чатов")
    for idx, chat in enumerate(chats, start=1):
        kind = "user" if chat.is_user else ("group" if chat.is_group else "channel")
        num = c(f"{idx:>3}", Style.violet, Style.bold)
        meta = c(f"[{kind}] ID:{chat.peer_id}", Style.muted)
        print(f"{num}  {c(chat.title, Style.white)}  {meta}")


async def load_forum_topics(client: TelegramClient, chats: list[ChatItem]) -> list[ForumTopicItem]:
    topics = []
    for chat in chats:
        try:
            entity = await client.get_entity(chat.peer_id)
            if not bool(getattr(entity, "forum", False)):
                continue
            result = await client(
                GetForumTopicsRequest(
                    peer=entity,
                    offset_date=None,
                    offset_id=0,
                    offset_topic=0,
                    limit=100,
                    q=None,
                )
            )
            chat_title = getattr(entity, "title", None) or chat.title
            for topic in getattr(result, "topics", []):
                title = getattr(topic, "title", None)
                top_message = getattr(topic, "top_message", None)
                topic_id = getattr(topic, "id", None)
                if title is None or top_message is None or topic_id is None:
                    continue
                topics.append(
                    ForumTopicItem(
                        chat_peer_id=int(chat.peer_id),
                        chat_title=str(chat_title),
                        topic_id=int(topic_id),
                        top_message_id=int(top_message),
                        title=str(title),
                    )
                )
        except Exception:
            continue
    return topics


def show_topics(topics: list[ForumTopicItem]):
    section("Форумные темы")
    for idx, topic in enumerate(topics, start=1):
        num = c(f"{idx:>3}", Style.violet, Style.bold)
        meta = c(f"topic #{topic.topic_id}", Style.muted)
        print(f"{num}  {c(topic.chat_title, Style.white)} {c('/', Style.pink)} {c(topic.title, Style.white)}  {meta}")


async def send_once(client: TelegramClient, target: dict, text: str, entities: list):
    peer_id = int(target["peer_id"])
    topic_id = target.get("topic_id")
    entity = await client.get_entity(peer_id)
    if topic_id is None:
        await client.send_message(entity, text, formatting_entities=entities or None)
        return

    input_peer = await client.get_input_entity(entity)
    await client(
        SendMessageRequest(
            peer=input_peer,
            message=text,
            reply_to=InputReplyToMessage(
                reply_to_msg_id=int(topic_id),
                top_msg_id=int(topic_id),
            ),
            entities=entities or None,
        )
    )


async def auto_send_loop(client: TelegramClient, targets: list[dict], message: str, cooldown_minutes: int):
    outgoing_text, entities = parse_tg_emoji_html(message)
    cooldown_minutes = max(int(cooldown_minutes), 5)
    per_chat_delay_sec = 3
    round_num = 0

    section("Рассылка")
    success(f"Старт: целей {len(targets)}, КД {cooldown_minutes} мин. Остановка: Ctrl+C")
    while True:
        round_num += 1
        print(c(f"\nКруг {round_num}", Style.bold, Style.violet))
        for idx, target in enumerate(targets, start=1):
            label = target.get("label") or str(target.get("peer_id"))
            try:
                await send_once(client, target, outgoing_text, entities)
                preview = outgoing_text[:80] + ("..." if len(outgoing_text) > 80 else "")
                success(f"[{idx}/{len(targets)}] Отправлено: {label} | {preview}")
            except FloodWaitError as exc:
                wait_s = max(int(getattr(exc, "seconds", 0)) or 0, per_chat_delay_sec)
                warn(f"[{idx}/{len(targets)}] FloodWait для {label}: жду {wait_s} сек")
                await asyncio.sleep(wait_s)
            except Exception as exc:
                error(f"[{idx}/{len(targets)}] Ошибка для {label}: {type(exc).__name__}: {exc}")

            if idx < len(targets):
                await asyncio.sleep(per_chat_delay_sec)

        info(f"Жду {cooldown_minutes} мин до следующего круга.")
        await asyncio.sleep(cooldown_minutes * 60)


async def choose_targets(client: TelegramClient) -> list[dict]:
    chats = await load_chats(client)
    show_chats(chats)
    chat_indexes = ask_indexes("\nВыберите чаты через запятую или диапазон, например 1,3,5-8", len(chats))
    selected_chats = [chats[i - 1] for i in chat_indexes]

    targets = []
    seen = set()
    for chat in selected_chats:
        key = (int(chat.peer_id), None)
        if key in seen:
            continue
        seen.add(key)
        targets.append({"peer_id": int(chat.peer_id), "topic_id": None, "label": chat.title})

    if selected_chats and ask("Загрузить форумные темы для выбранных чатов? y/n", "n").lower() == "y":
        topics = await load_forum_topics(client, selected_chats)
        if topics:
            show_topics(topics)
            topic_indexes = ask_indexes("Выберите темы через запятую или Enter, чтобы пропустить", len(topics))
            for index in topic_indexes:
                topic = topics[index - 1]
                plain_key = (int(topic.chat_peer_id), None)
                if plain_key in seen:
                    seen.remove(plain_key)
                    targets = [
                        target
                        for target in targets
                        if not (int(target["peer_id"]) == int(topic.chat_peer_id) and target.get("topic_id") is None)
                    ]

                key = (int(topic.chat_peer_id), int(topic.topic_id))
                if key in seen:
                    continue
                seen.add(key)
                targets.append(
                    {
                        "peer_id": int(topic.chat_peer_id),
                        "topic_id": int(topic.topic_id),
                        "label": f"{topic.chat_title} / {topic.title}",
                    }
                )
        else:
            warn("Форумные темы не найдены.")

    return targets


async def main():
    banner()
    if not API_ID or not API_HASH:
        error("Заполните API_ID и API_HASH в main.py или переменных окружения.")
        return

    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    try:
        await ensure_login(client)
        targets = await choose_targets(client)
        if not targets:
            warn("Цели не выбраны.")
            return

        message = read_message()
        if not message:
            warn("Текст пуст.")
            return

        cooldown = int(ask("КД в минутах", "5") or "5")
        await auto_send_loop(client, targets, message, cooldown)
    except KeyboardInterrupt:
        warn("\nОстановлено.")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
