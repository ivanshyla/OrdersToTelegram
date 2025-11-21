#!/bin/bash
# Скрипт деплоя CRM Monitor на AWS EC2

set -e

echo "🚀 Деплой CRM Monitor на AWS EC2..."

# Конфигурация
INSTANCE_TYPE="t3.micro"  # Free tier eligible
REGION=$(aws configure get region || echo "us-east-1")
KEY_NAME="crm-monitor-key"  # Нужно будет создать или указать существующий
SECURITY_GROUP="crm-monitor-sg"

# Получаем последний Ubuntu 22.04 AMI ID для региона
get_ubuntu_ami() {
    echo "🔍 Поиск Ubuntu 22.04 AMI в регионе $REGION..."
    AMI_ID=$(aws ec2 describe-images \
        --region "$REGION" \
        --owners 099720109477 \
        --filters "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" "Name=state,Values=available" \
        --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' \
        --output text 2>/dev/null || echo "")
    
    if [ -z "$AMI_ID" ] || [ "$AMI_ID" == "None" ]; then
        echo "   ⚠️  Не удалось найти AMI автоматически, используем дефолтный для us-east-1"
        AMI_ID="ami-0c55b159cbfafe1f0"
    else
        echo "   ✅ Найден AMI: $AMI_ID"
    fi
    echo "$AMI_ID"
}

# Функция для создания Security Group
create_security_group() {
    echo "📦 Создание Security Group..."
    
    # Проверяем существует ли уже
    SG_ID=$(aws ec2 describe-security-groups \
        --group-names "$SECURITY_GROUP" \
        --query 'SecurityGroups[0].GroupId' \
        --output text 2>/dev/null || echo "")
    
    if [ -z "$SG_ID" ] || [ "$SG_ID" == "None" ]; then
        echo "   Создаём новый Security Group..."
        SG_ID=$(aws ec2 create-security-group \
            --group-name "$SECURITY_GROUP" \
            --description "Security group for CRM Monitor" \
            --query 'GroupId' \
            --output text)
        
        # Разрешаем SSH из любого места (можно ограничить по IP)
        aws ec2 authorize-security-group-ingress \
            --group-id "$SG_ID" \
            --protocol tcp \
            --port 22 \
            --cidr 0.0.0.0/0 >/dev/null 2>&1 || true
        
        echo "   ✅ Security Group создан: $SG_ID"
    else
        echo "   ✅ Security Group уже существует: $SG_ID"
    fi
    
    echo "$SG_ID"
}

# Функция для создания/поиска Key Pair
setup_key_pair() {
    echo "🔑 Настройка Key Pair..."
    
    if aws ec2 describe-key-pairs --key-names "$KEY_NAME" >/dev/null 2>&1; then
        echo "   ✅ Key Pair уже существует: $KEY_NAME"
        if [ ! -f ~/.ssh/${KEY_NAME}.pem ]; then
            echo "   ⚠️  Файл ключа не найден локально!"
            echo "   Скачиваем публичный ключ..."
            aws ec2 describe-key-pairs --key-names "$KEY_NAME" --query 'KeyPairs[0].KeyMaterial' --output text
        fi
    else
        echo "   Создаём новый Key Pair..."
        aws ec2 create-key-pair \
            --key-name "$KEY_NAME" \
            --query 'KeyMaterial' \
            --output text > ~/.ssh/${KEY_NAME}.pem
        chmod 400 ~/.ssh/${KEY_NAME}.pem
        echo "   ✅ Key Pair создан и сохранён в ~/.ssh/${KEY_NAME}.pem"
    fi
}

# Функция для создания EC2 инстанса
create_instance() {
    echo "🖥️  Создание EC2 инстанса..."
    
    SG_ID=$1
    
    # User data скрипт для установки всего необходимого
    USER_DATA=$(cat <<'USERDATA'
#!/bin/bash
set -e

# Обновляем систему
apt-get update -y
apt-get upgrade -y

# Устанавливаем Python и зависимости
apt-get install -y python3 python3-pip python3-venv git curl

# Устанавливаем Playwright браузеры
pip3 install playwright
playwright install chromium
playwright install-deps chromium

# Создаём директорию для приложения
mkdir -p /opt/crm-monitor
chown ubuntu:ubuntu /opt/crm-monitor

# Добавляем cron для автоматического запуска
cat > /etc/cron.d/crm-monitor <<CRON
# Запуск CRM Monitor каждые 15 минут с 8:00 до 22:00 UTC
*/15 8-22 * * * ubuntu cd /opt/crm-monitor && /usr/bin/python3 /opt/crm-monitor/crm-watcher/multi_crm_monitor.py >> /var/log/crm-monitor.log 2>&1
CRON

echo "✅ Setup completed!" >> /var/log/crm-monitor-setup.log
USERDATA
)
    
    INSTANCE_ID=$(aws ec2 run-instances \
        --image-id "$AMI_ID" \
        --instance-type "$INSTANCE_TYPE" \
        --key-name "$KEY_NAME" \
        --security-group-ids "$SG_ID" \
        --user-data "$USER_DATA" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=crm-monitor}]" \
        --query 'Instances[0].InstanceId' \
        --output text)
    
    echo "   ✅ Инстанс создан: $INSTANCE_ID"
    echo "   ⏳ Ожидание запуска инстанса..."
    
    aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"
    
    # Получаем публичный IP
    PUBLIC_IP=$(aws ec2 describe-instances \
        --instance-ids "$INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].PublicIpAddress' \
        --output text)
    
    echo "   ✅ Инстанс запущен!"
    echo "   📍 Public IP: $PUBLIC_IP"
    echo "   🔑 SSH: ssh -i ~/.ssh/${KEY_NAME}.pem ubuntu@${PUBLIC_IP}"
    
    echo "$INSTANCE_ID|$PUBLIC_IP"
}

# Функция для деплоя кода
deploy_code() {
    echo "📦 Деплой кода на сервер..."
    
    INSTANCE_ID=$1
    PUBLIC_IP=$2
    
    # Ждём пока user-data скрипт выполнится (2-3 минуты)
    echo "   ⏳ Ожидание завершения установки на сервере (это может занять 2-3 минуты)..."
    sleep 180
    
    # Упаковываем код (исключаем ненужное)
    cd "$(dirname "$0")"
    tar -czf /tmp/crm-monitor-deploy.tar.gz \
        --exclude='.git' \
        --exclude='node_modules' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='run_artifacts/*' \
        --exclude='.env' \
        --exclude='*.log' \
        crm-watcher/
    
    # Копируем на сервер
    echo "   📤 Копирование кода на сервер..."
    scp -i ~/.ssh/${KEY_NAME}.pem \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        /tmp/crm-monitor-deploy.tar.gz ubuntu@${PUBLIC_IP}:/tmp/
    
    # Распаковываем на сервере
    echo "   📂 Установка кода..."
    ssh -i ~/.ssh/${KEY_NAME}.pem \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        ubuntu@${PUBLIC_IP} <<SSH
set -e
cd /opt/crm-monitor
tar -xzf /tmp/crm-monitor-deploy.tar.gz
cd crm-watcher
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium
echo "✅ Code deployed!"
SSH
    
    echo "   ✅ Код задеплоен!"
    
    # Удаляем временный файл
    rm /tmp/crm-monitor-deploy.tar.gz
}

# Функция для настройки .env
setup_env() {
    echo "⚙️  Настройка .env файла..."
    
    PUBLIC_IP=$1
    
    # Создаём .env файл на сервере из env.example
    ssh -i ~/.ssh/${KEY_NAME}.pem \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        ubuntu@${PUBLIC_IP} <<SSH
cd /opt/crm-monitor/crm-watcher
if [ ! -f .env ]; then
    cp env.example .env
    echo "⚠️  ВАЖНО: Нужно заполнить .env файл на сервере!"
    echo "   SSH команда: ssh -i ~/.ssh/${KEY_NAME}.pem ubuntu@${PUBLIC_IP}"
    echo "   Редактировать: nano /opt/crm-monitor/crm-watcher/.env"
fi
SSH
    
    echo "   ⚠️  Не забудьте заполнить .env файл на сервере!"
}

# Главная функция
main() {
    echo "=========================================="
    echo "🚀 ДЕПЛОЙ CRM MONITOR НА AWS EC2"
    echo "=========================================="
    echo "   Регион: $REGION"
    echo ""
    
    # 0. Получаем AMI ID
    AMI_ID=$(get_ubuntu_ami)
    echo ""
    
    # 1. Создаём Security Group
    SG_ID=$(create_security_group)
    echo ""
    
    # 2. Настраиваем Key Pair
    setup_key_pair
    echo ""
    
    # 3. Создаём инстанс
    INSTANCE_INFO=$(create_instance "$SG_ID")
    INSTANCE_ID=$(echo "$INSTANCE_INFO" | cut -d'|' -f1)
    PUBLIC_IP=$(echo "$INSTANCE_INFO" | cut -d'|' -f2)
    echo ""
    
    # 4. Деплоим код
    deploy_code "$INSTANCE_ID" "$PUBLIC_IP"
    echo ""
    
    # 5. Настраиваем .env
    setup_env "$PUBLIC_IP"
    echo ""
    
    echo "=========================================="
    echo "✅ ДЕПЛОЙ ЗАВЕРШЁН!"
    echo "=========================================="
    echo ""
    echo "📋 Информация:"
    echo "   Instance ID: $INSTANCE_ID"
    echo "   Public IP:   $PUBLIC_IP"
    echo "   SSH:         ssh -i ~/.ssh/${KEY_NAME}.pem ubuntu@${PUBLIC_IP}"
    echo ""
    echo "⚙️  Следующие шаги:"
    echo "   1. Настроить .env файл на сервере"
    echo "   2. Запустить тест: cd /opt/crm-monitor/crm-watcher && python3 multi_crm_monitor.py"
    echo "   3. Проверить логи: tail -f /var/log/crm-monitor.log"
    echo ""
    echo "💰 Стоимость: ~$7-10/месяц (t3.micro)"
    echo ""
}

# Запуск
main

