# Auto Piar Telegram

Подробности в ТГК - @autopiar_tg, либо в ЛС - @absolute_christian

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

При первом запуске приложение попросит:

- адрес сервера лицензий;
- лицензионный ключ.

После успешной проверки данные сохранятся локально в `configs/online_license.json`.

## Файлы проекта

- `main.py` - весь GUI и логика работы с Telegram.
- `online_license.py` - онлайн-проверка ключа лицензии через сервер.
- `license_server/` - сервер лицензий с SQLite-БД для хостинга.
- `Phone/` - CLI-версия для Termux/телефона.
- `requirements.txt` - зависимости.
- `*.session` - файлы сессий Telethon (локальные, не публиковать).
- `dist/main.exe` - готовая Windows-сборка.

## Важно по безопасности

- Не коммить `configs/`, `API_ID`, `API_HASH` и `*.session` в публичные репозитории.
- API-ключи вводятся через интерфейс и хранятся только локально.
- Не коммить БД лицензий `license_server/*.db`, потому что там реальные ключи клиентов.

## Онлайн-лицензии через БД

В проекте есть сервер лицензий:

```bash
cd license_server
pip install -r requirements.txt
python manage_keys.py create --owner client_01 --days 30 --max-devices 1
uvicorn server:app --host 0.0.0.0 --port 8000
```

Клиент проверяет ключ через:

```text
POST /api/activate
```

На хостинге нужно запустить `license_server/server.py`, а в приложении указать URL сервера, например:

```text
https://your-domain.com
```

Для Termux можно задать переменные:

```bash
export AUTOPIAR_LICENSE_SERVER_URL="https://your-domain.com"
export AUTOPIAR_LICENSE_KEY="AP-your-key"
```

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

## Лицензирование

Актуальная схема лицензирования - онлайн-проверка ключа через сервер из `license_server/`.
Без успешного ответа сервера главное окно не открывается.

Старый офлайн-модуль Ed25519 лежит в `licensing/` как задел, но текущий запуск приложения использует онлайн-ключи из БД.

Формат старого `license.json`:

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
