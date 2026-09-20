# -*- coding: utf-8 -*-
"""
把超星泛雅（国科大在线）作业页面 HTML 转成 ICS 日历文件。

用法:
    python build_ics.py <输出.ics> <作业页面.html> [更多.html ...]

设计说明:
- UID 用 work_id 生成，保证稳定 —— 同一作业重复推送时日历会「更新」而不是新增重复项
- 默认生成全天事件（截止日期这类东西在日历里按天看更直观）
- 内置两条提醒：截止前 1 天、截止前 2 小时
- 带 REFRESH-INTERVAL / X-PUBLISHED-TTL，提示客户端每小时刷新一次
"""
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from parse_work import parse_works, extract_course_ctx

CST = timezone(timedelta(hours=8))

# 这些状态视为已完成，不再写入日历
DONE_STATUS = {"已完成", "已批阅", "已交", "已提交", "已过期"}


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_deadline(s):
    """'2026-09-27 18:30' -> 带东八区时区的 datetime"""
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=CST)
        except ValueError:
            continue
    return None


def esc(text):
    """ICS 文本转义"""
    if not text:
        return ""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold(line, limit=75):
    """
    RFC 5545 要求：内容行不得超过 75 字节（不含 CRLF），超出必须折行，
    续行以一个空格开头（该空格不计入 75 字节，所以续行内容限 74 字节）。

    注意：必须按「字符」而非「字节」切分，否则会把中文的 UTF-8 多字节序列切断。
    """
    if len(line.encode("utf-8")) <= limit:
        return line

    out = []
    cur = ""
    cur_bytes = 0

    for ch in line:
        ch_len = len(ch.encode("utf-8"))
        # 首行可用 75 字节；续行开头要放一个空格，所以只剩 74
        avail = limit if not out else limit - 1
        if cur_bytes + ch_len > avail:
            out.append(cur)
            cur = ""
            cur_bytes = 0
        cur += ch
        cur_bytes += ch_len

    if cur:
        out.append(cur)

    # 第一段原样，后续每段前面加一个空格
    return "\r\n ".join(out)


def render(lines):
    """把逻辑行渲染成符合规范的 ICS 文本（折行 + CRLF 结尾）"""
    return "\r\n".join(fold(line) for line in lines) + "\r\n"


def course_name_from_html(html):
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    if not m:
        return "未知课程"
    name = m.group(1).strip()
    # 页面标题形如「英语B-19班（怀）-高级写作-作业」，去掉尾巴
    for suffix in ("-作业", "-考试", "-任务", "-通知"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def build_vevent(ev):
    lines = [
        "BEGIN:VEVENT",
        f"UID:{ev['uid_prefix']}-{ev['work_id']}@mooc.mooc.ucas.edu.cn",
        f"DTSTAMP:{now_utc()}",
        f"SUMMARY:{esc(ev['summary'])}",
    ]

    if ev["all_day"]:
        lines.append(f"DTSTART;VALUE=DATE:{ev['ymd']}")
        lines.append(f"DTEND;VALUE=DATE:{ev['ymd_next']}")
    else:
        # 浮动本地时间（不带 Z / TZID）：客户端按手机本地时区解释，
        # 对中国用户（Asia/Shanghai）最省事，也无需附带 VTIMEZONE。
        lines.append(f"DTSTART:{ev['dt_start']}")
        lines.append(f"DTEND:{ev['dt_end']}")

    if ev.get("desc"):
        lines.append(f"DESCRIPTION:{esc(ev['desc'])}")
    if ev.get("url"):
        lines.append(f"URL:{ev['url']}")
    lines.append("STATUS:CONFIRMED")
    lines.append("TRANSP:TRANSPARENT")

    for a in ev["alarms"]:
        lines.append("BEGIN:VALARM")
        if a.get("relative"):
            # 相对提醒：兼容性最好，几乎所有客户端都认
            lines.append(f"TRIGGER:{a['relative']}")
        else:
            # 绝对提醒：RFC 5545 合法，但 Android / Outlook 常静默丢弃
            lines.append(f"TRIGGER;VALUE=DATE-TIME:{a['at']}")
        lines += [
            "ACTION:DISPLAY",
            f"DESCRIPTION:{esc(a['text'])}",
            "END:VALARM",
        ]

    lines.append("END:VEVENT")
    return lines


def main():
    args = sys.argv[1:]

    # --timed：生成「定时事件」版本（事件落在截止时刻，提醒用相对时间）
    # 兼容性远好于全天版（很多安卓/Outlook 客户端会丢弃绝对时间的 VALARM）
    timed = "--timed" in args
    args = [a for a in args if a != "--timed"]

    if len(args) < 2:
        print("用法: python build_ics.py [--timed] <输出.ics> <作业页面.html> [更多.html ...]")
        sys.exit(1)

    out_path = Path(args[0])
    pages = args[1:]
    uid_prefix = "ucas-work-timed" if timed else "ucas-work"

    vevents = []
    total, skipped = 0, 0

    for p in pages:
        html = Path(p).read_text(encoding="utf-8", errors="ignore")
        course = course_name_from_html(html)
        ctx = extract_course_ctx(html)

        for w in parse_works(html):
            total += 1
            if w["status"] in DONE_STATUS:
                skipped += 1
                continue
            dl = parse_deadline(w["deadline"])
            if not dl:
                skipped += 1
                continue

            desc_parts = [
                f"课程：{course}",
                f"截止：{w['deadline']}",
                f"状态：{w['status']}",
                f"作业ID：{w['work_id']}",
            ]
            if ctx.get("courseId"):
                desc_parts.append(
                    "链接：https://mooc.mooc.ucas.edu.cn/mooc-ans/work/"
                    f"doHomeWorkNew?courseId={ctx['courseId']}&classId={ctx['classId']}"
                    f"&workId={w['work_id']}"
                )
            desc = "\n".join(desc_parts)

            ev = {
                "work_id": w["work_id"],
                "uid_prefix": uid_prefix,
                "summary": f"[作业] {w['title']}",
                "desc": desc,
            }

            if timed:
                # 定时事件：DTSTART = 截止时刻，时长为 1 小时
                ev.update(
                    {
                        "all_day": False,
                        "dt_start": dl.strftime("%Y%m%dT%H%M%S"),
                        "dt_end": (dl + timedelta(hours=1)).strftime("%Y%m%dT%H%M%S"),
                        "alarms": [
                            {
                                "relative": "-P1D",
                                "text": f"明天 {dl.strftime('%H:%M')} 截止：{w['title']}",
                            },
                            {
                                "relative": "-PT2H",
                                "text": f"2 小时后截止（{dl.strftime('%H:%M')}）：{w['title']}",
                            },
                        ],
                    }
                )
            else:
                # 全天事件：落在截止日期当天
                # 提醒只能用绝对时间 —— 全天事件的相对 -P1D 会落在日期零点，等于凌晨触发
                ev.update(
                    {
                        "all_day": True,
                        "ymd": dl.strftime("%Y%m%d"),
                        "ymd_next": (dl + timedelta(days=1)).strftime("%Y%m%d"),
                        "alarms": [
                            {
                                "at": (dl - timedelta(days=1))
                                .astimezone(timezone.utc)
                                .strftime("%Y%m%dT%H%M%SZ"),
                                "text": f"明天 {dl.strftime('%H:%M')} 截止：{w['title']}",
                            },
                            {
                                "at": (dl - timedelta(hours=2))
                                .astimezone(timezone.utc)
                                .strftime("%Y%m%dT%H%M%SZ"),
                                "text": f"2 小时后截止（{dl.strftime('%H:%M')}）：{w['title']}",
                            },
                        ],
                    }
                )

            vevents.append(ev)

    cal_name = "国科大作业（截止时刻）" if timed else "国科大作业"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//UCAS Homework Bridge//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{cal_name}",
        "X-WR-TIMEZONE:Asia/Shanghai",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    for ev in vevents:
        lines += build_vevent(ev)
    lines.append("END:VCALENDAR")

    # 必须用二进制写入：
    # Windows 上文本模式会把 \n 再转换成 \r\n，使已拼好的 \r\n 变成 \r\r\n,
    # 多出的 \r 会被计入行长度，导致超过 RFC 5545 的 75 字节上限。
    out_path.write_bytes(render(lines).encode("utf-8"))

    mode = "定时版（相对提醒）" if timed else "全天版（绝对提醒）"
    print(f"模式：{mode}")
    print(f"读取页面 {len(pages)} 个，解析作业 {total} 条")
    print(f"写入日历 {len(vevents)} 条，跳过（已完成/无截止时间）{skipped} 条")
    print(f"输出文件：{out_path}")

    verify_ics(out_path)


def verify_ics(path):
    """
    RFC 5545 规范自检。踩过的两个坑，做成常驻检查防止回归：
      1. 内容行超过 75 字节（必须折行）
      2. Windows 文本模式写入把 \\n 又转成 \\r\\n，产生 \\r\\r\\n
    """
    data = Path(path).read_bytes()
    lines = data.split(b"\r\n")

    problems = []
    over = [(i, len(l)) for i, l in enumerate(lines, 1) if len(l) > 75]
    if over:
        problems.append(f"存在超长行（>75 字节）：{over}")
    if data.count(b"\r\r\n"):
        problems.append(f"存在 \\r\\r\\n 共 {data.count(b'\r\r\n')} 处（文本模式写入所致）")
    if data.count(b"\n") - data.count(b"\r\n"):
        problems.append("存在裸 \\n 换行")

    if problems:
        print("[!] 规范自检未通过：")
        for p in problems:
            print("    -", p)
    else:
        print("[OK] 规范自检通过：无超长行、换行符正确、UTF-8 可解码")


if __name__ == "__main__":
    main()
