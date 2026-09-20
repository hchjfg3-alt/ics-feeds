# -*- coding: utf-8 -*-
"""
国科大在线作业全量同步（端到端）。

链路（已实测打通）：
  1. GET /courselist/coursedata        -> 全部已开课程 (cid, classid, cpi, ckenc, cname)
  2. GET /courselist/opencoursenewfy   -> 课程门户页 -> workEnc / openc
  3. GET /mooc-ans/mooc2/work/list     -> 作业条目 (workId, 标题, 状态, 剩余时间)
     （旧接口 /mooc-ans/work/getAllWork 已被平台停用，返回"无权限"）

截止时刻 = 抓取时刻 + 剩余时间（列表页只给相对时间，误差约 ±2 分钟）。
"""
import gzip
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from build_ics import DONE_STATUS, build_vevent, render, verify_ics

BASE = Path(__file__).resolve().parent

# 凭据来源：优先环境变量（GitHub Actions Secrets），回落到本地文件（本地调试）
COOKIE = os.environ.get("UCAS_COOKIE", "").strip()
if not COOKIE:
    COOKIE = re.sub(r"\s+", " ",
                    (BASE / ".secrets" / "cookie.txt").read_text(encoding="utf-8").strip())
if not COOKIE:
    print("!! 没有可用凭据：请设置环境变量 UCAS_COOKIE 或提供 .secrets/cookie.txt")
    sys.exit(1)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36 Edg/153.0.0.0")
CST = timezone(timedelta(hours=8))
MAIN = "https://mooc.ucas.edu.cn"
APP = "https://mooc.mooc.ucas.edu.cn"


def dec(d, e):
    e = (e or "").lower()
    if "gzip" in e:
        return gzip.GzipFile(fileobj=io.BytesIO(d)).read()
    if "deflate" in e:
        return zlib.decompress(d, -zlib.MAX_WBITS)
    return d


def get(url, referer):
    req = urllib.request.Request(url, headers={
        "Cookie": COOKIE, "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate", "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": referer, "Upgrade-Insecure-Requests": "1",
    })
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, dec(r.read(), r.headers.get("Content-Encoding")).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        print("   [warn] %s: %s" % (type(e).__name__, e))
        return 0, ""


def a_hidden(html, name):
    m = (re.search(r'id="%s"[^>]*value="([^"]*)"' % name, html)
         or re.search(r'name="%s"[^>]*value="([^"]*)"' % name, html))
    return m.group(1) if m else ""


def fetch_courses():
    st, body = get(MAIN + "/courselist/coursedata"
                         "?courseType=0&sectionId=0&columnId=0&fid=0"
                         "&classifyId=0&selfbuild=0&isjwkc=0",
                   MAIN + "/courselist/mycourse")
    if st != 200:
        print("!! 课程列表请求失败 HTTP", st)
        return []
    out = []
    for c in re.findall(r"<li[^>]*class=\"[^\"]*zmy_item[^\"]*\"[^>]*>", body):
        def a(k):
            m = re.search(r"\b" + k + r'\s*=\s*"([^"]*)"', c)
            return m.group(1) if m else ""
        if a("cid"):
            out.append({"cid": a("cid"), "cname": a("cname"), "classid": a("classid"),
                        "cpi": a("cpi"), "ckenc": a("ckenc")})
    return out


def parse_remaining(text):
    """'剩余165小时16分钟' -> timedelta"""
    t = text.replace(" ", "")
    h = re.search(r"(\d+)小时", t)
    mi = re.search(r"(\d+)分钟", t)
    d = re.search(r"(\d+)天", t)
    td = timedelta(0)
    if d:
        td += timedelta(days=int(d.group(1)))
    if h:
        td += timedelta(hours=int(h.group(1)))
    if mi:
        td += timedelta(minutes=int(mi.group(1)))
    return td


def fetch_works(course, now):
    """成功返回作业列表（可能为空列表）；失败返回 None。"""
    cid, cls, cpi, ckenc = course["cid"], course["classid"], course["cpi"], course["ckenc"]
    open_url = ("%s/courselist/opencoursenewfy?role=3&courseId=%s&clazzId=%s&cpi=%s&ckenc=%s"
                % (MAIN, cid, cls, cpi, ckenc))
    st, portal = get(open_url, MAIN + "/courselist/mycourse")
    if st != 200:
        print("   !! 门户页失败 HTTP %s" % st)
        return None
    work_enc, openc = a_hidden(portal, "workEnc"), a_hidden(portal, "openc")
    if not work_enc:
        print("   !! 没拿到 workEnc")
        return None

    list_url = ("%s/mooc-ans/mooc2/work/list?courseId=%s&classId=%s&cpi=%s&ut=s&enc=%s&openc=%s&mooc=1"
                % (APP, cid, cls, cpi, work_enc, openc))
    st, body = get(list_url, open_url)
    if st != 200:
        print("   !! 作业列表失败 HTTP %s" % st)
        return None

    works = []
    for li in re.findall(r"<li[^>]*onclick=\"goTask\(this\);[^\"]*\"[^>]*>.*?</li>", body, re.S):
        wm = re.search(r"workId=(\d+)", li)
        tm = re.search(r'<p class="overHidden2[^"]*">([^<]*)</p>', li)
        sm = re.search(r'<p class="status[^"]*">([^<]*)</p>', li)
        dm = re.search(r'<div class="time[^"]*"[^>]*>\s*(?:<img[^>]*>\s*)?([^<]*)</div>', li)
        if not wm:
            continue
        title = (tm.group(1) if tm else "").strip()
        status = (sm.group(1) if sm else "").strip()
        remain_raw = (dm.group(1) if dm else "").strip()
        # 截断到整分钟：列表页只给"小时+分钟"，秒级误差会让每天重算的结果抖动；
        # 截断后既稳定又更接近真实截止时刻（真实值通常落在整分钟上）
        dl = (now + parse_remaining(remain_raw)).replace(second=0, microsecond=0) if remain_raw else None
        works.append({"work_id": wm.group(1), "title": title, "status": status,
                      "remain_raw": remain_raw,
                      "deadline": dl.strftime("%Y-%m-%d %H:%M") if dl else ""})
    return works


def main():
    now = datetime.now(CST)
    print("抓取时刻（东八区）:", now.strftime("%Y-%m-%d %H:%M:%S"))

    courses = fetch_courses()
    if not courses:
        print("!! 课程列表为空 —— 极可能是 Cookie 已失效，需要重新获取")
        sys.exit(1)
    print("课程数：%d" % len(courses))
    for c in courses:
        print("   %-9s %s" % (c["cid"], c["cname"]))

    all_works = []
    failed = 0
    for i, c in enumerate(courses, 1):
        print("\n[%d/%d] %s" % (i, len(courses), c["cname"]))
        ws = fetch_works(c, now)
        if ws is None:
            failed += 1
            continue
        for w in ws:
            w["course"] = c["cname"]
            w["course_id"] = c["cid"]
        print("   作业 %d 条" % len(ws))
        for w in ws:
            print("      - %-42s %-6s %s" % (w["title"][:42], w["status"], w["remain_raw"]))
        all_works += ws

    if failed == len(courses):
        print("!! 所有课程都抓取失败 —— 极可能是 Cookie 已失效，需要重新获取")
        sys.exit(1)
    if failed:
        print("\n!! 有 %d/%d 门课抓取失败（其余正常）" % (failed, len(courses)))

    (BASE / "all_works.json").write_text(
        json.dumps(all_works, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n合计作业 %d 条，已保存 all_works.json" % len(all_works))
    return all_works


if __name__ == "__main__":
    main()
