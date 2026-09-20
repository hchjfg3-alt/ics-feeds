# ics-feeds

个人的日历订阅源（自动生成，勿手动编辑）。

## 内容

- `tjtzt92xdju92mmxxjrg.ics` —— 国科大在线（超星泛雅）未交作业的截止提醒

## 如何运作

`sync_all.py` 登录国科大在线 → 遍历全部已开课程 → 取每门课的作业列表
→ `make_ics.py` 生成 ICS → GitHub Actions 每天两次提交更新 → 日历客户端自动刷新。

## 链路要点

| 步骤 | 接口 |
|------|------|
| 课程列表 | `GET mooc.ucas.edu.cn/courselist/coursedata` |
| 课程门户（取 `workEnc`） | `GET mooc.ucas.edu.cn/courselist/opencoursenewfy?role=3&courseId=&clazzId=&cpi=&ckenc=` |
| 作业列表 | `GET mooc.mooc.ucas.edu.cn/mooc-ans/mooc2/work/list?courseId=&classId=&cpi=&ut=s&enc={workEnc}&openc=` |

- 作业接口的 `enc` **必须用门户页的 `workEnc`**，用页面 `enc` 会返回「无权限的操作！」
- 旧接口 `/mooc-ans/work/getAllWork` 已被平台停用
- 新版列表页只给**相对剩余时间**，故 `截止时刻 = 抓取时刻 + 剩余时间`（截断到整分钟）

## 凭据

通过 `UCAS_COOKIE` 环境变量注入（GitHub Secrets）。本地调试可放 `.secrets/cookie.txt`。
Cookie 约每月过期，届时工作流会失败并发出通知，需重新获取。
