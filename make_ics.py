# -*- coding: utf-8 -*-
"""把 all_works.json 转成订阅用的 ICS（定时版，相对提醒），并推送到 GitHub Pages。"""
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from build_ics import DONE_STATUS, build_vevent, render, verify_ics

BASE = Path(__file__).resolve().parent
CST = timezone(timedelta(hours=8))
OUT = BASE / "ucas-homework-timed.ics"

# 必须与用户已订阅的那份保持一致的 UID 前缀与日历名，否则会重复堆叠
UID_PREFIX = "ucas-work-timed"
CALNAME = "国科大作业"


def parse_dt(s):
    for f in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), f).replace(tzinfo=CST)
        except ValueError:
            continue
    return None


def build(works, out_path):
    vevents, skipped = [], 0
    for w in works:
        if w["status"] in DONE_STATUS:
            skipped += 1
            continue
        dl = parse_dt(w.get("deadline", ""))
        if not dl:
            skipped += 1
            continue
        vevents.append({
            "work_id": w["work_id"],
            "uid_prefix": UID_PREFIX,
            "summary": "[作业] %s" % w["title"],
            "desc": "\n".join([
                "课程：%s" % w["course"],
                "截止：%s" % dl.strftime("%Y-%m-%d %H:%M"),
                "状态：%s" % w["status"],
                "作业ID：%s" % w["work_id"],
            ]),
            "all_day": False,
            "dt_start": dl.strftime("%Y%m%dT%H%M%S"),
            "dt_end": (dl + timedelta(hours=1)).strftime("%Y%m%dT%H%M%S"),
            "alarms": [
                {"relative": "-P3D",
                 "text": "3 天后截止（%s %s）：%s" % (dl.strftime("%m-%d"), dl.strftime("%H:%M"), w["title"])},
                {"relative": "-P1D",
                 "text": "明天 %s 截止：%s" % (dl.strftime("%H:%M"), w["title"])},
                {"relative": "-PT3H",
                 "text": "3 小时后截止（%s）：%s" % (dl.strftime("%H:%M"), w["title"])},
            ],
        })

    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//UCAS Homework Bridge//CN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:%s" % CALNAME,
        "X-WR-TIMEZONE:Asia/Shanghai",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    for ev in vevents:
        lines += build_vevent(ev)
    lines.append("END:VCALENDAR")

    out_path.write_bytes(render(lines).encode("utf-8"))
    print("写入日历 %d 条（跳过 %d 条已完成/无截止）" % (len(vevents), skipped))
    verify_ics(out_path)
    return len(vevents)


def push():
    p = subprocess.run([sys.executable, str(BASE / "push_feeds.py")], capture_output=True)
    print((p.stdout + p.stderr).decode("utf-8", "ignore"))


if __name__ == "__main__":
    args = sys.argv[1:]
    # --out <路径>：指定输出文件（云端写进仓库里的订阅文件名）
    out = Path(args[args.index("--out") + 1]) if "--out" in args else OUT
    # 默认不推送；本地手动跑时用 --push 走 gh API
    do_push = "--push" in args

    works = json.loads((BASE / "all_works.json").read_text(encoding="utf-8"))
    for w in works:
        print("  %-44s -> %s" % (w["title"][:44], w.get("deadline")))
    print()
    n = build(works, out)
    if n and do_push:
        push()
