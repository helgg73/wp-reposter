# Установка WP Reposter на Linux-сервер

## 1. Подготовка системы

```bash
# Обновить пакеты
sudo apt update && sudo apt upgrade -y

# Установить Python 3.12+ (если нет)
sudo apt install python3.12 python3.12-venv -y

# Установить uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
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

## 4. Создание пользователя

```bash
sudo useradd --system --no-create-home --shell /bin/false wp-reposter
sudo chown -R wp-reposter:wp-reposter /opt/wp-reposter
```

## 5. Конфигурация

```bash
# Создать конфиг из примера
cp config/settings.example.yaml config/settings.yaml
nano config/settings.yaml  # Заполнить реальными данными

# Создать .env с секретами
nano .env
# MAX_BOT_TOKEN=ваш_токен
# MAX_CHAT_ID=ваш_chat_id

# Установить права
sudo chown wp-reposter:wp-reposter config/settings.yaml .env
chmod 600 .env
```

## 6. Установка systemd unit

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

```bash
cd /opt/wp-reposter
git pull
uv sync --frozen
sudo systemctl restart wp-reposter
```