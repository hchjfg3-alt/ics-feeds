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
- 新版列表页只给**相对剩余时间**，故 `截止时刻 = 抓取时刻 + 剩余时间`
  - 平台对剩余时间是**四舍五入到分钟**，所以估算也必须四舍五入（实测标定过）
  - 再用 `deadline_state.json` 固化基线：±2 分钟内沿用旧值，避免抖动导致日历反复变动

## 凭据

通过 `UCAS_COOKIE` 环境变量注入（GitHub Secrets）。本地调试可放 `.secrets/cookie.txt`。

### Cookie 过期了怎么办（约每月一次）

Cookie 失效时工作流会直接失败退出（日志里能看到「课程列表为空 —— 极可能是 Cookie 已失效」），
GitHub 会给仓库所有者发失败通知邮件。恢复步骤：

1. 浏览器登录 <https://mooc.ucas.edu.cn/courselist/mycourse>（**先按 F12 → Network → 勾选 Disable cache**，再 Ctrl+Shift+R 硬刷新）
2. 在 Network 里点名为 `mycourse`（类型 **document**）的请求，复制请求头里的整行 `Cookie: ...`
   - 若看到「Provisional headers are shown」，说明命中了缓存，重复第 1 步
3. 更新 Secret：`gh secret set UCAS_COOKIE --repo hchjfg3-alt/ics-feeds`
4. 手动触发一次：`gh workflow run sync-ucas-homework --repo hchjfg3-alt/ics-feeds`

## 运行时间

每天两次，北京时间 **07:00** 与 **19:00**（Actions 的 cron 用 UTC，故为 `0 23` 与 `0 11`）。

## 维护备忘

- 改动 `.github/workflows/` 下的文件需要 token 带 `workflow` 权限；**用 SSH 推送可绕过**
  （SSH 密钥没有 scope 概念，`git push git@github.com:...` 直接可写，而 HTTPS/Contents API 会 404）
- 定时任务若 60 天无仓库活动会被 GitHub 自动停用（Cookie 每月过期通常先于这个触发，可忽略）
