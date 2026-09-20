# -*- coding: utf-8 -*-
"""
解析超星泛雅平台（国科大在线 mooc.mooc.ucas.edu.cn）的作业页面 HTML。
输入：作业页面 HTML（"我的作业"标签页）
输出：结构化作业列表 JSON

平台已在 HTML 中确认：_CP_ = "/mooc-ans"，引用 fanya.js（超星泛雅）
"""
import re
import json
import sys
from pathlib import Path


def clean(text):
    if text is None:
        return None
    # 去掉多余空白（HTML 里有大量制表符和换行）
    return re.sub(r"\s+", " ", text).strip()


def parse_works(html: str) -> list:
    """从作业页面 HTML 中提取所有作业条目。"""
    works = []

    # 优先只在"列表内容开始/结束"注释之间查找，避免误匹配页面其它区域的 li
    zone_match = re.search(r"<!--列表内容开始-->(.*?)<!--列表内容结束-->", html, re.S)
    zone = zone_match.group(1) if zone_match else html

    # 每个作业包裹在一个 <li style="padding:30px 0"> 里
    for block in re.findall(r'<li\s+style="padding:30px 0">(.*?)</li>', zone, re.S):
        # 作业链接：class="inspectTask"、data="作业ID"、title="完整作业名"
        # 注意：页面上显示的名字被省略号截断，完整名字只在 title 属性里
        link = re.search(
            r'class="inspectTask"[^>]*?data="(\d+)"[^>]*?title="([^"]*)"',
            block,
            re.S,
        )
        if not link:
            continue

        work_id = link.group(1)
        title = clean(link.group(2))

        start = re.search(r"开始时间：</span>([\d\-: ]+)", block)
        deadline = re.search(r"截止时间：</span>([\d\-: ]+)", block)
        status = re.search(
            r"作业状态：</span>\s*<strong>\s*([^<]+?)\s*</strong>", block, re.S
        )

        works.append(
            {
                "work_id": work_id,
                "title": title,
                "start": clean(start.group(1)) if start else None,
                "deadline": clean(deadline.group(1)) if deadline else None,
                "status": clean(status.group(1)) if status else None,
            }
        )

    return works


def extract_course_ctx(html: str) -> dict:
    """从页面 JS 变量里提取课程上下文，用于拼接接口地址。"""
    def grab(pattern):
        m = re.search(pattern, html)
        return clean(m.group(1)) if m else None

    return {
        "host": grab(r'_HOST_\s*=\s*"([^"]+)"'),
        "cp": grab(r'_CP_\s*=\s*"([^"]+)"'),
        "courseId": grab(r"var courseId\s*=\s*(\d+)"),
        "classId": grab(r"var classId\s*=\s*(\d+)"),
        "cpi": grab(r"var cpi\s*=\s*(\d+)"),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python parse_work.py <作业页面.html>")
        sys.exit(1)

    path = Path(sys.argv[1])
    html = path.read_text(encoding="utf-8", errors="ignore")

    ctx = extract_course_ctx(html)
    works = parse_works(html)

    print("=== 课程上下文 ===")
    print(json.dumps(ctx, ensure_ascii=False, indent=2))
    print("\n=== 作业列表 ===")
    print(json.dumps(works, ensure_ascii=False, indent=2))
    print(f"\n共解析出 {len(works)} 条作业")

    # 未完成作业（用于后续写入日历）
    todo = [w for w in works if w["status"] not in ("已完成", "已批阅", "已交")]
    print(f"其中未完成 {len(todo)} 条")
