# AutoPiar Phone

CLI-версия AutoPiar для Termux. Скрипт умеет входить в Telegram по номеру или QR, показывать папки и чаты, выбирать несколько папок, загружать форумные темы и отправлять текст по кругу с cooldown.

## Установка в Termux

```bash
pkg update -y
pkg install python unzip -y
pip install -r requirements.txt
```

## Запуск

Если запускаете из корня репозитория:

```bash
export API_ID=123456
export API_HASH=abcdef123456
python Phone/main.py
```

Если запускаете из Termux release-архива, распакуйте архив, перейдите в папку и выполните:

```bash
export API_ID=123456
export API_HASH=abcdef123456
python Phone/main.py
```

Скрипт сначала попросит лицензионный ключ, затем предложит вход в Telegram. Остановка рассылки: `Ctrl+C`.

## Настройки

- `API_ID` и `API_HASH` - данные приложения Telegram с <https://my.telegram.org/apps>.
- `AUTOPIAR_LICENSE_KEY` - лицензионный ключ без интерактивного ввода.
- `AUTOPIAR_LICENSE_SERVER_URL` - свой сервер лицензий, если нужен.
- `AUTOPIAR_DATA_DIR` - папка для сессии и локальных файлов.
- `SESSION_NAME` - путь/имя Telethon session.
- `NO_COLOR=1` - отключить цвета терминала.

## Custom emoji

В тексте можно использовать Telegram custom emoji:

```html
<tg-emoji emoji-id="123456789">🙂</tg-emoji>
```
