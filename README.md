# AutoPiar

AutoPiar - утилита для автопостинга в Telegram через пользовательский аккаунт Telethon. В репозитории есть desktop-версия для Windows, CLI-версия для Termux и сервер online-лицензий.

## Что внутри

- `main.py` - PyQt5 desktop-приложение.
- `Phone/main.py` - CLI/Termux версия.
- `bot/autopiar_bot.py` - Telegram bot-интерфейс для управления Telethon аккаунтом.
- `online_license.py` - online-проверка ключа лицензии.
- `license_server/server.py` - FastAPI сервер лицензий с SQLite.
- `main.spec` - сборка Windows exe через PyInstaller.
- `release/README.txt` - короткая инструкция для Windows zip-архива.

## Windows

### Запуск из исходников

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

После запуска введите лицензионный ключ, затем откройте настройки API и добавьте Telegram `API_ID` / `API_HASH` из <https://my.telegram.org/apps>.

### Сборка exe

```bash
pip install -r requirements.txt
pyinstaller main.spec
```

Результат появится в `dist/AutoPiar.exe`. Для GitHub Release упакуйте exe вместе с `release/README.txt` в архив `AutoPiar-Windows.zip`.

## Termux

```bash
pkg update -y
pkg install python unzip -y
pip install -r Phone/requirements.txt
export API_ID=123456
export API_HASH=abcdef123456
python Phone/main.py
```

Для release-архива Termux нужны `Phone/main.py`, `Phone/requirements.txt`, `Phone/README.md` и `online_license.py`.

## License server

```bash
cd license_server
pip install -r requirements.txt
set LICENSE_ADMIN_TOKEN=change-me
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

Для Linux/macOS используйте `export` вместо `set`.

Важные переменные:

- `LICENSE_ADMIN_TOKEN` - токен входа в админку и API.
- `LICENSE_DB_PATH` - путь к SQLite базе.
- `LICENSE_BACKUP_DIR` - папка бэкапов.
- `LICENSE_PRODUCT_ID` - продукт, по умолчанию `autopiar`.
- `LICENSE_ADMIN_COOKIE_SECURE=1` - включить Secure cookie за HTTPS.

JSON API админки использует заголовок `x-admin-token`. HTML-админка хранит токен в HttpOnly cookie, без передачи токена в URL.

## Railway

Проект готов к деплою license server через `Dockerfile` и `railway.json`. Для постоянного хранения подключите Railway Volume и задайте:

```bash
LICENSE_DB_PATH=/data/licenses.db
LICENSE_BACKUP_DIR=/data/backups
```

## Тесты

```bash
pip install -r license_server/requirements.txt -r requirements-dev.txt
pytest
```

## Релизы

Бинарники не хранятся в Git. Для публикации используйте GitHub Releases:

```bash
gh release create v1.0.0 release/AutoPiar.zip release/AutoPiar-Termux.zip --title "AutoPiar v1.0.0" --notes "Windows and Termux builds"
```

Контакты: Telegram-канал `@autopiar_tg`, личные сообщения `@absolute_christian`.
