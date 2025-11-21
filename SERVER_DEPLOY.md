# 🚀 Развертывание на сервере

## Почему нужен сервер вместо MacBook:
- ✅ Работает 24/7 без перерывов
- ✅ Не зависит от сна/выключения компьютера
- ✅ Стабильное интернет-соединение
- ✅ Надежный cron без проблем launchd

## 📋 Быстрая инструкция по развертыванию

### 1. Выбор сервера

**Рекомендуемые варианты:**
- **DigitalOcean** - Droplet Ubuntu 22.04 ($6/мес)
- **Hetzner** - Cloud VPS (€3.79/мес)
- **Linode** - Nanode ($5/мес)

**Минимальные требования:**
- 1 GB RAM
- 1 CPU
- 10 GB SSD
- Ubuntu 20.04/22.04 или Debian 11/12

### 2. Установка на сервер

```bash
# Подключаемся к серверу
ssh root@your-server-ip

# Обновляем систему
apt update && apt upgrade -y

# Устанавливаем зависимости
apt install -y python3 python3-pip python3-venv git

# Клонируем репозиторий
cd /opt
git clone <your-repo-url> OrdersToTelegram
cd OrdersToTelegram/crm-watcher

# Создаем виртуальное окружение
python3 -m venv .venv
source .venv/bin/activate

# Устанавливаем зависимости
pip install -r requirements.txt

# Устанавливаем браузер Playwright
playwright install chromium
playwright install-deps chromium

# Копируем конфигурацию
cp multi_crm_config.py.example multi_crm_config.py
nano multi_crm_config.py
# (вставляем наши настройки)
```

### 3. Настройка cron

```bash
# Устанавливаем правильную временную зону
timedatectl set-timezone Europe/Warsaw

# Проверяем время
date
# Должно показать варшавское время

# Редактируем crontab
crontab -e

# Добавляем задания (время указывается по СЕРВЕРНОМУ времени - Warsaw)
30 7 * * * cd /opt/OrdersToTelegram/crm-watcher && /opt/OrdersToTelegram/crm-watcher/.venv/bin/python multi_crm_monitor.py >> /var/log/crm-monitor.log 2>&1
0 19 * * * cd /opt/OrdersToTelegram/crm-watcher && /opt/OrdersToTelegram/crm-watcher/.venv/bin/python multi_crm_monitor.py >> /var/log/crm-monitor.log 2>&1
0 20 * * * cd /opt/OrdersToTelegram/crm-watcher && /opt/OrdersToTelegram/crm-watcher/.venv/bin/python multi_crm_monitor.py >> /var/log/crm-monitor.log 2>&1
0 21 * * * cd /opt/OrdersToTelegram/crm-watcher && /opt/OrdersToTelegram/crm-watcher/.venv/bin/python multi_crm_monitor.py >> /var/log/crm-monitor.log 2>&1
```

### 4. Тестирование

```bash
# Тестовый запуск
cd /opt/OrdersToTelegram/crm-watcher
source .venv/bin/activate
python multi_crm_monitor.py

# Проверяем логи
tail -f /var/log/crm-monitor.log
```

### 5. Мониторинг

```bash
# Просмотр логов cron
tail -f /var/log/syslog | grep CRON

# Просмотр логов приложения
tail -f /var/log/crm-monitor.log

# Проверка запущенных задач
ps aux | grep python

# Просмотр скриншотов
ls -lh /opt/OrdersToTelegram/crm-watcher/run_artifacts/
```

## 🔧 Настройка конфигурации на сервере

Файл `multi_crm_config.py`:
```python
CRM_CONFIGS = {
    "warsaw": {
        "name": "Варшава",
        "crm_url": "https://crm.clean-whale.com/login",
        "crm_dashboard": "https://crm.clean-whale.com",
        "login": "ivan.shyla@cleanwhale.pl",
        "password": "r3NLdv[#}3",
        "telegram_chat_id": "-570262307",
        "timezone": "Europe/Warsaw",
        "notification_hours": [7, 19, 20, 21],
        "enabled": True
    },
    "berlin": {
        "name": "Берлин", 
        "crm_url": "https://crm.clean-whale.com/login",
        "crm_dashboard": "https://crm.clean-whale.com",
        "login": "ekaterina.daneyko@cleanwhale.de",
        "password": "tknxxMuP7nQVAQKD",
        "telegram_chat_id": "-1003007468821",
        "timezone": "Europe/Berlin", 
        "notification_hours": [7, 19, 20, 21],
        "enabled": True
    }
}

TELEGRAM_BOT_TOKEN = "7983513621:AAEhkYoAhpsgUD4A1GrZaqnZERKJBbyFs9Y"
```

## 📊 Логика работы на сервере

### Утренняя проверка (7:30)
- **Проверяет**: СЕГОДНЯШНИЙ день
- **Сообщение**: "⚠️ На сегодня есть неразобранные заказы"
- **Цель**: Убедиться что все заказы на текущий день разобраны

### Вечерние проверки (19:00, 20:00, 21:00)
- **Проверяет**: ЗАВТРАШНИЙ день  
- **Сообщение**: "⚠️ На 02.10 есть неразобранные заказы"
- **Цель**: Подготовка к следующему рабочему дню

## 🔐 Безопасность

```bash
# Создаем отдельного пользователя
useradd -m -s /bin/bash crm-monitor
passwd crm-monitor

# Переносим файлы
mv /opt/OrdersToTelegram /home/crm-monitor/
chown -R crm-monitor:crm-monitor /home/crm-monitor/OrdersToTelegram

# Настраиваем cron для этого пользователя
su - crm-monitor
crontab -e
# (добавляем задания)
```

## 🚨 Решение проблем

### Проблема: Cron не запускается
```bash
# Проверяем статус cron
systemctl status cron

# Перезапускаем cron
systemctl restart cron

# Проверяем синтаксис crontab
crontab -l
```

### Проблема: Playwright не работает
```bash
# Доустанавливаем зависимости
playwright install-deps chromium

# Или вручную
apt install -y libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1
```

### Проблема: Неправильное время
```bash
# Проверяем временную зону
timedatectl

# Устанавливаем Warsaw
timedatectl set-timezone Europe/Warsaw

# Проверяем
date
```

## 📈 Автоматические обновления

```bash
# Создаем скрипт обновления
cat > /home/crm-monitor/update.sh << 'EOF'
#!/bin/bash
cd /home/crm-monitor/OrdersToTelegram/crm-watcher
git pull
source .venv/bin/activate
pip install -r requirements.txt --upgrade
EOF

chmod +x /home/crm-monitor/update.sh

# Добавляем в cron (обновление раз в неделю)
0 3 * * 0 /home/crm-monitor/update.sh >> /var/log/crm-update.log 2>&1
```

## ✅ Преимущества серверного решения

- **Надежность**: Работает 24/7
- **Производительность**: Быстрее чем MacBook
- **Стабильность**: Нет проблем со сном/выключением
- **Простота**: Linux cron надежнее macOS launchd
- **Масштабируемость**: Легко добавить новые города
- **Мониторинг**: Удобные логи и отладка

















