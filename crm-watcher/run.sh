#!/bin/bash
set -euo pipefail
cd /Users/ivanshyla/OrdersToTelegram/crm-watcher
source ./.venv/bin/activate
/usr/bin/env caffeinate -i python check_and_notify.py >> run.log 2>&1
