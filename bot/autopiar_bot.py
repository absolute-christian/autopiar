import asyncio
import datetime
import html
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
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
from telethon.tl.types import MessageEntityCustomEmoji


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("AUTOPIAR_BOT_DATA_DIR", str(ROOT_DIR / "bot" / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = DATA_DIR / "config.json"
SESSION_PATH = DATA_DIR / "autopiar_user"
ENV_PATH = Path(__file__).resolve().parent / ".env"

TG_EMOJI_RE = re.compile(
    r'<tg-emoji\b[^>]*\bemoji-id\s*=\s*(?:"(\d+)"|\'(\d+)\'|(\d+))[^>]*>(.*?)</tg-emoji>',
    re.IGNORECASE | re.DOTALL,
)
EMOJI_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0xFE00, 0xFE0F))


@dataclass
class ChatItem:
    title: str
    peer_id: int
    is_user: bool
    is_group: bool
    is_channel: bool
    is_broadcast: bool
    is_bot: bool
    is_contact: bool
    folder_id: int = 0


@dataclass
class FolderItem:
    folder_id: int
    title: str
    peer_ids: list[int]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def telegram_plain_text(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "text"):
        return str(getattr(value, "text") or "")
    return str(value)


def strip_emoji_text(value: str) -> str:
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


def dialog_matches_telegram_filter(row: dict, dialog_filter, explicit_peer_ids: set, excluded_peer_ids: set) -> bool:
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
        emoji_text = html.unescape(match.group(4) or "").strip() or "🙂"
        emoji_len = len(add_surrogate(emoji_text))
        parts.append(emoji_text)
        entities.append(MessageEntityCustomEmoji(offset=utf16_offset, length=emoji_len, document_id=int(doc_id_raw)))
        utf16_offset += emoji_len
        pos = match.end()
    tail = text[pos:]
    if tail:
        parts.append(tail)
    return "".join(parts), entities


class BotApi:
    def __init__(self, token: str):
        self.base_url = f"https://api.telegram.org/bot{token}/"

    def request_sync(self, method: str, payload: Optional[dict] = None) -> dict:
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + method,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=70) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not data.get("ok"):
            raise RuntimeError(data)
        return data["result"]

    async def request(self, method: str, payload: Optional[dict] = None) -> dict:
        return await asyncio.to_thread(self.request_sync, method, payload)

    async def get_updates(self, offset: int, timeout: int = 45) -> list[dict]:
        return await self.request("getUpdates", {"offset": offset, "timeout": timeout, "allowed_updates": ["message", "callback_query"]})

    async def send_message(self, chat_id: int, text: str, reply_markup: Optional[dict] = None) -> dict:
        payload = {"chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return await self.request("sendMessage", payload)

    async def edit_message(self, chat_id: int, message_id: int, text: str, reply_markup: Optional[dict] = None) -> None:
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text[:4096], "disable_web_page_preview": True}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            await self.request("editMessageText", payload)
        except Exception:
            await self.send_message(chat_id, text, reply_markup)

    async def answer_callback(self, callback_query_id: str, text: str = "") -> None:
        await self.request("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})


class TelethonAccount:
    def __init__(self, notify):
        self.config = load_json(CONFIG_PATH, {})
        self.client: Optional[TelegramClient] = None
        self.notify = notify
        self.chats: list[ChatItem] = []
        self.folders: list[FolderItem] = []

    @property
    def api_id(self) -> int:
        return int(os.getenv("API_ID") or self.config.get("api_id") or 0)

    @property
    def api_hash(self) -> str:
        return str(os.getenv("API_HASH") or self.config.get("api_hash") or "").strip()

    def save_api(self, api_id: int, api_hash: str) -> None:
        self.config["api_id"] = int(api_id)
        self.config["api_hash"] = api_hash.strip()
        save_json(CONFIG_PATH, self.config)

    def has_api(self) -> bool:
        return self.api_id > 0 and bool(self.api_hash)

    async def ensure_client(self) -> TelegramClient:
        if not self.has_api():
            raise RuntimeError("API_ID/API_HASH не заданы.")
        if self.client is None:
            self.client = TelegramClient(str(SESSION_PATH), self.api_id, self.api_hash)
        if not self.client.is_connected():
            await self.client.connect()
        return self.client

    async def is_authorized(self) -> bool:
        client = await self.ensure_client()
        return bool(await client.is_user_authorized())

    async def request_code(self, phone: str):
        client = await self.ensure_client()
        return await client.send_code_request(phone)

    async def sign_in_code(self, phone: str, code: str, phone_code_hash: Optional[str]) -> None:
        client = await self.ensure_client()
        if phone_code_hash:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        else:
            await client.sign_in(phone=phone, code=code)

    async def sign_in_password(self, password: str) -> None:
        client = await self.ensure_client()
        await client.sign_in(password=password)

    async def qr_login_url(self):
        client = await self.ensure_client()
        return await client.qr_login()

    async def load_folders(self) -> list[FolderItem]:
        client = await self.ensure_client()
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram аккаунт не подключен.")
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
                    folder_names[int(folder_id)] = strip_emoji_text(title) or f"Папка {folder_id}"
                    folder_filters.append({
                        "id": int(folder_id),
                        "filter": item,
                        "explicit_peer_ids": dialog_filter_peer_ids(item),
                        "excluded_peer_ids": dialog_filter_peer_ids(item, ("exclude_peers",)),
                    })
            except Exception as exc:
                await self.notify(f"Не удалось загрузить папки Telegram: {type(exc).__name__}: {exc}")

        dialogs = await client.get_dialogs(limit=500)
        chats = []
        rows = []
        for dialog in dialogs:
            ent = dialog.entity
            peer_id = getattr(ent, "id", None)
            if peer_id is None:
                continue
            cls_name = ent.__class__.__name__.lower()
            is_user = cls_name.endswith("user")
            is_channel = cls_name.endswith("channel")
            is_group = ("chat" in cls_name) or (is_channel and getattr(ent, "megagroup", False))
            item = ChatItem(
                title=str(dialog.name or getattr(ent, "title", None) or getattr(ent, "first_name", "") or "Без названия"),
                peer_id=int(peer_id),
                is_user=bool(is_user),
                is_group=bool(is_group),
                is_channel=bool(is_channel),
                is_broadcast=bool(is_channel and not getattr(ent, "megagroup", False)),
                is_bot=bool(getattr(ent, "bot", False)),
                is_contact=bool(getattr(ent, "contact", False)),
                folder_id=int(getattr(dialog, "folder_id", None) or 0),
            )
            chats.append(item)
            rows.append(item.__dict__)

        folder_peer_ids = {0: [chat.peer_id for chat in chats]}
        for folder in folder_filters:
            folder_id = int(folder["id"])
            folder_peer_ids[folder_id] = [
                int(row["peer_id"])
                for row in rows
                if dialog_matches_telegram_filter(row, folder["filter"], folder["explicit_peer_ids"], folder["excluded_peer_ids"])
            ]

        self.chats = chats
        self.folders = [
            FolderItem(folder_id=int(folder_id), title=str(title), peer_ids=folder_peer_ids.get(int(folder_id), []))
            for folder_id, title in sorted(folder_names.items(), key=lambda pair: (pair[0], pair[1]))
            if folder_peer_ids.get(int(folder_id))
        ]
        return self.folders

    async def send_to_peer(self, peer_id: int, text: str, entities: list):
        client = await self.ensure_client()
        entity = await client.get_entity(peer_id)
        await client.send_message(entity, text, formatting_entities=entities or None)


class AutoPiarBot:
    def __init__(self, bot: BotApi, owner_id: int):
        self.bot = bot
        self.owner_id = owner_id
        self.account = TelethonAccount(self.notify_owner)
        self.state = load_json(DATA_DIR / "state.json", {"cooldown": 5, "message": "", "folder_id": None})
        self.mode: Optional[str] = None
        self.auth_phone = ""
        self.phone_code_hash: Optional[str] = None
        self.sending_task: Optional[asyncio.Task] = None
        self.qr_task: Optional[asyncio.Task] = None

    def save_state(self) -> None:
        save_json(DATA_DIR / "state.json", self.state)

    async def notify_owner(self, text: str) -> None:
        await self.bot.send_message(self.owner_id, text)

    def is_owner_update(self, update: dict) -> bool:
        source = update.get("message") or update.get("callback_query", {}).get("message") or {}
        chat = source.get("chat") or {}
        from_user = update.get("message", {}).get("from") or update.get("callback_query", {}).get("from") or {}
        return int(chat.get("id") or 0) == self.owner_id and int(from_user.get("id") or 0) == self.owner_id

    def menu_markup(self) -> dict:
        rows = [
            [{"text": "Статус", "callback_data": "status"}, {"text": "Подключить аккаунт", "callback_data": "auth_menu"}],
            [{"text": "Загрузить папки", "callback_data": "folders"}],
            [{"text": "Текст поста", "callback_data": "set_msg"}, {"text": "КД", "callback_data": "cooldown_menu"}],
            [{"text": "Старт", "callback_data": "start_send"}, {"text": "Стоп", "callback_data": "stop_send"}],
        ]
        return {"inline_keyboard": rows}

    def auth_markup(self) -> dict:
        return {
            "inline_keyboard": [
                [{"text": "API ID / HASH", "callback_data": "api_settings"}],
                [{"text": "Вход по телефону", "callback_data": "auth_phone"}, {"text": "Вход по QR", "callback_data": "auth_qr"}],
                [{"text": "Назад", "callback_data": "menu"}],
            ]
        }

    def cooldown_markup(self) -> dict:
        return {
            "inline_keyboard": [
                [{"text": "5 мин", "callback_data": "cd:5"}, {"text": "10 мин", "callback_data": "cd:10"}, {"text": "15 мин", "callback_data": "cd:15"}],
                [{"text": "30 мин", "callback_data": "cd:30"}, {"text": "60 мин", "callback_data": "cd:60"}, {"text": "Свое", "callback_data": "cd_custom"}],
                [{"text": "Назад", "callback_data": "menu"}],
            ]
        }

    def folders_markup(self) -> dict:
        rows = []
        for folder in self.account.folders:
            rows.append([{"text": f"{folder.title} ({len(folder.peer_ids)})", "callback_data": f"folder:{folder.folder_id}"}])
        rows.append([{"text": "Назад", "callback_data": "menu"}])
        return {"inline_keyboard": rows}

    def status_text(self) -> str:
        selected = next((f for f in self.account.folders if f.folder_id == self.state.get("folder_id")), None)
        selected_text = f"{selected.title} ({len(selected.peer_ids)})" if selected else "не выбрана"
        message_text = "задан" if self.state.get("message") else "не задан"
        sending = "идет" if self.sending_task and not self.sending_task.done() else "остановлена"
        return (
            "AutoPiar Bot\n"
            f"API: {'задан' if self.account.has_api() else 'не задан'}\n"
            f"Папка: {selected_text}\n"
            f"КД: {int(self.state.get('cooldown') or 5)} мин\n"
            f"Текст: {message_text}\n"
            f"Рассылка: {sending}"
        )

    async def show_menu(self, chat_id: int, message_id: Optional[int] = None):
        text = self.status_text()
        if message_id:
            await self.bot.edit_message(chat_id, message_id, text, self.menu_markup())
        else:
            await self.bot.send_message(chat_id, text, self.menu_markup())

    async def handle_message(self, message: dict):
        chat_id = int(message["chat"]["id"])
        text = str(message.get("text") or "").strip()
        if text == "/start":
            self.mode = None
            await self.show_menu(chat_id)
            return
        if self.mode == "api_id":
            try:
                self.state["pending_api_id"] = int(text)
            except ValueError:
                await self.bot.send_message(chat_id, "API ID должен быть числом.")
                return
            self.mode = "api_hash"
            await self.bot.send_message(chat_id, "Теперь отправь API HASH.")
            return
        if self.mode == "api_hash":
            api_id = int(self.state.pop("pending_api_id"))
            self.account.save_api(api_id, text)
            self.mode = None
            await self.bot.send_message(chat_id, "API настройки сохранены.", self.auth_markup())
            return
        if self.mode == "phone":
            self.auth_phone = text
            try:
                result = await self.account.request_code(text)
                self.phone_code_hash = getattr(result, "phone_code_hash", None)
                self.mode = "code"
                await self.bot.send_message(chat_id, "Код отправлен. Пришли код из Telegram.")
            except Exception as exc:
                self.mode = None
                await self.bot.send_message(chat_id, f"Не удалось отправить код: {type(exc).__name__}: {exc}", self.auth_markup())
            return
        if self.mode == "code":
            try:
                await self.account.sign_in_code(self.auth_phone, text, self.phone_code_hash)
                self.mode = None
                await self.bot.send_message(chat_id, "Аккаунт подключен.", self.menu_markup())
            except PhoneCodeInvalidError:
                await self.bot.send_message(chat_id, "Неверный код. Пришли код еще раз.")
            except SessionPasswordNeededError:
                self.mode = "password"
                await self.bot.send_message(chat_id, "Включена 2FA. Пришли пароль 2FA.")
            except Exception as exc:
                self.mode = None
                await self.bot.send_message(chat_id, f"Ошибка входа: {type(exc).__name__}: {exc}", self.auth_markup())
            return
        if self.mode == "password":
            try:
                await self.account.sign_in_password(text)
                self.mode = None
                await self.bot.send_message(chat_id, "2FA пройдена, аккаунт подключен.", self.menu_markup())
            except Exception as exc:
                await self.bot.send_message(chat_id, f"Ошибка 2FA: {type(exc).__name__}: {exc}")
            return
        if self.mode == "message":
            self.state["message"] = text
            self.save_state()
            self.mode = None
            await self.bot.send_message(chat_id, "Текст сохранен.", self.menu_markup())
            return
        if self.mode == "cooldown":
            try:
                cooldown = max(1, int(text))
            except ValueError:
                await self.bot.send_message(chat_id, "Пришли число минут.")
                return
            self.state["cooldown"] = cooldown
            self.save_state()
            self.mode = None
            await self.bot.send_message(chat_id, f"КД сохранен: {cooldown} мин.", self.menu_markup())
            return
        await self.show_menu(chat_id)

    async def handle_callback(self, callback: dict):
        data = callback.get("data") or ""
        message = callback.get("message") or {}
        chat_id = int(message.get("chat", {}).get("id") or self.owner_id)
        message_id = int(message.get("message_id") or 0)
        await self.bot.answer_callback(callback["id"])
        if data == "menu":
            self.mode = None
            await self.show_menu(chat_id, message_id)
        elif data == "status":
            await self.show_menu(chat_id, message_id)
        elif data == "auth_menu":
            await self.bot.edit_message(chat_id, message_id, "Подключение Telegram аккаунта", self.auth_markup())
        elif data == "api_settings":
            self.mode = "api_id"
            await self.bot.send_message(chat_id, "Отправь API ID числом. Взять можно на https://my.telegram.org/apps")
        elif data == "auth_phone":
            if not self.account.has_api():
                self.mode = "api_id"
                await self.bot.send_message(chat_id, "Сначала отправь API ID числом.")
            else:
                self.mode = "phone"
                await self.bot.send_message(chat_id, "Отправь номер телефона в формате +79990000000.")
        elif data == "auth_qr":
            await self.start_qr_login(chat_id)
        elif data == "folders":
            await self.load_and_show_folders(chat_id, message_id)
        elif data.startswith("folder:"):
            self.state["folder_id"] = int(data.split(":", 1)[1])
            self.save_state()
            await self.show_menu(chat_id, message_id)
        elif data == "cooldown_menu":
            await self.bot.edit_message(chat_id, message_id, "Выбери КД между кругами рассылки.", self.cooldown_markup())
        elif data.startswith("cd:"):
            self.state["cooldown"] = int(data.split(":", 1)[1])
            self.save_state()
            await self.show_menu(chat_id, message_id)
        elif data == "cd_custom":
            self.mode = "cooldown"
            await self.bot.send_message(chat_id, "Отправь КД в минутах числом.")
        elif data == "set_msg":
            self.mode = "message"
            await self.bot.send_message(chat_id, "Отправь текст поста одним сообщением.")
        elif data == "start_send":
            await self.start_sending(chat_id)
        elif data == "stop_send":
            await self.stop_sending(chat_id)

    async def start_qr_login(self, chat_id: int):
        if not self.account.has_api():
            self.mode = "api_id"
            await self.bot.send_message(chat_id, "Сначала отправь API ID числом.")
            return
        if self.qr_task and not self.qr_task.done():
            await self.bot.send_message(chat_id, "QR вход уже ожидает сканирования.")
            return
        try:
            qr_login = await self.account.qr_login_url()
            expires = qr_login.expires.astimezone(datetime.timezone.utc).strftime("%H:%M:%S UTC")
            await self.bot.send_message(chat_id, f"Открой ссылку или отсканируй QR через Telegram:\n{qr_login.url}\nИстекает: {expires}")
            self.qr_task = asyncio.create_task(self.wait_qr_login(qr_login))
        except Exception as exc:
            await self.bot.send_message(chat_id, f"Не удалось создать QR вход: {type(exc).__name__}: {exc}")

    async def wait_qr_login(self, qr_login):
        timeout = max((qr_login.expires - datetime.datetime.now(tz=datetime.timezone.utc)).total_seconds(), 1.0)
        try:
            await qr_login.wait(timeout=timeout)
            await self.notify_owner("QR вход выполнен. Аккаунт подключен.")
        except SessionPasswordNeededError:
            self.mode = "password"
            await self.notify_owner("QR принят, но включена 2FA. Пришли пароль 2FA.")
        except asyncio.TimeoutError:
            await self.notify_owner("QR вход истек. Запроси новый QR.")
        except Exception as exc:
            await self.notify_owner(f"Ошибка QR входа: {type(exc).__name__}: {exc}")

    async def load_and_show_folders(self, chat_id: int, message_id: int):
        try:
            folders = await self.account.load_folders()
            if not folders:
                await self.bot.send_message(chat_id, "Папки/чаты не найдены.")
                return
            await self.bot.edit_message(chat_id, message_id, "Выбери папку для рассылки.", self.folders_markup())
        except Exception as exc:
            await self.bot.send_message(chat_id, f"Не удалось загрузить папки: {type(exc).__name__}: {exc}", self.auth_markup())

    async def start_sending(self, chat_id: int):
        if self.sending_task and not self.sending_task.done():
            await self.bot.send_message(chat_id, "Рассылка уже идет.")
            return
        folder_id = self.state.get("folder_id")
        folder = next((f for f in self.account.folders if f.folder_id == folder_id), None)
        if not folder:
            await self.bot.send_message(chat_id, "Сначала загрузи и выбери папку.")
            return
        message = str(self.state.get("message") or "").strip()
        if not message:
            await self.bot.send_message(chat_id, "Сначала задай текст поста.")
            return
        self.sending_task = asyncio.create_task(self.sending_loop(folder, message, int(self.state.get("cooldown") or 5)))
        await self.bot.send_message(chat_id, f"Рассылка запущена: {folder.title}, целей {len(folder.peer_ids)}.")

    async def stop_sending(self, chat_id: int):
        if self.sending_task and not self.sending_task.done():
            self.sending_task.cancel()
            await self.bot.send_message(chat_id, "Останавливаю рассылку.")
        else:
            await self.bot.send_message(chat_id, "Рассылка не запущена.")

    async def sending_loop(self, folder: FolderItem, message: str, cooldown_minutes: int):
        outgoing_text, entities = parse_tg_emoji_html(message)
        round_num = 0
        try:
            while True:
                round_num += 1
                await self.notify_owner(f"Круг {round_num}: отправка в папку {folder.title}.")
                for index, peer_id in enumerate(folder.peer_ids, start=1):
                    label = next((chat.title for chat in self.account.chats if chat.peer_id == peer_id), str(peer_id))
                    try:
                        await self.account.send_to_peer(peer_id, outgoing_text, entities)
                    except FloodWaitError as exc:
                        wait_s = int(getattr(exc, "seconds", 0) or 0)
                        await self.notify_owner(f"[{index}/{len(folder.peer_ids)}] FloodWait для {label}: жду {wait_s} сек.")
                        await asyncio.sleep(max(wait_s, 1))
                        continue
                    except Exception as exc:
                        await self.notify_owner(f"[{index}/{len(folder.peer_ids)}] Ошибка для {label}: {type(exc).__name__}: {exc}")
                    if index < len(folder.peer_ids):
                        await asyncio.sleep(3)
                await self.notify_owner(f"Круг {round_num} завершен. Следующий через {cooldown_minutes} мин.")
                await asyncio.sleep(max(cooldown_minutes, 1) * 60)
        except asyncio.CancelledError:
            await self.notify_owner("Рассылка остановлена.")

    async def handle_update(self, update: dict):
        if not self.is_owner_update(update):
            return
        if "message" in update:
            await self.handle_message(update["message"])
        elif "callback_query" in update:
            await self.handle_callback(update["callback_query"])


async def main():
    load_dotenv(ENV_PATH)
    token = os.getenv("BOT_TOKEN", "").strip()
    owner_id = int(os.getenv("OWNER_ID", "0") or 0)
    if not token or not owner_id:
        raise SystemExit("Set BOT_TOKEN and OWNER_ID in bot/.env or environment.")
    bot = AutoPiarBot(BotApi(token), owner_id)
    offset = 0
    await bot.notify_owner("AutoPiar bot запущен. Нажми /start")
    while True:
        try:
            updates = await bot.bot.get_updates(offset)
            for update in updates:
                offset = max(offset, int(update["update_id"]) + 1)
                try:
                    await bot.handle_update(update)
                except Exception as exc:
                    await bot.notify_owner(f"Ошибка обработки update: {type(exc).__name__}: {exc}")
        except Exception as exc:
            print(f"Polling error: {type(exc).__name__}: {exc}", file=sys.stderr)
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
