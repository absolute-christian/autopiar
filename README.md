# Auto Piar Telegram

GUI-приложение на `PyQt5 + Telethon` для Telegram:
- авторизация по номеру, коду и 2FA;
- загрузка чатов;
- выбор форумных тем;
- циклическая отправка сообщения в выбранные цели.

## Стек

- Python 3.10+
- PyQt5
- Telethon

## Быстрый запуск

1. Установи зависимости:
```bash
pip install -r requirements.txt
```

2. Запусти приложение и открой `API настройки`.

3. Укажи свои данные Telegram API:
- `API_ID`
- `API_HASH`

Данные сохраняются локально в `configs/api_credentials.json`. Этот файл не нужно публиковать в репозиторий.

4. Запусти приложение:
```bash
python main.py
```

## Файлы проекта

- `main.py` - весь GUI и логика работы с Telegram.
- `Phone/` - CLI-версия для Termux/телефона.
- `requirements.txt` - зависимости.
- `*.session` - файлы сессий Telethon (локальные, не публиковать).
- `dist/main.exe` - готовая Windows-сборка.

## Важно по безопасности

- Не коммить `configs/`, `API_ID`, `API_HASH` и `*.session` в публичные репозитории.
- API-ключи вводятся через интерфейс и хранятся только локально.

## Контекст для ИИ (можно копировать)

```text
Это проект на Python с одним главным файлом main.py.
Назначение: Telegram GUI-утилита (PyQt5 + Telethon) для авторизации и автоотправки сообщений в выбранные чаты/форумные темы.

Что важно при правках:
1) Не ломать текущую авторизацию (phone -> code -> 2FA).
2) Не удалять логи и сигналы PyQt (log/auth_state/chats_loaded/forum_topics_loaded/sending_state).
3) Сохранять совместимость с Windows.
4) Предпочитать минимальные точечные изменения.
5) Перед изменениями коротко объяснять план, после изменений показывать diff/файлы.

Текущая структура:
- main.py: UI + worker в QThread с asyncio и Telethon.
- requirements.txt: PyQt5, Telethon.
```

## Идеи для улучшений

- Вынести `API_ID/API_HASH` в `.env`.
- Разделить `main.py` на модули (`ui`, `worker`, `telegram_client`).
- Добавить `logging` в файл и тесты для утилитных функций.

## Лицензирование (офлайн, Ed25519)

- При старте приложение проверяет `license.json` и подпись Ed25519.
- В приложении хранится только публичный ключ (`APP_PUBLIC_KEY_B64` в `main.py`).
- Приватный ключ в приложение не вшивается и используется только для выпуска лицензий.
- Без валидной лицензии главное окно не открывается.
- Реализован anti-rollback: если системная дата меньше `last_ok_date` из `state.json`, запуск блокируется.

Формат `license.json`:

```json
{
  "payload": "<base64url(JSON bytes)>",
  "sig": "<base64url(signature)>"
}
```

Пример payload после decode:

```json
{
  "product": "telethon_neon_sender",
  "license_to": "client_01",
  "issued_at": "2026-02-13",
  "expires": "2026-03-15",
  "type": "user"
}
```

## Dev-меню

- Dev-меню видно только при лицензии типа `dev`.
- Внутри:
- генератор лицензий (`license_to`, `days`, `type`, выбор `private.key`);
- опция сборки EXE через PyInstaller.

Важно: сборка отдельного EXE под каждого клиента технически возможна, но это плохая практика для сопровождения. Рекомендуемый подход: один универсальный EXE + разные `license.json`.

## Сборка EXE

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole main.py
```

После сборки кладите `license.json` рядом с `dist/main.exe`.
