# AutoPiar Phone

CLI-версия для Termux без графического интерфейса.

## Установка в Termux

```bash
pkg update -y
pkg install python -y
pip install -r requirements.txt
```

## Запуск

```bash
python main.py
```

Скрипт умеет:

- входить по номеру телефона или QR;
- показывать список чатов;
- выбирать много чатов через запятую, например `1,3,5-8`;
- загружать форумные темы выбранных чатов;
- отправлять текст по кругу с КД;
- принимать `<tg-emoji emoji-id="...">...</tg-emoji>` в тексте сообщения.

Остановка рассылки: `Ctrl+C`.

Цветовая тема терминала: `#5227FF` + `#FF9FFC`, доминирует `#5227FF`.
Если нужен запуск без цветов:

```bash
NO_COLOR=1 python main.py
```

## API

По умолчанию в `main.py` уже стоят API_ID и API_HASH из desktop-версии.
Можно переопределить их переменными окружения:

```bash
export API_ID=123456
export API_HASH=abcdef123456
python main.py
```
