# AutoPiar Bot

Гибридный Telegram bot + Telethon user-session. Bot API используется только как интерфейс с кнопками, а отправка идет от подключенного Telegram аккаунта.

## Настройка

```bash
python -m venv .venv-bot
.venv-bot\Scripts\activate
pip install -r bot/requirements.txt
copy bot\.env.example bot\.env
```

Заполните `bot/.env`:

```env
BOT_TOKEN=token-from-botfather
OWNER_ID=5905289902
API_ID=123456
API_HASH=abcdef123456
```

`API_ID` и `API_HASH` можно не указывать заранее: бот спросит их при подключении аккаунта.

## Запуск

```bash
python bot/autopiar_bot.py
```

Откройте бота в Telegram и отправьте `/start`.

## Что умеет

- доступ только для `OWNER_ID`;
- подключение Telegram аккаунта по телефону/коду/2FA или QR-ссылке;
- загрузка всех чатов аккаунта, но показ только папок Telegram;
- выбор папки через inline-кнопки;
- настройка текста поста и cooldown;
- запуск/остановка циклической отправки;
- уведомления владельцу по каждой ошибке отправки.

## Важно

Не коммитьте `bot/.env`, `bot/data/` и `.session` файлы. В них находятся токены и сессия Telegram аккаунта.
