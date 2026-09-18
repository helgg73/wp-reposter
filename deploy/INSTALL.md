# Установка WP Reposter на Linux-сервер

Инструкция для Debian/Ubuntu и ALT Linux. Для других дистрибутивов
команды установки пакетов замените на свои.

## 1. Подготовка системы

### Debian/Ubuntu

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3.12 python3.12-venv git -y

# Установить uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
```

### ALT Linux

```bash
sudo apt-get update
sudo apt-get install python3 python3-venv git uv -y
```

В ALT Linux `uv` уже есть в репозитории (`python3-module-uv`),
поэтому `curl | sh` и `source $HOME/.cargo/env` не нужны.

Проверьте версию Python:

```bash
python3 --version
```

Если версия ниже 3.12, установите её через `uv`:

```bash
uv python install 3.12
```

## 2. Клонирование репозитория

```bash
sudo mkdir -p /opt/wp-reposter
sudo chown $USER:$USER /opt/wp-reposter
cd /opt/wp-reposter
git clone <your-repo-url> .
```

## 3. Установка зависимостей

```bash
uv sync --frozen
```

`uv` сам создаст виртуальное окружение в `.venv` и установит туда
все зависимости. Активировать `.venv` вручную не нужно.

## 4. Конфигурация

> **Важно:** конфиги создаются и правятся **от вашего пользователя**,
> пока папка ещё принадлежит вам. Передача владения сервисному
> пользователю делается только на шаге 5.

```bash
# Создать конфиг из примера
cp config/settings.example.yaml config/settings.yaml
nano config/settings.yaml  # Заполнить реальными данными

# Создать .env с секретами
nano .env
# MAX_BOT_TOKEN=ваш_токен
# MAX_CHAT_ID=ваш_chat_id
```

## 5. Создание пользователя и передача прав

```bash
# Создать системного пользователя без домашней директории
sudo useradd --system --no-create-home --shell /bin/false wp-reposter

# Передать владение папкой сервисному пользователю
sudo chown -R wp-reposter:wp-reposter /opt/wp-reposter

# Ограничить доступ к .env
sudo chmod 600 /opt/wp-reposter/.env
```

## 6. Установка systemd unit

Проверьте `deploy/wp-reposter.service`. В нём должны быть указаны:

- `User=wp-reposter`
- `Group=wp-reposter`
- `WorkingDirectory=/opt/wp-reposter`
- `ExecStart=` с путём к `.venv/bin/python` или через `uv run`

Если пути в unit-файле отличаются от `/opt/wp-reposter` — исправьте
их **до** копирования в `/etc/systemd/system/`.

```bash
sudo cp deploy/wp-reposter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable wp-reposter
sudo systemctl start wp-reposter
```

## 7. Проверка

```bash
# Статус сервиса
sudo systemctl status wp-reposter

# Логи в реальном времени
sudo journalctl -u wp-reposter -f

# Логи за последний час
sudo journalctl -u wp-reposter --since "1 hour ago"
```

## 8. Управление

```bash
# Остановить
sudo systemctl stop wp-reposter

# Перезапустить
sudo systemctl restart wp-reposter

# Отключить автозапуск
sudo systemctl disable wp-reposter
```

## 9. Обновление

Обновление выполняется **от имени сервисного пользователя**,
так как папка принадлежит ему.

```bash
sudo -u wp-reposter git -C /opt/wp-reposter pull
sudo -u wp-reposter bash -c 'cd /opt/wp-reposter && uv sync --frozen'
sudo systemctl restart wp-reposter
```

Если `sudo -u wp-reposter` не работает из-за отсутствия shell
(он указан как `/bin/false`), используйте `runuser`:

```bash
sudo runuser -u wp-reposter -- git -C /opt/wp-reposter pull
sudo runuser -u wp-reposter -- bash -c 'cd /opt/wp-reposter && uv sync --frozen'
sudo systemctl restart wp-reposter
```

> **Альтернатива:** можно временно вернуть владение папкой себе,
> обновиться, и снова отдать права сервисному пользователю:
>
> ```bash
> sudo chown -R $USER:$USER /opt/wp-reposter
> cd /opt/wp-reposter
> git pull
> uv sync --frozen
> sudo chown -R wp-reposter:wp-reposter /opt/wp-reposter
> sudo systemctl restart wp-reposter
> ```
>
> Этот способ удобнее, если обновления редкие. Но помните, что
> `uv sync` при этом будет запускаться от вашего пользователя,
> а не от `wp-reposter`.