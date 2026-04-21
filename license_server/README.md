# AutoPiar License Server

Сервер онлайн-лицензий для AutoPiar. Ключи хранятся в SQLite-БД, клиент проверяет ключ через `POST /api/activate`.

## Установка

```bash
cd license_server
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

На Linux:

```bash
cd license_server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Запуск

```bash
set LICENSE_ADMIN_TOKEN=change-me
venv\Scripts\uvicorn server:app --host 0.0.0.0 --port 8000
```

Linux:

```bash
export LICENSE_ADMIN_TOKEN="change-me"
uvicorn server:app --host 0.0.0.0 --port 8000
```

## Railway

В репозитории уже есть `nixpacks.toml` и `railway.json`, поэтому Railway должен запускать сервер командой:

```bash
cd license_server && python -m uvicorn server:app --host 0.0.0.0 --port $PORT
```

Если в Railway вручную задан `Start Command`, очистите его или поставьте ровно команду выше.

Обязательно добавьте переменную окружения:

```text
LICENSE_ADMIN_TOKEN=любой_сложный_пароль
```

После деплоя проверьте:

```text
https://your-service.up.railway.app/health
https://your-service.up.railway.app/admin
```

## Админ-панель

Откройте в браузере:

```text
https://your-domain.com/admin
```

В поле входа укажите значение переменной:

```text
LICENSE_ADMIN_TOKEN
```

После входа можно:

- создать ключ;
- указать клиента/заметку;
- выбрать срок действия;
- выбрать лимит устройств;
- отозвать ключ.

## Создать ключ

```bash
python manage_keys.py create --owner client_01 --days 30 --max-devices 1
```

## Посмотреть ключи

```bash
python manage_keys.py list
```

## Отозвать ключ

```bash
python manage_keys.py revoke AP-your-key
```

## Настройка клиента

В приложении на ПК при старте появится окно лицензии. Нужно указать:

- адрес сервера, например `https://your-domain.com`;
- лицензионный ключ.

В Termux можно задать переменные:

```bash
export AUTOPIAR_LICENSE_SERVER_URL="https://your-domain.com"
export AUTOPIAR_LICENSE_KEY="AP-your-key"
```

Или скрипт спросит их при запуске.
