#!/bin/bash
# Деплой CRM Monitor на AWS Lambda

set -e

echo "🚀 Деплой CRM Monitor на AWS Lambda..."

# Конфигурация
FUNCTION_NAME="crm-monitor"
REGION="eu-north-1"  # Europe (Stockholm)
ROLE_NAME="crm-monitor-lambda-role"
RUNTIME="python3.11"
TIMEOUT=900  # 15 минут максимум для Lambda
MEMORY=1024  # 1GB RAM

# Создание IAM Role для Lambda
create_lambda_role() {
    echo "🔐 Создание IAM Role для Lambda..."
    
    # Проверяем существует ли роль
    if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
        echo "   ✅ Role уже существует: $ROLE_NAME"
        ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)
        echo "$ROLE_ARN"
        return
    fi
    
    # Trust policy для Lambda
    cat > /tmp/lambda-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
    
    # Создаём роль
    aws iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document file:///tmp/lambda-trust-policy.json \
        --description "Role for CRM Monitor Lambda function" \
        >/dev/null 2>&1 || true
    
    # Добавляем базовые политики (CloudWatch Logs)
    aws iam attach-role-policy \
        --role-name "$ROLE_ARN" \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole \
        >/dev/null 2>&1 || true
    
    # Ждём пока роль будет готова
    sleep 5
    
    ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)
    echo "   ✅ Role создана: $ROLE_ARN"
    echo "$ROLE_ARN"
}

# Упаковка проекта для Lambda
package_lambda() {
    echo "📦 Упаковка проекта для Lambda..."
    
    cd "$(dirname "$0")"
    
    # Создаём временную директорию
    PACKAGE_DIR="/tmp/crm-monitor-lambda"
    rm -rf "$PACKAGE_DIR"
    mkdir -p "$PACKAGE_DIR"
    
    # Копируем код
    cp -r crm-watcher/* "$PACKAGE_DIR/"
    
    # Удаляем ненужное
    rm -rf "$PACKAGE_DIR/run_artifacts"
    rm -rf "$PACKAGE_DIR/__pycache__"
    rm -f "$PACKAGE_DIR/*.log"
    rm -f "$PACKAGE_DIR/.env"
    rm -f "$PACKAGE_DIR/*.plist"
    rm -f "$PACKAGE_DIR/crontab.txt"
    
    # Создаём lambda_handler.py
    cat > "$PACKAGE_DIR/lambda_function.py" <<'HANDLER'
import json
import os
import sys

# Добавляем путь к модулям
sys.path.insert(0, '/var/task')

# Настройка Playwright для Lambda (если используется layer)
if os.path.exists('/opt/playwright'):
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '/opt/playwright'

def lambda_handler(event, context):
    """
    AWS Lambda handler для CRM Monitor
    """
    try:
        # Импортируем после настройки путей
        from multi_crm_monitor import main
        
        # Запускаем мониторинг
        main()
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'CRM monitoring completed successfully',
                'timestamp': context.aws_request_id
            })
        }
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'message': f'CRM monitoring failed: {str(e)}',
                'error': str(e)
            })
        }
HANDLER
    
    # Устанавливаем зависимости в package (исключаем playwright - будет через layer)
    echo "   📦 Установка зависимостей..."
    cd "$PACKAGE_DIR"
    
    # Создаём requirements без playwright (будет через layer)
    grep -v "^playwright" requirements.txt > /tmp/requirements-lambda.txt || cp requirements.txt /tmp/requirements-lambda.txt
    
    pip3 install -r /tmp/requirements-lambda.txt -t . --quiet 2>&1 | head -10 || true
    
    # Playwright нужно устанавливать отдельно через Lambda Layer
    echo "   ⚠️  Playwright будет установлен через Lambda Layer"
    
    # Создаём ZIP архив
    ZIP_FILE="/tmp/crm-monitor-lambda.zip"
    rm -f "$ZIP_FILE"
    zip -r "$ZIP_FILE" . -q
    
    # Проверяем размер (Lambda максимум 50MB unzipped, 250MB zipped)
    SIZE=$(stat -f%z "$ZIP_FILE" 2>/dev/null || stat -c%s "$ZIP_FILE" 2>/dev/null || echo "0")
    SIZE_MB=$(echo "scale=2; $SIZE / 1024 / 1024" | bc)
    echo "   ✅ Package создан: $ZIP_FILE (${SIZE_MB}MB)"
    
    echo "$ZIP_FILE"
}

# Создание/обновление Lambda функции
deploy_lambda() {
    echo "🚀 Деплой Lambda функции..."
    
    ZIP_FILE=$1
    ROLE_ARN=$2
    
    # Проверяем существует ли функция
    if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
        echo "   🔄 Обновление существующей функции..."
        
        aws lambda update-function-code \
            --function-name "$FUNCTION_NAME" \
            --region "$REGION" \
            --zip-file "fileb://$ZIP_FILE" \
            --output json > /tmp/lambda-update.json
        
        # Обновляем конфигурацию
        aws lambda update-function-configuration \
            --function-name "$FUNCTION_NAME" \
            --region "$REGION" \
            --timeout "$TIMEOUT" \
            --memory-size "$MEMORY" \
            --output json > /dev/null
        
        echo "   ✅ Функция обновлена!"
    else
        echo "   ➕ Создание новой функции..."
        
        aws lambda create-function \
            --function-name "$FUNCTION_NAME" \
            --region "$REGION" \
            --runtime "$RUNTIME" \
            --role "$ROLE_ARN" \
            --handler lambda_function.lambda_handler \
            --zip-file "fileb://$ZIP_FILE" \
            --timeout "$TIMEOUT" \
            --memory-size "$MEMORY" \
            --output json > /tmp/lambda-create.json
        
        echo "   ✅ Функция создана!"
    fi
    
    # Настраиваем переменные окружения (нужно будет заполнить вручную)
    echo "   ⚙️  Настройка переменных окружения..."
    echo "   ⚠️  ВАЖНО: Заполните переменные окружения в AWS Console!"
    echo "      Lambda → Functions → $FUNCTION_NAME → Configuration → Environment variables"
}

# Создание EventBridge правила для запуска по расписанию
setup_schedule() {
    echo "⏰ Настройка расписания (EventBridge)..."
    
    RULE_NAME="crm-monitor-schedule"
    
    # Создаём правило (каждые 15 минут с 8:00 до 22:00 UTC)
    # Cron: */15 8-22 * * ?
    CRON_EXPRESSION="cron(*/15 8-22 * * ? *)"
    
    # Проверяем существует ли правило
    if aws events describe-rule --name "$RULE_NAME" --region "$REGION" >/dev/null 2>&1; then
        echo "   🔄 Обновление правила..."
        aws events put-rule \
            --name "$RULE_NAME" \
            --region "$REGION" \
            --schedule-expression "$CRON_EXPRESSION" \
            --description "CRM Monitor - каждые 15 минут 8:00-22:00 UTC" \
            >/dev/null
    else
        echo "   ➕ Создание правила..."
        aws events put-rule \
            --name "$RULE_NAME" \
            --region "$REGION" \
            --schedule-expression "$CRON_EXPRESSION" \
            --description "CRM Monitor - каждые 15 минут 8:00-22:00 UTC" \
            --state ENABLED \
            >/dev/null
    fi
    
    # Получаем ARN функции
    FUNCTION_ARN=$(aws lambda get-function \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" \
        --query 'Configuration.FunctionArn' \
        --output text)
    
    # Разрешаем EventBridge вызывать Lambda
    aws lambda add-permission \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" \
        --statement-id "allow-eventbridge-invoke" \
        --action "lambda:InvokeFunction" \
        --principal events.amazonaws.com \
        --source-arn "arn:aws:events:${REGION}:$(aws sts get-caller-identity --query Account --output text):rule/${RULE_NAME}" \
        >/dev/null 2>&1 || true
    
    # Добавляем target (Lambda функцию) к правилу
    RULE_ARN=$(aws events describe-rule --name "$RULE_NAME" --region "$REGION" --query 'Arn' --output text)
    
    aws events put-targets \
        --rule "$RULE_NAME" \
        --region "$REGION" \
        --targets "Id"="1","Arn"="$FUNCTION_ARN" \
        >/dev/null
    
    echo "   ✅ Расписание настроено!"
    echo "   📅 Каждые 15 минут с 8:00 до 22:00 UTC"
}

# Главная функция
main() {
    echo "=========================================="
    echo "🚀 ДЕПЛОЙ CRM MONITOR НА AWS LAMBDA"
    echo "=========================================="
    echo "   Регион: $REGION (Europe Stockholm)"
    echo "   Функция: $FUNCTION_NAME"
    echo ""
    
    # 1. Создаём IAM Role
    ROLE_ARN=$(create_lambda_role)
    echo ""
    
    # 2. Упаковываем проект
    ZIP_FILE=$(package_lambda)
    echo ""
    
    # 3. Деплоим Lambda
    deploy_lambda "$ZIP_FILE" "$ROLE_ARN"
    echo ""
    
    # 4. Настраиваем расписание
    setup_schedule
    echo ""
    
    echo "=========================================="
    echo "✅ ДЕПЛОЙ ЗАВЕРШЁН!"
    echo "=========================================="
    echo ""
    echo "📋 Информация:"
    echo "   Function: $FUNCTION_NAME"
    echo "   Region:   $REGION"
    echo "   Schedule: каждые 15 минут (8:00-22:00 UTC)"
    echo ""
    echo "⚙️  Следующие шаги:"
    echo "   1. Заполните Environment Variables в Lambda Console:"
    echo "      https://${REGION}.console.aws.amazon.com/lambda/home?region=${REGION}#/functions/${FUNCTION_NAME}"
    echo ""
    echo "   Нужные переменные:"
    echo "      TELEGRAM_BOT_TOKEN=..."
    echo "      TELEGRAM_CHAT_ID=..."
    echo "      CRM_LOGIN_WARSAW=..."
    echo "      CRM_PASSWORD_WARSAW=..."
    echo "      CRM_LOGIN_BERLIN=..."
    echo "      CRM_PASSWORD_BERLIN=..."
    echo ""
    echo "   2. Тестовый запуск:"
    echo "      aws lambda invoke --function-name $FUNCTION_NAME --region $REGION /tmp/response.json"
    echo ""
    echo "💰 Стоимость:"
    echo "   Free Tier: 1M запросов/месяц БЕСПЛАТНО"
    echo "   ~400 запросов/день = ~12k/месяц = БЕСПЛАТНО ✅"
    echo "   После Free Tier: ~$0.20/млн запросов"
    echo ""
    echo "⚠️  ВАЖНО: Playwright в Lambda требует специальный Layer!"
    echo "   Нужно добавить Playwright Layer в Lambda Console:"
    echo "   Configuration → Layers → Add a layer"
    echo ""
    echo "   Или используйте готовый:"
    echo "   arn:aws:lambda:${REGION}:123456789012:layer:playwright:1"
    echo ""
}

# Запуск
main

