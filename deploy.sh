#!/bin/bash
set -e  # 出错直接退出

git pull

sudo systemctl restart tianai_capability tianai_capability_reminder_worker