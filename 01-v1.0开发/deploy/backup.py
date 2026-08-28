#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkReport HR-Pro 数据库自动备份脚本
用法：每天凌晨由 cron 触发，备份 workreport.db 到 backups/ 目录，保留 180 天。
示例 cron（每天凌晨 2 点）：
  0 2 * * * /usr/bin/python3 /opt/workreport/src/backend/backup.py
"""
import os
import shutil
import glob
from datetime import datetime, timedelta

# 数据库文件路径（请按实际部署路径修改）
DB_PATH = "/opt/workreport/src/workreport.db"
# 备份目录
BACKUP_DIR = "/opt/workreport/backups"
# 保留天数
RETENTION_DAYS = 180


def main():
    if not os.path.exists(DB_PATH):
        print(f"[备份失败] 数据库不存在: {DB_PATH}")
        return

    os.makedirs(BACKUP_DIR, exist_ok=True)

    # 备份文件名：workreport-2026-08-28.db
    today = datetime.now().strftime("%Y-%m-%d")
    dest = os.path.join(BACKUP_DIR, f"workreport-{today}.db")

    # 当天已备份则跳过（避免重复）
    if os.path.exists(dest):
        print(f"[跳过] 今日已备份: {dest}")
    else:
        shutil.copy2(DB_PATH, dest)
        print(f"[完成] 已备份到: {dest}")

    # 清理超过保留期的旧备份
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    for f in glob.glob(os.path.join(BACKUP_DIR, "workreport-*.db")):
        try:
            name = os.path.basename(f)
            date_str = name.replace("workreport-", "").replace(".db", "")
            f_date = datetime.strptime(date_str, "%Y-%m-%d")
            if f_date < cutoff:
                os.remove(f)
                print(f"[清理] 删除过期备份: {name}")
        except (ValueError, OSError):
            continue

    # 统计当前备份数
    count = len(glob.glob(os.path.join(BACKUP_DIR, "workreport-*.db")))
    print(f"[统计] 当前共 {count} 份备份")


if __name__ == "__main__":
    main()
