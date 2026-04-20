import sys
import os
import asyncio
import datetime
import io
import json
import re
import html
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import List, Optional

def _configure_qt_plugin_path():
    """
    Windows fix: point Qt to the bundled platforms plugin folder if env vars are empty/wrong.
    """
    if os.name != "nt":
        return

    # Keep explicit non-empty user config, but fix empty values.
    current = os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH")
    if current and os.path.isfile(os.path.join(current, "qwindows.dll")):
        return

    try:
        import PyQt5
    except Exception:
        return

    pyqt_dir = os.path.dirname(PyQt5.__file__)
    candidates = [
        os.path.join(pyqt_dir, "Qt5", "plugins", "platforms"),
        os.path.join(pyqt_dir, "Qt", "plugins", "platforms"),
    ]

    for path in candidates:
        if os.path.isfile(os.path.join(path, "qwindows.dll")):
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = path
            break


_configure_qt_plugin_path()

from PyQt5 import QtCore, QtGui, QtWidgets

from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    FloodWaitError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    PasswordHashInvalidError,
)
from telethon.sessions import StringSession
from telethon.helpers import add_surrogate
from telethon.tl.types import MessageEntityCustomEmoji
try:
    from telethon.tl.functions.messages import GetDialogFiltersRequest
except Exception:
    GetDialogFiltersRequest = None
from telethon.tl.functions.messages import GetForumTopicsRequest
from telethon.tl.functions.messages import SendMessageRequest
from telethon.tl.types import InputReplyToMessage


TG_EMOJI_RE = re.compile(
    r'<tg-emoji\b[^>]*\bemoji-id\s*=\s*(?:"(\d+)"|\'(\d+)\'|(\d+))[^>]*>(.*?)</tg-emoji>',
    re.IGNORECASE | re.DOTALL,
)

EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),
    (0x2600, 0x27BF),
    (0xFE00, 0xFE0F),
)


def telegram_plain_text(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "text"):
        return str(getattr(value, "text") or "")
    return str(value)


def strip_emoji_text(value: str) -> str:
    """
    Removes visual emoji from Telegram folder names, including premium emoji rendered as tags.
    """
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
    """
    Telegram folders store peers as Peer/InputPeer objects. For UI filtering we only need
    the local id because ChatItem.peer_id is also the entity id from Telethon dialogs.
    """
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


def dialog_filter_peer_ids(dialog_filter, attrs=("include_peers", "pinned_peers")) -> set:
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

    # If a folder is category-based, Telegram exposes these flags on DialogFilter.
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
    """
    Converts Telegram-style <tg-emoji emoji-id="...">🙂</tg-emoji> tags
    into plain text + MessageEntityCustomEmoji entities.
    """
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


# -----------------------------
# Настройки проекта (ОБЯЗАТЕЛЬНО заполнить)
# -----------------------------
API_ID = 0          # заполняется через "API настройки" или configs/api_credentials.json
API_HASH = ""       # заполняется через "API настройки" или configs/api_credentials.json

APP_TITLE = "Telethon Neon Sender"
DEFAULT_SESSION_NAME = "telethon_gui.session"  # будет создан рядом со скриптом
API_CONFIG_FILE = os.path.join("configs", "api_credentials.json")
PROFILES_FILE = os.path.join("configs", "profiles.json")


def runtime_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def config_path(relative_path: str) -> str:
    return os.path.join(runtime_base_dir(), relative_path)


def parse_import_target(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urllib.parse.urlparse(raw if "://" in raw else f"https://{raw}")
    except Exception:
        parsed = None
    if parsed and parsed.netloc.lower() in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
        path = (parsed.path or "").strip("/")
        if path and not path.startswith("+") and not path.lower().startswith("joinchat/"):
            return f"@{path.split('/', 1)[0]}"
    return raw


# -----------------------------
# Data models
# -----------------------------
@dataclass
class ChatItem:
    title: str
    peer_id: int
    is_user: bool
    is_group: bool
    is_channel: bool
    folder_id: int = 0
    folder_title: str = "Все чаты"


@dataclass
class ForumTopicItem:
    chat_peer_id: int
    chat_title: str
    topic_id: int
    top_message_id: int
    title: str


# -----------------------------
# Worker: Telethon + asyncio in QThread
# -----------------------------
class TelethonWorker(QtCore.QObject):
    # Сигналы -> GUI
    log = QtCore.pyqtSignal(str)
    auth_state = QtCore.pyqtSignal(str)              # "need_phone" | "need_code" | "need_password" | "authorized" | "error"
    qr_login_ready = QtCore.pyqtSignal(str, int)     # qr_url, expires_unix_ts
    account_info = QtCore.pyqtSignal(dict)
    folders_loaded = QtCore.pyqtSignal(list)         # List[{"id": int, "title": str, "count": int}]
    chats_loaded = QtCore.pyqtSignal(list)           # List[ChatItem]
    forum_topics_loaded = QtCore.pyqtSignal(list)    # List[ForumTopicItem]
    sending_state = QtCore.pyqtSignal(bool)          # True when sending, False otherwise

    def __init__(self, api_id: int, api_hash: str, session_path: str):
        super().__init__()
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_path = session_path

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._client: Optional[TelegramClient] = None

        self._phone: Optional[str] = None
        self._phone_code_hash: Optional[str] = None
        self._qr_login = None
        self._qr_wait_task: Optional[asyncio.Task] = None

        self._stop_event: Optional[asyncio.Event] = None
        self._sending_task: Optional[asyncio.Task] = None


    # --- Thread lifecycle ---
    @QtCore.pyqtSlot()
    def start(self):
        """
        Запускается внутри QThread. Создаёт event loop и держит его живым.
        """
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self._loop.create_task(self._init_client())
        self._loop.create_task(self._idle_forever())

        try:
            self._loop.run_forever()
        finally:
            try:
                if self._client:
                    self._loop.run_until_complete(self._client.disconnect())
            except Exception:
                pass

            pending = asyncio.all_tasks(self._loop)
            for t in pending:
                t.cancel()
            try:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            self._loop.close()

    async def _idle_forever(self):
        while True:
            await asyncio.sleep(3600)

    async def _init_client(self):
        """
        Инициализируем TelegramClient с файловой сессией.
        """
        try:
            # Telethon сам создаст/прочитает session файл
            self._client = TelegramClient(self.session_path, self.api_id, self.api_hash)
            await self._client.connect()

            if await self._client.is_user_authorized():
                self.log.emit("✅ Уже авторизованы (сессия найдена).")
                await self._emit_account_info()
                self.auth_state.emit("authorized")
            else:
                self.log.emit("ℹ️ Требуется авторизация: введите номер телефона.")
                self.auth_state.emit("need_phone")
        except Exception as e:
            self.log.emit(f"❌ Ошибка инициализации клиента: {e}")
            self.auth_state.emit("error")

    def _ensure_ready(self) -> bool:
        if not self._loop or not self._client:
            self.log.emit("⏳ Клиент ещё не готов. Подождите секунду и попробуйте снова.")
            return False
        return True

    # --- Public API (called from GUI thread via run_coroutine_threadsafe) ---
    def request_code(self, phone: str):
        if not self._ensure_ready():
            return
        fut = asyncio.run_coroutine_threadsafe(self._request_code(phone), self._loop)
        fut.add_done_callback(self._silent_callback)

    def request_qr_login(self):
        if not self._ensure_ready():
            return
        fut = asyncio.run_coroutine_threadsafe(self._request_qr_login(), self._loop)
        fut.add_done_callback(self._silent_callback)

    async def _request_qr_login(self):
        if await self._client.is_user_authorized():
            self.log.emit("Аккаунт уже авторизован.")
            self.auth_state.emit("authorized")
            return

        try:
            self._qr_login = await self._client.qr_login()
            expires_ts = int(self._qr_login.expires.timestamp())
            self.qr_login_ready.emit(self._qr_login.url, expires_ts)
            self.log.emit("QR-токен создан. Откройте Telegram -> Настройки -> Устройства -> Подключить устройство.")

            if self._qr_wait_task and not self._qr_wait_task.done():
                self._qr_wait_task.cancel()
                try:
                    await self._qr_wait_task
                except Exception:
                    pass

            self._qr_wait_task = asyncio.create_task(self._wait_qr_login(self._qr_login))
        except Exception as e:
            self.log.emit(f"Не удалось создать QR-токен: {type(e).__name__}: {e}")
            self.auth_state.emit("error")

    async def _wait_qr_login(self, qr_login_obj):
        timeout = max(
            (qr_login_obj.expires - datetime.datetime.now(tz=datetime.timezone.utc)).total_seconds(),
            1.0,
        )
        try:
            await qr_login_obj.wait(timeout=timeout)
            if await self._client.is_user_authorized():
                self.log.emit("Вход по QR выполнен.")
                await self._emit_account_info()
                self.auth_state.emit("authorized")
        except SessionPasswordNeededError:
            self.log.emit("Включена 2FA. Введите пароль 2FA.")
            self.auth_state.emit("need_password")
        except asyncio.TimeoutError:
            self.log.emit("Срок действия QR истек. Запросите новый QR.")
        except Exception as e:
            self.log.emit(f"Ошибка входа по QR: {type(e).__name__}: {e}")
            self.auth_state.emit("error")
        finally:
            self._qr_wait_task = None

    async def _request_code(self, phone: str):
        phone = phone.strip()
        if not phone:
            self.log.emit("⚠️ Номер телефона пуст.")
            return

        try:
            self._phone = phone
            self.log.emit("📨 Отправляю код подтверждения в Telegram…")
            result = await self._client.send_code_request(phone)
            # В Telethon это обычно result.phone_code_hash
            self._phone_code_hash = getattr(result, "phone_code_hash", None)
            self.auth_state.emit("need_code")
            self.log.emit("✅ Код отправлен. Введите код из Telegram.")
        except PhoneNumberInvalidError:
            self.log.emit("❌ Некорректный номер телефона.")
            self.auth_state.emit("need_phone")
        except Exception as e:
            self.log.emit(f"❌ Ошибка отправки кода: {e}")
            self.auth_state.emit("error")

    def sign_in_with_code(self, code: str):
        if not self._ensure_ready():
            return
        fut = asyncio.run_coroutine_threadsafe(self._sign_in_with_code(code), self._loop)
        fut.add_done_callback(self._silent_callback)

    async def _sign_in_with_code(self, code: str):
        code = code.strip()
        if not self._phone:
            self.log.emit("⚠️ Сначала введите номер телефона.")
            self.auth_state.emit("need_phone")
            return

        if not code:
            self.log.emit("⚠️ Код пуст.")
            return

        try:
            self.log.emit("🔐 Выполняю вход по коду…")
            # phone_code_hash можно не передавать — Telethon сам подхватит из send_code_request,
            # но оставим как явную опцию при наличии.
            if self._phone_code_hash:
                await self._client.sign_in(phone=self._phone, code=code, phone_code_hash=self._phone_code_hash)
            else:
                await self._client.sign_in(phone=self._phone, code=code)

            self.log.emit("✅ Успешная авторизация.")
            await self._emit_account_info()
            self.auth_state.emit("authorized")
        except SessionPasswordNeededError:
            self.log.emit("🔒 Включена 2FA. Введите пароль 2FA.")
            self.auth_state.emit("need_password")
        except PhoneCodeInvalidError:
            self.log.emit("❌ Неверный код. Попробуйте снова.")
            self.auth_state.emit("need_code")
        except Exception as e:
            self.log.emit(f"❌ Ошибка входа по коду: {e}")
            self.auth_state.emit("error")

    def sign_in_with_password(self, password: str):
        if not self._ensure_ready():
            return
        fut = asyncio.run_coroutine_threadsafe(self._sign_in_with_password(password), self._loop)
        fut.add_done_callback(self._silent_callback)

    async def _sign_in_with_password(self, password: str):
        password = password.strip()
        if not password:
            self.log.emit("⚠️ Пароль пуст.")
            return

        try:
            self.log.emit("🔐 Проверяю 2FA пароль…")
            await self._client.sign_in(password=password)
            self.log.emit("✅ Успешная авторизация (2FA пройдена).")
            await self._emit_account_info()
            self.auth_state.emit("authorized")
        except PasswordHashInvalidError:
            self.log.emit("❌ Неверный 2FA пароль. Попробуйте снова.")
            self.auth_state.emit("need_password")
        except Exception as e:
            self.log.emit(f"❌ Ошибка входа по паролю: {e}")
            self.auth_state.emit("error")

    def load_chats(self):
        if not self._ensure_ready():
            return
        fut = asyncio.run_coroutine_threadsafe(self._load_chats(), self._loop)
        fut.add_done_callback(self._silent_callback)

    async def _load_chats(self):
        try:
            if not await self._client.is_user_authorized():
                self.log.emit("⚠️ Сначала авторизуйтесь.")
                self.auth_state.emit("need_phone")
                return

            self.log.emit("📚 Загружаю список чатов…")
            folder_names = {0: "Все чаты"}
            folder_filters = []
            if GetDialogFiltersRequest is not None:
                try:
                    result = await self._client(GetDialogFiltersRequest())
                    filters = getattr(result, "filters", result)
                    for item in filters:
                        folder_id = getattr(item, "id", None)
                        title = getattr(item, "title", None)
                        if folder_id is not None and title:
                            clean_title = strip_emoji_text(title) or f"Папка {folder_id}"
                            folder_names[int(folder_id)] = clean_title
                            folder_filters.append({
                                "id": int(folder_id),
                                "title": clean_title,
                                "filter": item,
                                "explicit_peer_ids": dialog_filter_peer_ids(item),
                                "excluded_peer_ids": dialog_filter_peer_ids(item, ("exclude_peers",)),
                            })
                except Exception:
                    pass
            dialogs = await self._client.get_dialogs(limit=200)

            items: List[ChatItem] = []
            dialog_rows = []
            folder_counts = {folder_id: 0 for folder_id in folder_names}
            for d in dialogs:
                ent = d.entity
                title = d.name or getattr(ent, "title", None) or getattr(ent, "first_name", "") or "Без названия"

                # Универсально получаем peer_id
                peer_id = getattr(ent, "id", None)
                if peer_id is None:
                    continue

                # Примерные флаги
                is_user = ent.__class__.__name__.lower().endswith("user")
                is_channel = ent.__class__.__name__.lower().endswith("channel")
                is_group = ("chat" in ent.__class__.__name__.lower()) or (is_channel and getattr(ent, "megagroup", False))
                is_broadcast = bool(is_channel and not getattr(ent, "megagroup", False))
                is_bot = bool(getattr(ent, "bot", False))
                is_contact = bool(getattr(ent, "contact", False))
                folder_id = int(getattr(d, "folder_id", None) or 0)
                folder_title = folder_names.get(folder_id, f"Папка {folder_id}")
                folder_counts[folder_id] = folder_counts.get(folder_id, 0) + 1

                chat_item = ChatItem(
                    title=str(title),
                    peer_id=int(peer_id),
                    is_user=bool(is_user),
                    is_group=bool(is_group),
                    is_channel=bool(is_channel),
                    folder_id=folder_id,
                    folder_title=folder_title,
                )
                items.append(chat_item)
                dialog_rows.append({
                    "item": chat_item,
                    "dialog": d,
                    "entity": ent,
                    "peer_id": int(peer_id),
                    "is_user": bool(is_user),
                    "is_group": bool(is_group),
                    "is_channel": bool(is_channel),
                    "is_broadcast": bool(is_broadcast),
                    "is_bot": bool(is_bot),
                    "is_contact": bool(is_contact),
                })

            folder_peer_ids = {}
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

            folders_payload = [
                {
                    "id": int(folder_id),
                    "title": str(title),
                    "count": int(folder_counts.get(folder_id, 0)),
                    "peer_ids": folder_peer_ids.get(int(folder_id), []),
                }
                for folder_id, title in sorted(folder_names.items(), key=lambda pair: (pair[0], pair[1]))
            ]
            self.folders_loaded.emit(folders_payload)
            self.chats_loaded.emit(items)
            self.log.emit(f"✅ Чаты загружены: {len(items)}")
        except Exception as e:
            self.log.emit(f"❌ Ошибка загрузки чатов: {e}")

    def load_forum_topics(self, peer_ids: List[int]):
        if not self._ensure_ready():
            return
        fut = asyncio.run_coroutine_threadsafe(self._load_forum_topics(peer_ids), self._loop)
        fut.add_done_callback(self._silent_callback)

    async def _load_forum_topics(self, peer_ids: List[int]):
        items: List[ForumTopicItem] = []
        try:
            if not await self._client.is_user_authorized():
                self.forum_topics_loaded.emit(items)
                return

            unique_peer_ids = []
            seen = set()
            for pid in peer_ids:
                if pid not in seen:
                    seen.add(pid)
                    unique_peer_ids.append(pid)

            for peer_id in unique_peer_ids:
                try:
                    entity = await self._client.get_entity(peer_id)
                    if not bool(getattr(entity, "forum", False)):
                        continue

                    result = await self._client(
                        GetForumTopicsRequest(
                            peer=entity,
                            offset_date=None,
                            offset_id=0,
                            offset_topic=0,
                            limit=100,
                            q=None,
                        )
                    )

                    chat_title = getattr(entity, "title", None) or str(peer_id)
                    for topic in getattr(result, "topics", []):
                        title = getattr(topic, "title", None)
                        top_message = getattr(topic, "top_message", None)
                        topic_id = getattr(topic, "id", None)
                        if title is None or top_message is None or topic_id is None:
                            continue
                        items.append(
                            ForumTopicItem(
                                chat_peer_id=int(peer_id),
                                chat_title=str(chat_title),
                                topic_id=int(topic_id),
                                top_message_id=int(top_message),
                                title=str(title),
                            )
                        )
                except Exception:
                    continue

            self.forum_topics_loaded.emit(items)
        except Exception as e:
            self.log.emit(f"Ошибка загрузки форумных веток: {e}")
            self.forum_topics_loaded.emit(items)

    def start_sending(
        self,
        targets: List[dict],
        message_text: str,
        cooldown_minutes: int,
    ):
        if not self._ensure_ready():
            return
        fut = asyncio.run_coroutine_threadsafe(
            self._start_sending(targets, message_text, cooldown_minutes),
            self._loop,
        )
        fut.add_done_callback(self._silent_callback)

    async def _start_sending(
        self,
        targets: List[dict],
        message_text: str,
        cooldown_minutes: int,
    ):
        if self._sending_task and not self._sending_task.done():
            self.log.emit("Отправка уже запущена.")
            return

        if not await self._client.is_user_authorized():
            self.log.emit("Сначала авторизуйтесь.")
            return

        if not targets:
            self.log.emit("Сначала выберите хотя бы одну цель отправки.")
            return

        msg = message_text.strip()
        if not msg:
            self.log.emit("Текст сообщения пуст.")
            return

        cooldown_minutes = int(cooldown_minutes)
        if cooldown_minutes < 5:
            cooldown_minutes = 5

        per_chat_delay_sec = 3.0
        self._stop_event = asyncio.Event()
        self.sending_state.emit(True)
        self.log.emit(
            f"СТАРТ: автоотправка в {len(targets)} целей, "
            f"задержка {cooldown_minutes} мин."
        )
        try:
            outgoing_text, entities = parse_tg_emoji_html(msg)
            if entities:
                self.log.emit(f"Применены custom-emoji теги: {len(entities)}")
            self._sending_task = asyncio.create_task(
                self._auto_send_loop(
                    targets,
                    outgoing_text,
                    entities,
                    per_chat_delay_sec,
                    cooldown_minutes,
                    self._stop_event,
                )
            )
            await self._sending_task
        except Exception as e:
            self.log.emit(f"Ошибка отправки: {e}")
        finally:
            self._sending_task = None
            self.sending_state.emit(False)
            self.log.emit("СТОП: завершено.")

    async def _auto_send_loop(
        self,
        targets: List[dict],
        outgoing_text: str,
        entities: list,
        per_chat_delay_sec: float,
        cooldown_minutes: int,
        stop_event: asyncio.Event,
    ):
        round_num = 0
        while not stop_event.is_set():
            round_num += 1
            self.log.emit(f"Круг {round_num}: отправка в выбранные цели.")

            total = len(targets)
            for i, target in enumerate(targets, start=1):
                if stop_event.is_set():
                    self.log.emit("Остановлено пользователем.")
                    return

                peer_id = int(target.get("peer_id") or 0)
                topic_id = target.get("topic_id")
                label = target.get("label") or str(target.get("raw_target") or peer_id)

                try:
                    raw_target = target.get("raw_target")
                    if raw_target:
                        entity = await self._client.get_entity(parse_import_target(str(raw_target)))
                    else:
                        entity = await self._client.get_entity(peer_id)
                    if topic_id is not None:
                        input_peer = await self._client.get_input_entity(entity)
                        await self._client(
                            SendMessageRequest(
                                peer=input_peer,
                                message=outgoing_text,
                                reply_to=InputReplyToMessage(
                                    reply_to_msg_id=int(topic_id),
                                    top_msg_id=int(topic_id),
                                ),
                                entities=entities or None,
                            )
                        )
                    else:
                        await self._client.send_message(
                            entity,
                            outgoing_text,
                            formatting_entities=entities or None,
                        )
                    self.log.emit(
                        f"[{i}/{total}] Отправлено в {label}: "
                        + outgoing_text[:80]
                        + ("..." if len(outgoing_text) > 80 else "")
                    )
                except FloodWaitError as e:
                    wait_s = max(int(getattr(e, "seconds", 0)) or 0, int(per_chat_delay_sec))
                    self.log.emit(f"[{i}/{total}] FloodWait для {label}: ждать {wait_s} сек.")
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=wait_s)
                        self.log.emit("Скрипт остановлен пользователем.")
                        return
                    except asyncio.TimeoutError:
                        continue
                except Exception as e:
                    self.log.emit(f"[{i}/{total}] Ошибка отправки для {label}: {e}")

                if i < total:
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=per_chat_delay_sec)
                        self.log.emit("Скрипт остановлен пользователем.")
                        return
                    except asyncio.TimeoutError:
                        pass

            cooldown_seconds = cooldown_minutes * 60
            self.log.emit(f"Жду {cooldown_minutes} минут для следующей отправки.")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=cooldown_seconds)
                self.log.emit("Скрипт остановлен пользователем.")
                return
            except asyncio.TimeoutError:
                pass

    def stop_sending(self):
        if not self._ensure_ready():
            return
        fut = asyncio.run_coroutine_threadsafe(self._stop_sending(), self._loop)
        fut.add_done_callback(self._silent_callback)

    async def _stop_sending(self):
        if self._stop_event:
            self._stop_event.set()
        if self._sending_task:
            try:
                await asyncio.wait_for(self._sending_task, timeout=5)
            except Exception:
                pass

    async def _emit_account_info(self):
        try:
            me = await self._client.get_me()
            if not me:
                return
            first = getattr(me, "first_name", None) or ""
            last = getattr(me, "last_name", None) or ""
            name = (f"{first} {last}").strip() or getattr(me, "username", None) or str(getattr(me, "id", "Аккаунт"))
            username = getattr(me, "username", None) or ""
            photo_bytes = None
            try:
                photo_bytes = await self._client.download_profile_photo(me, file=bytes)
            except Exception:
                photo_bytes = None
            self.account_info.emit({
                "name": name,
                "username": username,
                "phone": getattr(me, "phone", "") or "",
                "photo": photo_bytes or b"",
            })
        except Exception as exc:
            self.log.emit(f"Не удалось загрузить профиль аккаунта: {exc}")

    def shutdown(self):
        """
        Корректно останавливаем event loop.
        """
        if not self._loop:
            return
        fut = asyncio.run_coroutine_threadsafe(self._shutdown_async(), self._loop)
        fut.add_done_callback(self._silent_callback)

    async def _shutdown_async(self):
        try:
            if self._qr_wait_task and not self._qr_wait_task.done():
                self._qr_wait_task.cancel()
                try:
                    await self._qr_wait_task
                except Exception:
                    pass
            await self._stop_sending()
        finally:
            self.log.emit("👋 Завершение работы…")
            self._loop.call_soon_threadsafe(self._loop.stop)

    @staticmethod
    def _silent_callback(_fut):
        # Ничего не делаем: ошибки логируются внутри корутин
        pass


# -----------------------------
# GUI
# -----------------------------
class NeonMainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1150, 720)
        self.api_id, self.api_hash = self._load_api_credentials()

        if self.api_id == 0 or not self.api_hash:
            QtWidgets.QMessageBox.critical(
                self, "API_ID / API_HASH не заданы",
                "Откройте настройки API и заполните API_ID и API_HASH.\n"
                "Telegram API можно получить на my.telegram.org"
            )
            # не выходим насильно — пусть пользователь увидит интерфейс, но функционал будет ограничен

        # --- Worker thread ---
        session_path = os.path.join(runtime_base_dir(), DEFAULT_SESSION_NAME)

        self.worker = TelethonWorker(self.api_id, self.api_hash, session_path)
        self.thread = QtCore.QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.start)

        self.worker.log.connect(self.append_log)
        self.worker.auth_state.connect(self.on_auth_state)
        self.worker.qr_login_ready.connect(self.on_qr_login_ready)
        self.worker.account_info.connect(self.on_account_info)
        self.worker.folders_loaded.connect(self.on_folders_loaded)
        self.worker.chats_loaded.connect(self.on_chats_loaded)
        self.worker.forum_topics_loaded.connect(self.on_forum_topics_loaded)
        self.worker.sending_state.connect(self.on_sending_state)

        # --- UI build ---
        central = QtWidgets.QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        # Left panel: auth + chats
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(12)

        self.auth_group = self._build_auth_group()
        left.addWidget(self.auth_group)

        self.account_group = self._build_account_group()
        left.addWidget(self.account_group)

        self.chats_group = self._build_chats_group()
        left.addWidget(self.chats_group, 1)

        # Right panel: forum topics + sender + logs
        right = QtWidgets.QVBoxLayout()
        right.setSpacing(12)

        self.forums_group = self._build_forums_group()
        right.addWidget(self.forums_group, 1)

        self.sender_group = self._build_sender_group()
        right.addWidget(self.sender_group, 1)

        self.log_group = self._build_log_group()
        right.addWidget(self.log_group, 1)

        root.addLayout(left, 1)
        root.addLayout(right, 2)

        self._apply_neon_theme()

        # initial state
        self._set_auth_inputs(phone=True, code=False, password=False)
        self.btn_load_chats.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(False)

        self._chat_items: List[ChatItem] = []
        self._visible_chat_items: List[ChatItem] = []
        self._forum_topic_items: List[ForumTopicItem] = []
        self._telegram_folders: List[dict] = []
        self._folder_peer_ids: dict = {}
        self._imported_targets: List[str] = []
        self._profiles: dict = self._load_profiles()
        self._qr_dialog: Optional[QtWidgets.QDialog] = None
        self._qr_code_label: Optional[QtWidgets.QLabel] = None
        self._qr_url_edit: Optional[QtWidgets.QLineEdit] = None
        self._qr_countdown_label: Optional[QtWidgets.QLabel] = None
        self._qr_expires_ts: int = 0
        self._qr_timer = QtCore.QTimer(self)
        self._qr_timer.setInterval(1000)
        self._qr_timer.timeout.connect(self._update_qr_countdown)
        self._refresh_api_status()
        self._refresh_profiles_combo()
        self._set_account_status(False)
        self.thread.start()


    # --- UI sections ---
    def _load_json_file(self, path: str, default):
        try:
            if not os.path.exists(path):
                return default
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception:
            return default

    def _write_json_file(self, path: str, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_api_credentials(self):
        data = self._load_json_file(config_path(API_CONFIG_FILE), {})
        api_id = int(data.get("api_id") or API_ID or 0)
        api_hash = str(data.get("api_hash") or API_HASH or "").strip()
        return api_id, api_hash

    def _save_api_credentials(self, api_id: int, api_hash: str):
        self._write_json_file(config_path(API_CONFIG_FILE), {
            "api_id": int(api_id),
            "api_hash": api_hash.strip(),
        })

    def _load_profiles(self) -> dict:
        data = self._load_json_file(config_path(PROFILES_FILE), {})
        return data if isinstance(data, dict) else {}

    def _save_profiles(self):
        self._write_json_file(config_path(PROFILES_FILE), self._profiles)

    def _refresh_api_status(self):
        if hasattr(self, "lbl_api_status"):
            suffix = str(self.api_id)[-4:] if self.api_id else "----"
            self.lbl_api_status.setText(f"Telegram API: ID *{suffix}")

    def _refresh_profiles_combo(self):
        if not hasattr(self, "combo_profiles"):
            return
        current = self.combo_profiles.currentText().strip()
        self.combo_profiles.blockSignals(True)
        self.combo_profiles.clear()
        self.combo_profiles.addItems(sorted(self._profiles.keys()))
        if current:
            idx = self.combo_profiles.findText(current)
            if idx >= 0:
                self.combo_profiles.setCurrentIndex(idx)
        self.combo_profiles.blockSignals(False)

    def _set_account_status(self, online: bool):
        color = "#39FF9A" if online else "#FF4D7D"
        if hasattr(self, "account_status_dot"):
            self.account_status_dot.setStyleSheet(f"background: {color}; border-radius: 5px;")
        if hasattr(self, "lbl_account_meta"):
            self.lbl_account_meta.setText("Статус: онлайн" if online else "Статус: офлайн")

    def _render_avatar(self, name: str, photo: bytes):
        if not hasattr(self, "lbl_account_avatar"):
            return
        if photo:
            pixmap = QtGui.QPixmap()
            if pixmap.loadFromData(photo):
                size = 44
                scaled = pixmap.scaled(size, size, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
                x = max((scaled.width() - size) // 2, 0)
                y = max((scaled.height() - size) // 2, 0)
                cropped = scaled.copy(x, y, size, size)

                rounded = QtGui.QPixmap(size, size)
                rounded.fill(QtCore.Qt.transparent)
                painter = QtGui.QPainter(rounded)
                painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
                path = QtGui.QPainterPath()
                path.addEllipse(0, 0, size, size)
                painter.setClipPath(path)
                painter.drawPixmap(0, 0, cropped)
                painter.end()

                self.lbl_account_avatar.setPixmap(rounded)
                self.lbl_account_avatar.setText("")
                return
        initial = (name or "A").strip()[:1].upper()
        self.lbl_account_avatar.setPixmap(QtGui.QPixmap())
        self.lbl_account_avatar.setText(initial)

    def _current_folder_id(self) -> Optional[int]:
        item = self.list_folders.currentItem() if hasattr(self, "list_folders") else None
        if not item:
            return None
        return item.data(QtCore.Qt.UserRole)

    def _render_folders(self):
        self.list_folders.blockSignals(True)
        self.list_folders.clear()
        all_item = QtWidgets.QListWidgetItem(f"Все чаты ({len(self._chat_items)})")
        all_item.setData(QtCore.Qt.UserRole, None)
        self.list_folders.addItem(all_item)

        if self._telegram_folders:
            folders = self._telegram_folders
        else:
            folder_map = {}
            for chat in self._chat_items:
                folder_map.setdefault(chat.folder_id, {"id": chat.folder_id, "title": chat.folder_title, "count": 0})
                folder_map[chat.folder_id]["count"] += 1
            folders = list(folder_map.values())

        for folder in folders:
            folder_id = int(folder.get("id") or 0)
            if folder_id == 0:
                continue
            title = strip_emoji_text(folder.get("title") or f"Папка {folder_id}") or f"Папка {folder_id}"
            count = int(folder.get("count") or 0)
            item = QtWidgets.QListWidgetItem(f"{title} ({count})")
            item.setData(QtCore.Qt.UserRole, int(folder_id))
            self.list_folders.addItem(item)
        self.list_folders.setCurrentRow(0)
        self.list_folders.blockSignals(False)

    def _render_chats_for_folder(self, folder_id: Optional[int] = None):
        if folder_id is None:
            self._visible_chat_items = list(self._chat_items)
        elif folder_id in self._folder_peer_ids:
            peer_ids = set(self._folder_peer_ids.get(folder_id) or [])
            self._visible_chat_items = [
                chat for chat in self._chat_items
                if int(chat.peer_id) in peer_ids
            ]
        else:
            self._visible_chat_items = [
                chat for chat in self._chat_items
                if chat.folder_id == folder_id
            ]
        self.list_chats.blockSignals(True)
        self.list_chats.clear()
        for chat in self._visible_chat_items:
            badge = "👤 |" if chat.is_user else ("👥 |" if chat.is_group else "📢 |")
            item = QtWidgets.QListWidgetItem(f"{badge} {chat.title}  (ID: {chat.peer_id})")
            item.setData(QtCore.Qt.UserRole, int(chat.peer_id))
            self.list_chats.addItem(item)
        self.list_chats.blockSignals(False)

    def _render_imported_targets(self, select_all: bool = True):
        self.list_imported_targets.blockSignals(True)
        self.list_imported_targets.clear()
        for raw in self._imported_targets:
            item = QtWidgets.QListWidgetItem(str(raw))
            item.setData(QtCore.Qt.UserRole, str(raw))
            self.list_imported_targets.addItem(item)
            item.setSelected(select_all)
        self.list_imported_targets.blockSignals(False)

    def _sync_start_button(self):
        is_sending = self.btn_stop.isEnabled()
        has_chat_selection = len(self.list_chats.selectedItems()) > 0
        has_topic_selection = len(self.list_forum_topics.selectedItems()) > 0
        has_import_selection = len(self.list_imported_targets.selectedItems()) > 0
        self.btn_start.setEnabled((not is_sending) and (has_chat_selection or has_topic_selection or has_import_selection))

    def _build_auth_group(self) -> QtWidgets.QGroupBox:
        g = QtWidgets.QGroupBox("Авторизация")
        lay = QtWidgets.QGridLayout(g)
        lay.setHorizontalSpacing(10)
        lay.setVerticalSpacing(10)

        self.lbl_api_status = QtWidgets.QLabel()
        self.lbl_api_status.setObjectName("hintLabel")
        self.btn_api_settings = QtWidgets.QPushButton("API настройки")
        self.btn_api_settings.clicked.connect(self.ui_api_settings)

        self.in_phone = QtWidgets.QLineEdit()
        self.in_phone.setPlaceholderText("В формате страны + и без пробелов")
        self.in_code = QtWidgets.QLineEdit()
        self.in_code.setPlaceholderText("Код из Telegram")
        self.in_code.setMaxLength(10)

        self.in_password = QtWidgets.QLineEdit()
        self.in_password.setPlaceholderText("Пароль 2FA (если включен)")
        self.in_password.setEchoMode(QtWidgets.QLineEdit.Password)

        self.btn_send_code = QtWidgets.QPushButton("Отправить код")
        self.btn_sign_in = QtWidgets.QPushButton("Вход")
        self.btn_sign_in_2fa = QtWidgets.QPushButton("Вход (2FA)")
        self.btn_qr_login = QtWidgets.QPushButton("Вход по QR")
        self.btn_load_chats = QtWidgets.QPushButton("Загрузить чаты")

        self.btn_send_code.clicked.connect(self.ui_send_code)
        self.btn_sign_in.clicked.connect(self.ui_sign_in_code)
        self.btn_sign_in_2fa.clicked.connect(self.ui_sign_in_password)
        self.btn_qr_login.clicked.connect(self.ui_request_qr_login)
        self.btn_load_chats.clicked.connect(self.ui_load_chats)

        lay.addWidget(self.lbl_api_status, 0, 0, 1, 3)
        lay.addWidget(self.btn_api_settings, 0, 3)

        lay.addWidget(QtWidgets.QLabel("Телефон:"), 1, 0)
        lay.addWidget(self.in_phone, 1, 1, 1, 3)

        lay.addWidget(QtWidgets.QLabel("Код:"), 2, 0)
        lay.addWidget(self.in_code, 2, 1)
        lay.addWidget(self.btn_send_code, 2, 2)
        lay.addWidget(self.btn_sign_in, 2, 3)

        lay.addWidget(QtWidgets.QLabel("2FA пароль:"), 3, 0)
        lay.addWidget(self.in_password, 3, 1)
        lay.addWidget(self.btn_sign_in_2fa, 3, 2, 1, 2)

        lay.addWidget(self.btn_load_chats, 4, 0, 1, 4)
        lay.addWidget(self.btn_qr_login, 5, 0, 1, 4)

        return g

    def _build_account_group(self) -> QtWidgets.QGroupBox:
        g = QtWidgets.QGroupBox("Аккаунт")
        lay = QtWidgets.QHBoxLayout(g)
        lay.setContentsMargins(12, 14, 12, 12)
        lay.setSpacing(10)

        self.lbl_account_avatar = QtWidgets.QLabel("A")
        self.lbl_account_avatar.setObjectName("accountAvatar")
        self.lbl_account_avatar.setAlignment(QtCore.Qt.AlignCenter)
        self.lbl_account_avatar.setFixedSize(44, 44)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setSpacing(2)

        name_row = QtWidgets.QHBoxLayout()
        name_row.setSpacing(7)
        self.account_status_dot = QtWidgets.QFrame()
        self.account_status_dot.setFixedSize(10, 10)
        self.lbl_account_name = QtWidgets.QLabel("Не авторизован")
        self.lbl_account_name.setObjectName("accountName")
        name_row.addWidget(self.account_status_dot)
        name_row.addWidget(self.lbl_account_name, 1)

        self.lbl_account_meta = QtWidgets.QLabel("Статус: офлайн")
        self.lbl_account_meta.setObjectName("hintLabel")
        text_col.addLayout(name_row)
        text_col.addWidget(self.lbl_account_meta)

        lay.addWidget(self.lbl_account_avatar)
        lay.addLayout(text_col, 1)
        return g

    def _build_chats_group(self) -> QtWidgets.QGroupBox:
        g = QtWidgets.QGroupBox("Чаты")
        lay = QtWidgets.QVBoxLayout(g)
        lay.setSpacing(10)

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(8)
        self.btn_import_chats = QtWidgets.QPushButton("Импорт из файла")
        self.btn_select_folder = QtWidgets.QPushButton("Выбрать папку")
        self.btn_clear_import = QtWidgets.QPushButton("Очистить импорт")
        self.btn_import_chats.clicked.connect(self.ui_import_chats)
        self.btn_select_folder.clicked.connect(self.ui_select_folder_chats)
        self.btn_clear_import.clicked.connect(self.ui_clear_imported_targets)
        controls.addWidget(self.btn_import_chats)
        controls.addWidget(self.btn_select_folder)
        controls.addWidget(self.btn_clear_import)

        self.lbl_loading_chats = QtWidgets.QLabel("Готов к загрузке чатов")
        self.lbl_loading_chats.setObjectName("hintLabel")
        self.progress_chats = QtWidgets.QProgressBar()
        self.progress_chats.setRange(0, 0)
        self.progress_chats.setTextVisible(False)
        self.progress_chats.setVisible(False)

        self.list_folders = QtWidgets.QListWidget()
        self.list_folders.setObjectName("foldersList")
        self.list_folders.setMinimumHeight(165)
        self.list_folders.setMaximumHeight(220)
        self.list_folders.itemSelectionChanged.connect(self.ui_folder_selected)

        self.list_chats = QtWidgets.QListWidget()
        self.list_chats.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list_chats.itemSelectionChanged.connect(self.ui_chat_selected)

        self.list_imported_targets = QtWidgets.QListWidget()
        self.list_imported_targets.setObjectName("importedTargetsList")
        self.list_imported_targets.setMaximumHeight(90)
        self.list_imported_targets.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list_imported_targets.itemSelectionChanged.connect(self.ui_chat_selected)

        lay.addLayout(controls)
        lay.addWidget(self.lbl_loading_chats)
        lay.addWidget(self.progress_chats)
        lay.addWidget(self.list_folders)
        lay.addWidget(self.list_chats)
        lay.addWidget(QtWidgets.QLabel("Импортированные цели:"))
        lay.addWidget(self.list_imported_targets)
        return g

    def _build_forums_group(self) -> QtWidgets.QGroupBox:
        g = QtWidgets.QGroupBox("Форумные чаты")
        lay = QtWidgets.QVBoxLayout(g)
        lay.setSpacing(10)

        self.list_forum_topics = QtWidgets.QListWidget()
        self.list_forum_topics.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.list_forum_topics.itemSelectionChanged.connect(self.ui_forum_topic_selected)

        lay.addWidget(self.list_forum_topics)
        return g

    def _build_sender_group(self) -> QtWidgets.QGroupBox:
        g = QtWidgets.QGroupBox("Пост-бот")
        lay = QtWidgets.QGridLayout(g)
        lay.setHorizontalSpacing(10)
        lay.setVerticalSpacing(10)

        self.txt_messages = QtWidgets.QPlainTextEdit()
        self.txt_messages.setPlaceholderText("Вставьте один текст для отправки.")

        self.spin_cooldown = QtWidgets.QSpinBox()
        self.spin_cooldown.setRange(5, 1440)
        self.spin_cooldown.setValue(5)
        self.spin_cooldown.setSuffix(" минут")

        self.btn_start = QtWidgets.QPushButton("СТАРТ")
        self.btn_stop = QtWidgets.QPushButton("СТОП")
        self.btn_start.clicked.connect(self.ui_start_sending)
        self.btn_stop.clicked.connect(self.ui_stop_sending)

        lay.addWidget(QtWidgets.QLabel("Текст постинга:"), 0, 0)
        lay.addWidget(self.txt_messages, 1, 0, 1, 4)
        lay.addWidget(QtWidgets.QLabel("КД минут:"), 2, 0)
        lay.addWidget(self.spin_cooldown, 2, 1)
        lay.addWidget(self.btn_start, 3, 2)
        lay.addWidget(self.btn_stop, 3, 3)

        note = QtWidgets.QLabel(
            "Пост-бот с отправкой HTML. Между чатами 3 секунды. Цикл не меньше периодичности (минимум 5 минут)."
        )
        note.setWordWrap(True)
        note.setObjectName("hintLabel")
        lay.addWidget(note, 4, 0, 1, 4)

        return g

    def _build_log_group(self) -> QtWidgets.QGroupBox:
        g = QtWidgets.QGroupBox("Логи")
        lay = QtWidgets.QVBoxLayout(g)
        lay.setSpacing(10)

        self.txt_log = QtWidgets.QPlainTextEdit()
        self.txt_log.setReadOnly(True)

        lay.addWidget(self.txt_log)
        return g

    def _apply_neon_theme(self):
        # Softer neon look with cleaner lists and scrollbars.
        self.setStyleSheet("""
            QWidget {
                color: #EAF1FF;
                font-family: Segoe UI, Arial, sans-serif;
                font-size: 13px;
            }

            QMainWindow, QWidget#centralWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #06040F, stop:0.55 #120B31, stop:1 #24106E);
            }

            QGroupBox {
                border: 1px solid rgba(82, 39, 255, 130);
                border-radius: 16px;
                margin-top: 10px;
                padding: 12px;
                background-color: rgba(9, 6, 28, 220);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                color: #FF9FFC;
                font-weight: 700;
                letter-spacing: 0.2px;
            }

            QLineEdit, QPlainTextEdit, QListWidget, QComboBox, QDoubleSpinBox, QSpinBox {
                background-color: rgba(5, 4, 18, 235);
                border: 1px solid rgba(82, 39, 255, 150);
                border-radius: 12px;
                padding: 10px;
                selection-background-color: rgba(82, 39, 255, 150);
                selection-color: #F6FAFF;
            }
            QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {
                border: 1px solid rgba(255, 159, 252, 230);
            }

            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 #5227FF,
                                            stop:1 #FF9FFC);
                border: none;
                border-radius: 14px;
                padding: 10px 14px;
                font-weight: 700;
                color: #100A24;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 #6A45FF,
                                            stop:1 #FFB7FD);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 #421FD6,
                                            stop:1 #E884E6);
            }
            QPushButton:disabled {
                background: rgba(52, 35, 90, 150);
                color: rgba(230, 220, 245, 120);
            }

            QMenuBar {
                background: rgba(12, 8, 38, 230);
                color: #EAF1FF;
                border: 1px solid rgba(255, 159, 252, 90);
                border-radius: 10px;
                padding: 4px 6px;
            }
            QMenuBar::item {
                background: transparent;
                color: #EAF1FF;
                padding: 6px 10px;
                border-radius: 8px;
            }
            QMenuBar::item:selected {
                background: rgba(82, 39, 255, 165);
            }
            QMenu {
                background: rgba(16, 9, 48, 245);
                color: #EAF1FF;
                border: 1px solid rgba(255, 159, 252, 125);
                border-radius: 8px;
                padding: 6px;
            }
            QMenu::item {
                padding: 7px 12px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background: rgba(82, 39, 255, 180);
            }

            QLabel#hintLabel {
                color: rgba(255, 220, 254, 180);
            }

            QLabel#accountAvatar {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #5227FF,
                                            stop:1 #FF9FFC);
                border: 1px solid rgba(255, 255, 255, 55);
                border-radius: 22px;
                color: #FFFFFF;
                font-size: 18px;
                font-weight: 900;
            }
            QLabel#accountName {
                color: #FFFFFF;
                font-size: 14px;
                font-weight: 800;
            }

            QProgressBar {
                min-height: 8px;
                max-height: 8px;
                border: none;
                border-radius: 4px;
                background: rgba(255, 255, 255, 35);
            }
            QProgressBar::chunk {
                border-radius: 4px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 #5227FF,
                                            stop:1 #FF9FFC);
            }

            QListWidget {
                padding: 8px;
            }
            QListWidget#foldersList, QListWidget#importedTargetsList {
                background: rgba(4, 3, 15, 210);
                border-color: rgba(255, 159, 252, 105);
            }
            QListWidget#foldersList::item {
                margin: 5px 0;
                padding: 15px 14px;
                font-size: 14px;
                font-weight: 700;
            }
            QListWidget::item {
                margin: 3px 0;
                padding: 11px 12px;
                border-radius: 10px;
                border: 1px solid rgba(82, 39, 255, 115);
                background: rgba(11, 7, 34, 200);
            }
            QListWidget::item:selected {
                border: 1px solid rgba(255, 159, 252, 230);
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 rgba(82, 39, 255, 190),
                                            stop:1 rgba(255, 159, 252, 145));
                color: #F4F8FF;
            }
            QListWidget::item:hover:!selected {
                background: rgba(82, 39, 255, 105);
            }

            QScrollBar:vertical {
                background: rgba(5, 4, 18, 210);
                width: 12px;
                margin: 8px 3px 8px 3px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                min-height: 28px;
                border-radius: 6px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #FF9FFC,
                                            stop:1 #5227FF);
            }
            QScrollBar::handle:vertical:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #FFB7FD,
                                            stop:1 #6A45FF);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                background: rgba(5, 4, 18, 210);
                height: 12px;
                margin: 3px 8px 3px 8px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                min-width: 28px;
                border-radius: 6px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 #FF9FFC,
                                            stop:1 #5227FF);
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)

    # --- Auth UI state helpers ---
    def _set_auth_inputs(self, phone: bool, code: bool, password: bool):
        self.in_phone.setEnabled(phone)
        self.btn_send_code.setEnabled(phone)
        self.btn_qr_login.setEnabled(phone or code)

        self.in_code.setEnabled(code)
        self.btn_sign_in.setEnabled(code)

        self.in_password.setEnabled(password)
        self.btn_sign_in_2fa.setEnabled(password)

    def _build_qr_dialog(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Вход по QR")
        dlg.setModal(False)
        dlg.resize(460, 560)
        dlg.setObjectName("qrDialog")

        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(12)

        hint = QtWidgets.QLabel(
            "Откройте Telegram на телефоне: Настройки -> Устройства -> Подключить устройство, затем сканируйте QR."
        )
        hint.setWordWrap(True)
        hint.setObjectName("qrHint")

        qr_frame = QtWidgets.QFrame()
        qr_frame.setObjectName("qrFrame")
        qr_lay = QtWidgets.QVBoxLayout(qr_frame)
        qr_lay.setContentsMargins(16, 16, 16, 16)

        self._qr_code_label = QtWidgets.QLabel()
        self._qr_code_label.setObjectName("qrCodeLabel")
        self._qr_code_label.setAlignment(QtCore.Qt.AlignCenter)
        self._qr_code_label.setFixedSize(332, 332)
        qr_lay.addWidget(self._qr_code_label, 0, QtCore.Qt.AlignCenter)

        self._qr_countdown_label = QtWidgets.QLabel("Действует: --")
        self._qr_countdown_label.setObjectName("qrCountdown")
        self._qr_countdown_label.setAlignment(QtCore.Qt.AlignCenter)

        self._qr_url_edit = QtWidgets.QLineEdit()
        self._qr_url_edit.setObjectName("qrUrl")
        self._qr_url_edit.setReadOnly(True)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(8)
        btn_copy = QtWidgets.QPushButton("Копировать ссылку")
        btn_open = QtWidgets.QPushButton("Открыть ссылку")
        btn_refresh = QtWidgets.QPushButton("Обновить QR")
        btn_close = QtWidgets.QPushButton("Закрыть")
        for btn in (btn_copy, btn_open, btn_refresh, btn_close):
            btn.setMinimumHeight(38)
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_open)
        btn_row.addWidget(btn_refresh)
        btn_row.addWidget(btn_close)

        btn_copy.clicked.connect(
            lambda: QtWidgets.QApplication.clipboard().setText(self._qr_url_edit.text().strip())
        )
        btn_open.clicked.connect(
            lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(self._qr_url_edit.text().strip()))
        )
        btn_refresh.clicked.connect(self.ui_request_qr_login)
        btn_close.clicked.connect(dlg.close)

        lay.addWidget(hint)
        lay.addWidget(qr_frame, 0, QtCore.Qt.AlignCenter)
        lay.addWidget(self._qr_countdown_label)
        lay.addWidget(self._qr_url_edit)
        lay.addLayout(btn_row)

        dlg.setStyleSheet("""
            QDialog#qrDialog {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #06040F, stop:0.55 #120B31, stop:1 #24106E);
                color: #EAF1FF;
                font-family: Segoe UI, Arial, sans-serif;
                font-size: 13px;
            }
            QLabel#qrHint {
                color: rgba(255, 220, 254, 220);
                font-weight: 600;
                padding: 4px 2px;
            }
            QFrame#qrFrame {
                background: rgba(245, 248, 255, 245);
                border: 1px solid rgba(255, 159, 252, 180);
                border-radius: 8px;
            }
            QLabel#qrCodeLabel {
                background: #FFFFFF;
                border-radius: 4px;
            }
            QLabel#qrCountdown {
                color: #FF9FFC;
                font-weight: 700;
                padding: 2px;
            }
            QLineEdit#qrUrl {
                background-color: rgba(5, 4, 18, 240);
                border: 1px solid rgba(82, 39, 255, 165);
                border-radius: 8px;
                padding: 10px;
                color: #EAF1FF;
                selection-background-color: rgba(82, 39, 255, 150);
            }
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 #5227FF,
                                            stop:1 #FF9FFC);
                border: none;
                border-radius: 8px;
                padding: 8px 10px;
                font-weight: 700;
                color: #100A24;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 #6A45FF,
                                            stop:1 #FFB7FD);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 #421FD6,
                                            stop:1 #E884E6);
            }
        """)

        self._qr_dialog = dlg

    def _make_qr_pixmap(self, qr_url: str):
        try:
            import qrcode
            qr = qrcode.QRCode(border=2, box_size=8)
            qr.add_data(qr_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            raw = buf.getvalue()
        except Exception:
            try:
                api_url = (
                    "https://api.qrserver.com/v1/create-qr-code/?size=360x360&data="
                    + urllib.parse.quote(qr_url, safe="")
                )
                with urllib.request.urlopen(api_url, timeout=8) as resp:
                    raw = resp.read()
            except Exception:
                return None

        pixmap = QtGui.QPixmap()
        if not pixmap.loadFromData(raw, "PNG"):
            return None
        return pixmap.scaled(300, 300, QtCore.Qt.KeepAspectRatio, QtCore.Qt.FastTransformation)

    def _update_qr_countdown(self):
        if not self._qr_countdown_label:
            return
        if not self._qr_expires_ts:
            self._qr_countdown_label.setText("Действует: --")
            return
        left = max(self._qr_expires_ts - int(QtCore.QDateTime.currentSecsSinceEpoch()), 0)
        self._qr_countdown_label.setText(f"Действует: {left} сек")
        if left <= 0:
            self._qr_timer.stop()

    @QtCore.pyqtSlot(str, int)
    def on_qr_login_ready(self, qr_url: str, expires_ts: int):
        if not self._qr_dialog:
            self._build_qr_dialog()

        self._qr_expires_ts = int(expires_ts or 0)
        self._qr_url_edit.setText(qr_url)

        pixmap = self._make_qr_pixmap(qr_url)
        if pixmap is not None:
            self._qr_code_label.setPixmap(pixmap)
            self._qr_code_label.setText("")
        else:
            self._qr_code_label.setPixmap(QtGui.QPixmap())
            self._qr_code_label.setText("Не удалось отрисовать QR. Используйте ссылку ниже.")

        self._update_qr_countdown()
        self._qr_timer.start()
        self._qr_dialog.show()
        self._qr_dialog.raise_()
        self._qr_dialog.activateWindow()

    # --- Slots: worker -> GUI ---
    @QtCore.pyqtSlot(str)
    def append_log(self, text: str):
        self.txt_log.appendPlainText(text)
        self.txt_log.verticalScrollBar().setValue(self.txt_log.verticalScrollBar().maximum())

    def ui_api_settings(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setObjectName("apiDialog")
        dlg.setWindowTitle("Telegram API")
        dlg.setModal(True)
        dlg.resize(430, 210)

        lay = QtWidgets.QVBoxLayout(dlg)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(12)

        title = QtWidgets.QLabel("API ID и API HASH")
        title.setObjectName("accountName")
        hint = QtWidgets.QLabel("Данные берутся на my.telegram.org. После сохранения лучше перезапустить приложение.")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)

        form = QtWidgets.QFormLayout()
        form.setSpacing(10)
        api_id_edit = QtWidgets.QLineEdit(str(self.api_id or ""))
        api_id_edit.setPlaceholderText("Например: 12345678")
        api_hash_edit = QtWidgets.QLineEdit(self.api_hash or "")
        api_hash_edit.setPlaceholderText("API HASH")
        api_hash_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        form.addRow("API ID:", api_id_edit)
        form.addRow("API HASH:", api_hash_edit)

        buttons = QtWidgets.QHBoxLayout()
        btn_save = QtWidgets.QPushButton("Сохранить")
        btn_cancel = QtWidgets.QPushButton("Отмена")
        buttons.addStretch(1)
        buttons.addWidget(btn_save)
        buttons.addWidget(btn_cancel)

        def save_and_close():
            raw_id = api_id_edit.text().strip()
            raw_hash = api_hash_edit.text().strip()
            try:
                new_api_id = int(raw_id)
            except ValueError:
                QtWidgets.QMessageBox.warning(dlg, "Ошибка", "API ID должен быть числом.")
                return
            if new_api_id <= 0 or not raw_hash:
                QtWidgets.QMessageBox.warning(dlg, "Ошибка", "Заполните API ID и API HASH.")
                return

            self.api_id = new_api_id
            self.api_hash = raw_hash
            self._save_api_credentials(new_api_id, raw_hash)
            self._refresh_api_status()
            self.append_log("API настройки сохранены. Если клиент уже запущен, перезапустите приложение.")
            dlg.accept()

        btn_save.clicked.connect(save_and_close)
        btn_cancel.clicked.connect(dlg.reject)

        lay.addWidget(title)
        lay.addWidget(hint)
        lay.addLayout(form)
        lay.addLayout(buttons)
        dlg.setStyleSheet(self.styleSheet() + """
            QDialog#apiDialog {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #06040F,
                                            stop:0.55 #120B31,
                                            stop:1 #24106E);
            }
            QDialog#apiDialog QLabel {
                color: #EAF1FF;
                background: transparent;
            }
            QDialog#apiDialog QLabel#hintLabel {
                color: rgba(255, 220, 254, 205);
            }
            QDialog#apiDialog QLabel#accountName {
                color: #FFFFFF;
                font-size: 15px;
                font-weight: 900;
            }
            QDialog#apiDialog QLineEdit {
                background-color: rgba(5, 4, 18, 245);
                border: 1px solid rgba(255, 159, 252, 190);
                border-radius: 12px;
                color: #F8FBFF;
                padding: 10px;
            }
            QDialog#apiDialog QPushButton {
                min-width: 90px;
            }
        """)
        dlg.exec_()

    @QtCore.pyqtSlot(str)
    def on_auth_state(self, state: str):
        if state == "need_phone":
            self._set_account_status(False)
            self._set_auth_inputs(phone=True, code=False, password=False)
            self.btn_load_chats.setEnabled(False)
        elif state == "need_code":
            self._set_auth_inputs(phone=True, code=True, password=False)
            self.btn_load_chats.setEnabled(False)
        elif state == "need_password":
            self._set_auth_inputs(phone=False, code=False, password=True)
            self.btn_load_chats.setEnabled(False)
        elif state == "authorized":
            self._set_account_status(True)
            self._set_auth_inputs(phone=False, code=False, password=False)
            self.btn_load_chats.setEnabled(True)
            self._qr_timer.stop()
            if self._qr_dialog:
                self._qr_dialog.close()
        elif state == "error":
            self._set_account_status(False)
            # дадим пользователю попробовать снова
            self._set_auth_inputs(phone=True, code=True, password=True)
            self.btn_load_chats.setEnabled(False)

    @QtCore.pyqtSlot(dict)
    def on_account_info(self, info: dict):
        name = str(info.get("name") or "Аккаунт").strip()
        username = str(info.get("username") or "").strip()
        phone = str(info.get("phone") or "").strip()
        display_name = f"{name} @{username}" if username else name
        self._set_account_status(True)
        self.lbl_account_name.setText(display_name)
        meta = "Статус: онлайн"
        if phone:
            meta += f" | +{phone.lstrip('+')}"
        self.lbl_account_meta.setText(meta)
        self._render_avatar(name, info.get("photo") or b"")

    @QtCore.pyqtSlot(list)
    def on_folders_loaded(self, folders: list):
        self._telegram_folders = [
            {
                "id": int(folder.get("id") or 0),
                "title": strip_emoji_text(folder.get("title") or "") or "Папка",
                "count": int(folder.get("count") or 0),
                "peer_ids": [
                    int(peer_id)
                    for peer_id in (folder.get("peer_ids") or [])
                    if str(peer_id).lstrip("-").isdigit()
                ],
            }
            for folder in folders
            if isinstance(folder, dict)
        ]
        self._folder_peer_ids = {
            int(folder["id"]): set(folder.get("peer_ids") or [])
            for folder in self._telegram_folders
        }
        self._render_folders()

    @QtCore.pyqtSlot(list)
    def on_chats_loaded(self, items: list):
        self._chat_items = list(items)
        self._visible_chat_items = []
        self._forum_topic_items = []
        self.list_forum_topics.clear()
        self.progress_chats.setVisible(False)
        self.btn_load_chats.setEnabled(True)
        self.lbl_loading_chats.setText(f"Загружено чатов: {len(items)}")
        self._render_folders()
        self._render_chats_for_folder(None)
        self._sync_start_button()

    @QtCore.pyqtSlot(list)
    def on_forum_topics_loaded(self, items: list):
        self._forum_topic_items = items
        self.list_forum_topics.clear()
        for it in items:
            self.list_forum_topics.addItem(
                f"{it.chat_title} / {it.title} (тема #{it.topic_id})"
            )

    @QtCore.pyqtSlot(bool)
    def on_sending_state(self, is_sending: bool):
        self.btn_stop.setEnabled(is_sending)
        self.spin_cooldown.setEnabled(not is_sending)
        self.list_chats.setEnabled(not is_sending)
        self.list_imported_targets.setEnabled(not is_sending)
        self.list_forum_topics.setEnabled(not is_sending)
        self._sync_start_button()

    # --- UI actions: GUI -> worker ---
    def ui_send_code(self):
        phone = self.in_phone.text().strip()
        if not phone:
            self.append_log("Введите номер телефона.")
            return
        self.worker.request_code(phone)

    def ui_sign_in_code(self):
        code = self.in_code.text().strip()
        if not code:
            self.append_log("Введите код.")
            return
        self.worker.sign_in_with_code(code)

    def ui_sign_in_password(self):
        password = self.in_password.text()
        if not password:
            self.append_log("Введите пароль 2FA.")
            return
        self.worker.sign_in_with_password(password)

    def ui_request_qr_login(self):
        self.worker.request_qr_login()

    def ui_load_chats(self):
        self.lbl_loading_chats.setText("Загружаю чаты и папки Telegram...")
        self.progress_chats.setVisible(True)
        self.btn_load_chats.setEnabled(False)
        self.worker.load_chats()

    def ui_folder_selected(self):
        self._render_chats_for_folder(self._current_folder_id())
        self._forum_topic_items = []
        self.list_forum_topics.clear()
        self._sync_start_button()

    def ui_select_folder_chats(self):
        for row in range(self.list_chats.count()):
            self.list_chats.item(row).setSelected(True)
        self.ui_chat_selected()

    def ui_import_chats(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Импорт чатов",
            runtime_base_dir(),
            "Text files (*.txt *.csv);;All files (*.*)",
        )
        if not path:
            return

        raw_text = ""
        for enc in ("utf-8-sig", "utf-8", "cp1251"):
            try:
                with open(path, "r", encoding=enc) as f:
                    raw_text = f.read()
                break
            except UnicodeDecodeError:
                continue
            except Exception as exc:
                self.append_log(f"Не удалось прочитать файл импорта: {exc}")
                return

        values = []
        for part in re.split(r"[\n,;]+", raw_text):
            value = part.strip()
            if value and not value.startswith("#"):
                values.append(value)

        existing = {v.lower() for v in self._imported_targets}
        added = 0
        for value in values:
            if value.lower() in existing:
                continue
            self._imported_targets.append(value)
            existing.add(value.lower())
            added += 1

        self._render_imported_targets(select_all=True)
        self._sync_start_button()
        self.append_log(f"Импортировано целей: {added}. Всего в импорте: {len(self._imported_targets)}")

    def ui_clear_imported_targets(self):
        self._imported_targets = []
        self.list_imported_targets.clear()
        self._sync_start_button()
        self.append_log("Импортированные цели очищены.")

    def ui_chat_selected(self):
        selected_rows = sorted({idx.row() for idx in self.list_chats.selectedIndexes()})
        if not selected_rows:
            self.list_forum_topics.clear()
            self._forum_topic_items = []
            self._sync_start_button()
            return

        peer_ids = []
        for row in selected_rows:
            if 0 <= row < len(self._visible_chat_items):
                peer_ids.append(self._visible_chat_items[row].peer_id)

        if peer_ids:
            self.worker.load_forum_topics(peer_ids)

        self._sync_start_button()

    def ui_forum_topic_selected(self):
        self._sync_start_button()

    def ui_save_profile(self):
        current = self.combo_profiles.currentText().strip()
        default_name = current or f"Профиль {len(self._profiles) + 1}"
        name, ok = QtWidgets.QInputDialog.getText(self, "Профиль рассылки", "Название профиля:", text=default_name)
        name = name.strip()
        if not ok or not name:
            return

        selected_chat_ids = []
        for row in sorted({idx.row() for idx in self.list_chats.selectedIndexes()}):
            if 0 <= row < len(self._visible_chat_items):
                selected_chat_ids.append(int(self._visible_chat_items[row].peer_id))

        selected_imports = []
        for item in self.list_imported_targets.selectedItems():
            raw = item.data(QtCore.Qt.UserRole) or item.text()
            selected_imports.append(str(raw))

        topic_payload = None
        topic_row = self.list_forum_topics.currentRow()
        if 0 <= topic_row < len(self._forum_topic_items):
            topic = self._forum_topic_items[topic_row]
            topic_payload = {
                "chat_peer_id": int(topic.chat_peer_id),
                "topic_id": int(topic.topic_id),
                "label": f"{topic.chat_title} / {topic.title}",
            }

        self._profiles[name] = {
            "message": self.txt_messages.toPlainText(),
            "cooldown": int(self.spin_cooldown.value()),
            "chat_peer_ids": selected_chat_ids,
            "imported_targets": selected_imports,
            "topic": topic_payload,
        }
        self._save_profiles()
        self._refresh_profiles_combo()
        idx = self.combo_profiles.findText(name)
        if idx >= 0:
            self.combo_profiles.setCurrentIndex(idx)
        self.append_log(f"Профиль сохранён: {name}")

    def ui_load_profile(self):
        name = self.combo_profiles.currentText().strip()
        if not name or name not in self._profiles:
            self.append_log("Сначала выберите профиль.")
            return

        profile = self._profiles.get(name, {})
        self.txt_messages.setPlainText(str(profile.get("message") or ""))
        self.spin_cooldown.setValue(max(5, int(profile.get("cooldown") or 5)))

        imports = []
        seen_imports = set()
        for raw in profile.get("imported_targets") or []:
            value = str(raw).strip()
            if value and value.lower() not in seen_imports:
                imports.append(value)
                seen_imports.add(value.lower())
        self._imported_targets = imports
        self._render_imported_targets(select_all=True)

        chat_ids = {int(pid) for pid in (profile.get("chat_peer_ids") or []) if str(pid).lstrip("-").isdigit()}
        if chat_ids:
            self.list_folders.setCurrentRow(0)
            self._render_chats_for_folder(None)
            for row, chat in enumerate(self._visible_chat_items):
                if int(chat.peer_id) in chat_ids:
                    self.list_chats.item(row).setSelected(True)

        if profile.get("topic"):
            self.append_log("В профиле есть ветка форума. Выберите чат и дождитесь загрузки веток, если нужно отправлять именно в тему.")

        self._sync_start_button()
        self.append_log(f"Профиль загружен: {name}")

    def ui_delete_profile(self):
        name = self.combo_profiles.currentText().strip()
        if not name or name not in self._profiles:
            self.append_log("Сначала выберите профиль для удаления.")
            return
        if QtWidgets.QMessageBox.question(self, "Удалить профиль", f"Удалить профиль '{name}'?") != QtWidgets.QMessageBox.Yes:
            return
        self._profiles.pop(name, None)
        self._save_profiles()
        self._refresh_profiles_combo()
        self.append_log(f"Профиль удалён: {name}")

    def ui_start_sending(self):
        message_text = self.txt_messages.toPlainText().strip()
        if not message_text:
            self.append_log("Сначала добавьте текст сообщения.")
            return

        targets = []
        seen = set()

        # Always include selected chats
        selected_rows = sorted({idx.row() for idx in self.list_chats.selectedIndexes()})
        for row in selected_rows:
            if 0 <= row < len(self._visible_chat_items):
                chat = self._visible_chat_items[row]
                key = (int(chat.peer_id), None)
                if key in seen:
                    continue
                seen.add(key)
                targets.append({
                    "peer_id": int(chat.peer_id),
                    "topic_id": None,
                    "label": str(chat.title),
                })

        # If a topic is selected, include it too (in addition to chats)
        topic_row = self.list_forum_topics.currentRow()
        if 0 <= topic_row < len(self._forum_topic_items):
            topic = self._forum_topic_items[topic_row]
            # If a specific topic is selected for this chat, prefer topic target over plain chat target.
            plain_key = (int(topic.chat_peer_id), None)
            if plain_key in seen:
                seen.remove(plain_key)
                targets = [
                    t for t in targets
                    if not (int(t.get("peer_id")) == int(topic.chat_peer_id) and t.get("topic_id") is None)
                ]

            key = (int(topic.chat_peer_id), int(topic.topic_id))
            if key not in seen:
                seen.add(key)
                targets.append({
                    "peer_id": int(topic.chat_peer_id),
                    "topic_id": int(topic.topic_id),
                    "label": f"{topic.chat_title} / {topic.title}",
                })

        for item in self.list_imported_targets.selectedItems():
            raw = str(item.data(QtCore.Qt.UserRole) or item.text()).strip()
            if not raw:
                continue
            key = ("raw", raw.lower())
            if key in seen:
                continue
            seen.add(key)
            targets.append({
                "raw_target": raw,
                "topic_id": None,
                "label": raw,
            })

        if not targets:
            self.append_log("Сначала выберите чаты, импортированные цели или одну ветку форума.")
            return

        cooldown_minutes = int(self.spin_cooldown.value())
        if cooldown_minutes < 5:
            cooldown_minutes = 5
            self.spin_cooldown.setValue(5)

        self.worker.start_sending(targets, message_text, cooldown_minutes)

    def ui_stop_sending(self):
        self.worker.stop_sending()

    # --- Graceful close ---
    def closeEvent(self, event: QtGui.QCloseEvent):
        try:
            self._qr_timer.stop()
            if self._qr_dialog:
                self._qr_dialog.close()
            self.worker.shutdown()
        except Exception:
            pass

        # Ждём чуть-чуть закрытия потока (не блокируем долго)
        self.thread.quit()
        self.thread.wait(1500)
        event.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = NeonMainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
