# -*- coding: utf-8 -*-
import asyncio
import html
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError, PhoneCodeInvalidError, SessionPasswordNeededError
from telethon.helpers import add_surrogate
try:
    from telethon.tl.functions.messages import GetDialogFiltersRequest
except Exception:
    GetDialogFiltersRequest = None
from telethon.tl.functions.messages import GetForumTopicsRequest, SendMessageRequest
from telethon.tl.types import InputReplyToMessage, MessageEntityCustomEmoji

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from online_license import require_cli_license


API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
DATA_DIR = Path(os.getenv("AUTOPIAR_DATA_DIR", str(Path.home() / ".autopiar")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SESSION_NAME = os.getenv("SESSION_NAME", str(DATA_DIR / "termux_auto_piar"))
COLOR_ENABLED = os.getenv("NO_COLOR", "").strip() == ""

TG_EMOJI_RE = re.compile(
    r'<tg-emoji\b[^>]*\bemoji-id\s*=\s*(?:"(\d+)"|\'(\d+)\'|(\d+))[^>]*>(.*?)</tg-emoji>',
    re.IGNORECASE | re.DOTALL,
)

EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),
    (0x2600, 0x27BF),
    (0xFE00, 0xFE0F),
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
    is_broadcast: bool = False
    is_bot: bool = False
    is_contact: bool = False
    folder_id: int = 0
    folder_title: str = "Все чаты"


@dataclass
class FolderItem:
    id: int
    title: str
    count: int
    peer_ids: list[int]


@dataclass
class ForumTopicItem:
    chat_peer_id: int
    chat_title: str
    topic_id: int
    top_message_id: int
    title: str


def telegram_plain_text(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "text"):
        return str(getattr(value, "text") or "")
    return str(value)


def strip_emoji_text(value) -> str:
    raw = TG_EMOJI_RE.sub("", telegram_plain_text(value))
    cleaned = []
    for ch in raw:
        code = ord(ch)
        if code == 0x200D:
            continue
        if any(start <= code <= end for start, end in EMOJI_RANGES):
            continue
        if unicodedata.category(ch) == "So":
            continue
        cleaned.append(ch)
    return re.sub(r"\s+", " ", "".join(cleaned)).strip()


def peer_local_id(peer) -> Optional[int]:
    if peer is None:
        return None
    nested_peer = getattr(peer, "peer", None)
    if nested_peer is not None:
        nested_id = peer_local_id(nested_peer)
        if nested_id is not None:
            return nested_id
    for attr in ("user_id", "chat_id", "channel_id", "id"):
        value = getattr(peer, attr, None)
        if value is not None:
            try:
                return int(value)
            except Exception:
                return None
    return None


def dialog_filter_peer_ids(dialog_filter, attrs=("include_peers", "pinned_peers")) -> set[int]:
    ids = set()
    for attr in attrs:
        for peer in getattr(dialog_filter, attr, None) or []:
            peer_id = peer_local_id(peer)
            if peer_id is not None:
                ids.add(peer_id)
    return ids


def dialog_matches_telegram_filter(row: dict, dialog_filter, explicit_peer_ids: set[int], excluded_peer_ids: set[int]) -> bool:
    peer_id = int(row.get("peer_id") or 0)
    if peer_id in excluded_peer_ids:
        return False
    if peer_id in explicit_peer_ids:
        return True

    include_groups = bool(getattr(dialog_filter, "groups", False) or getattr(dialog_filter, "include_groups", False))
    include_broadcasts = bool(getattr(dialog_filter, "broadcasts", False) or getattr(dialog_filter, "include_broadcasts", False))
    include_bots = bool(getattr(dialog_filter, "bots", False) or getattr(dialog_filter, "include_bots", False))
    include_contacts = bool(getattr(dialog_filter, "contacts", False) or getattr(dialog_filter, "include_contacts", False))
    include_non_contacts = bool(getattr(dialog_filter, "non_contacts", False) or getattr(dialog_filter, "include_non_contacts", False))

    if bool(row.get("is_group")) and include_groups:
        return True
    if bool(row.get("is_broadcast")) and include_broadcasts:
        return True
    if bool(row.get("is_bot")) and include_bots:
        return True
    if bool(row.get("is_user")) and bool(row.get("is_contact")) and include_contacts:
        return True
    if bool(row.get("is_user")) and not bool(row.get("is_contact")) and not bool(row.get("is_bot")) and include_non_contacts:
        return True
    return False


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
    info("Вставьте текст сообщения. Напишите /done на новой строке и нажмите Enter чтобы запустить отправку.")
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
        warn("Модуль qr-code недоступен, откройте ссылку вручную или установите qrcode.")


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

        phone = ask("Телефон в формате +хххххххххх")
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


async def load_chats_and_folders(client: TelegramClient) -> tuple[list[ChatItem], list[FolderItem]]:
    section("Папки")
    info("Загружаю папки Telegram...")
    folder_names = {0: "Все чаты"}
    folder_filters = []
    if GetDialogFiltersRequest is not None:
        try:
            result = await client(GetDialogFiltersRequest())
            filters = getattr(result, "filters", result)
            for item in filters:
                folder_id = getattr(item, "id", None)
                title = getattr(item, "title", None)
                if folder_id is None or not title:
                    continue
                clean_title = strip_emoji_text(title) or f"Папка {folder_id}"
                folder_names[int(folder_id)] = clean_title
                folder_filters.append(
                    {
                        "id": int(folder_id),
                        "title": clean_title,
                        "filter": item,
                        "explicit_peer_ids": dialog_filter_peer_ids(item),
                        "excluded_peer_ids": dialog_filter_peer_ids(item, ("exclude_peers",)),
                    }
                )
        except Exception as exc:
            warn(f"Не удалось загрузить папки Telegram: {type(exc).__name__}: {exc}")

    dialogs = await client.get_dialogs(limit=500)
    items = []
    dialog_rows = []
    folder_counts = {folder_id: 0 for folder_id in folder_names}
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
        is_broadcast = bool(is_channel and not getattr(ent, "megagroup", False))
        is_bot = bool(getattr(ent, "bot", False))
        is_contact = bool(getattr(ent, "contact", False))
        folder_id = int(getattr(dialog, "folder_id", None) or 0)
        folder_title = folder_names.get(folder_id, f"Папка {folder_id}")
        folder_counts[folder_id] = folder_counts.get(folder_id, 0) + 1
        chat_item = ChatItem(
            str(title),
            int(peer_id),
            bool(is_user),
            bool(is_group),
            bool(is_channel),
            bool(is_broadcast),
            bool(is_bot),
            bool(is_contact),
            folder_id,
            folder_title,
        )
        items.append(chat_item)
        dialog_rows.append(
            {
                "peer_id": int(peer_id),
                "is_user": bool(is_user),
                "is_group": bool(is_group),
                "is_broadcast": bool(is_broadcast),
                "is_bot": bool(is_bot),
                "is_contact": bool(is_contact),
            }
        )

    folder_peer_ids = {0: [int(chat.peer_id) for chat in items]}
    for folder in folder_filters:
        folder_id = int(folder["id"])
        explicit_ids = folder["explicit_peer_ids"]
        excluded_ids = folder["excluded_peer_ids"]
        filter_obj = folder["filter"]
        matched = [
            int(row["peer_id"])
            for row in dialog_rows
            if dialog_matches_telegram_filter(row, filter_obj, explicit_ids, excluded_ids)
        ]
        folder_peer_ids[folder_id] = matched
        folder_counts[folder_id] = len(matched)

    folders = [
        FolderItem(
            int(folder_id),
            str(title),
            int(folder_counts.get(folder_id, 0)),
            folder_peer_ids.get(int(folder_id), []),
        )
        for folder_id, title in sorted(folder_names.items(), key=lambda pair: (pair[0], pair[1]))
        if int(folder_counts.get(folder_id, 0)) > 0
    ]
    return items, folders


def show_folders(folders: list[FolderItem]):
    section("Папки Telegram")
    for idx, folder in enumerate(folders, start=1):
        num = c(f"{idx:>3}", Style.violet, Style.bold)
        meta = c(f"{folder.count} чатов", Style.muted)
        print(f"{num}  {c(folder.title, Style.white)}  {meta}")


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
    chats, folders = await load_chats_and_folders(client)
    if not folders:
        warn("Папки Telegram не найдены.")
        return []

    show_folders(folders)
    folder_indexes = ask_indexes("\nВыберите папки через запятую или диапазон, например 1,3,5-8", len(folders))
    selected_folders = [folders[i - 1] for i in folder_indexes]
    if not selected_folders:
        return []

    selected_peer_ids = set()
    for folder in selected_folders:
        selected_peer_ids.update(int(peer_id) for peer_id in folder.peer_ids)

    selected_chats = [chat for chat in chats if int(chat.peer_id) in selected_peer_ids]
    selected_titles = ", ".join(folder.title for folder in selected_folders)
    success(f"Выбрано папок: {len(selected_folders)} | Чатов внутри: {len(selected_chats)}")
    info(f"Папки: {selected_titles}")

    targets = []
    seen = set()
    for chat in selected_chats:
        key = (int(chat.peer_id), None)
        if key in seen:
            continue
        seen.add(key)
        targets.append({"peer_id": int(chat.peer_id), "topic_id": None, "label": chat.title})

    if selected_chats and ask("Загрузить форумные темы для выбранных папок? y/n", "n").lower() == "y":
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
    license_result = require_cli_license()
    if not license_result.ok:
        error(license_result.message)
        return
    success("Лицензия активна.")

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
