# 🚀 Деплой CRM Monitor на AWS EC2

## 📋 Быстрый старт

### 1. Предварительные требования

- AWS CLI установлен и настроен (credentials уже настроены ✅)
- SSH ключ (скрипт создаст автоматически)
- ~10 минут времени

### 2. Запуск деплоя

```bash
cd /Users/ivanshyla/OrdersToTelegram
./deploy_aws.sh
```

Скрипт автоматически:
1. ✅ Найдёт последний Ubuntu 22.04 AMI
2. ✅ Создаст Security Group
3. ✅ Создаст/найдёт SSH ключ
4. ✅ Запустит EC2 инстанс (t3.micro)
5. ✅ Установит все зависимости
6. ✅ Задеплоит код
7. ✅ Настроит cron (каждые 15 минут, 8:00-22:00 UTC)

### 3. Настройка .env файла

После деплоя нужно заполнить `.env` на сервере:

```bash
# SSH на сервер (скрипт покажет команду)
ssh -i ~/.ssh/crm-monitor-key.pem ubuntu@<PUBLIC_IP>

# Редактировать .env
cd /opt/crm-monitor/crm-watcher
nano .env
```

Заполнить:
```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
CRM_LOGIN_WARSAW=email@example.com
CRM_PASSWORD_WARSAW=password
CRM_LOGIN_BERLIN=email@example.com
CRM_PASSWORD_BERLIN=password
```

### 4. Тестовый запуск

```bash
# На сервере
cd /opt/crm-monitor/crm-watcher
source venv/bin/activate
python3 multi_crm_monitor.py
```

### 5. Проверка логов

```bash
# Логи cron задач
tail -f /var/log/crm-monitor.log

# Логи установки
cat /var/log/crm-monitor-setup.log
```

## 📊 Архитектура

```
┌─────────────────────────────────┐
│   AWS EC2 (t3.micro)            │
│                                 │
│   Ubuntu 22.04                  │
│   ├── Python 3 + venv          │
│   ├── Playwright + Chromium    │
│   ├── OpenCV + EasyOCR         │
│   └── /opt/crm-monitor/        │
│       └── crm-watcher/         │
│           ├── .env             │
│           └── multi_crm_...   │
│                                 │
│   Cron: */15 8-22 * * *        │
└─────────────────────────────────┘
         │
         │ (Telegram API)
         ▼
    ┌──────────┐
    │ Telegram │
    └──────────┘
```

## 💰 Стоимость

- **EC2 t3.micro**: ~$7-10/месяц
  - 1 vCPU, 1GB RAM
  - Достаточно для мониторинга
- **Трафик**: ~$1-2/месяц (небольшой объём)
- **Итого**: ~$8-12/месяц

## 🔧 Управление инстансом

### Остановить инстанс:
```bash
INSTANCE_ID=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=crm-monitor" \
    --query 'Reservations[0].Instances[0].InstanceId' \
    --output text)

aws ec2 stop-instances --instance-ids "$INSTANCE_ID"
```

### Запустить инстанс:
```bash
aws ec2 start-instances --instance-ids "$INSTANCE_ID"
```

### Удалить инстанс:
```bash
# ОСТОРОЖНО! Это удалит инстанс навсегда!
aws ec2 terminate-instances --instance-ids "$INSTANCE_ID"
```

### Получить IP:
```bash
aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=crm-monitor" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text
```

## 🔄 Обновление кода

### Вариант 1: Через скрипт деплоя (пересоздать инстанс)
```bash
./deploy_aws.sh
```

### Вариант 2: Вручную через SSH
```bash
# На вашем Mac
cd /Users/ivanshyla/OrdersToTelegram
tar -czf /tmp/crm-monitor-update.tar.gz \
    --exclude='.git' \
    --exclude='node_modules' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='run_artifacts/*' \
    crm-watcher/

# Скопировать на сервер
scp -i ~/.ssh/crm-monitor-key.pem \
    /tmp/crm-monitor-update.tar.gz \
    ubuntu@<PUBLIC_IP>:/tmp/

# SSH и распаковать
ssh -i ~/.ssh/crm-monitor-key.pem ubuntu@<PUBLIC_IP>
cd /opt/crm-monitor
tar -xzf /tmp/crm-monitor-update.tar.gz
cd crm-watcher
source venv/bin/activate
pip install -r requirements.txt
```

## 📝 Мониторинг

### Проверить что cron работает:
```bash
# На сервере
sudo systemctl status cron
crontab -l -u ubuntu
```

### Проверить последний запуск:
```bash
tail -20 /var/log/crm-monitor.log
```

### Ручной запуск:
```bash
cd /opt/crm-monitor/crm-watcher
source venv/bin/activate
python3 multi_crm_monitor.py
```

## 🐛 Отладка

### Проблемы с SSH:
```bash
# Проверить Security Group
aws ec2 describe-security-groups \
    --group-names crm-monitor-sg

# Разрешить ваш IP для SSH
aws ec2 authorize-security-group-ingress \
    --group-name crm-monitor-sg \
    --protocol tcp \
    --port 22 \
    --cidr YOUR_IP/32
```

### Проблемы с Playwright:
```bash
# На сервере
cd /opt/crm-monitor/crm-watcher
source venv/bin/activate
playwright install chromium
playwright install-deps chromium
```

### Проблемы с зависимостями:
```bash
# На сервере
cd /opt/crm-monitor/crm-watcher
source venv/bin/activate
pip install --upgrade -r requirements.txt
```

## ✅ Готово!

После выполнения всех шагов система будет:
- ✅ Запускаться каждые 15 минут (8:00-22:00 UTC)
- ✅ Мониторить оба города (Варшава, Берлин)
- ✅ Отправлять уведомления в Telegram
- ✅ Логировать все действия в `/var/log/crm-monitor.log`

---

**Вопросы?** См. основной README.md или проверьте логи на сервере.

