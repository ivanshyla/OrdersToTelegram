#!/bin/bash
set -euo pipefail

# Получаем абсолютный путь к директории скрипта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Активируем виртуальное окружение с абсолютным путем  
source "$SCRIPT_DIR/.venv/bin/activate"

# Проверяем что Python доступен
if ! command -v python &> /dev/null; then
    echo "ERROR: Python not found in venv" >> run_multi.log
    exit 1
fi

# Записываем время запуска
echo "=== $(date): Starting multi-CRM monitoring ===" >> run_multi.log

# Держим мак бодрым, пока скрипт идёт
/usr/bin/env caffeinate -i python multi_crm_monitor.py >> run_multi.log 2>&1

# Записываем время завершения  
echo "=== $(date): Multi-CRM monitoring completed ===" >> run_multi.log



