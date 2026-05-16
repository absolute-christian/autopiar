# AutoPiar Telegram для термукса

## Тутор установки (для Termux)

```bash
pkg update -y
pkg install python unzip -y
pip install -r requirements.txt
```

## Запускаем скрипт, API ID и HASH берем отсюда - https://my.telegram.org/apps

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

Скрипт сначала попросит лицензионный ключ, потом происходит заход на акк, а дальше рассылка. Остановка рассылки: `Ctrl+C`
 
## Прем эмодзи

В тексте можно использовать прем эмодзи через эту форму(в поиске тг пишите "emoji code" и в бот отправляете эмодзи, копируете HTML код):

```html
<tg-emoji emoji-id="123456789">🙂</tg-emoji>
```
