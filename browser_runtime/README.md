# 浏览器运行时原型

独立宿主服务，支持 Google Chrome 普通/无头运行、持久化资料、实时画面和人工接管。默认使用普通模式（`headless: false`）。已接入 HayBot 后台的登录、Bot 工作台和 HTTP/WebSocket 中继；模型任务循环与 QQ 浏览器指令仍在后续阶段。安卓工作台暂时保留。

当前实现和实机验收范围为 **macOS arm64**。macOS Intel 有架构检查分支，未实测；Windows/Linux 只有安装路径发现，身份和启动流程尚未实现，会阻断启动。

## 启动

前置条件：Node >=20、官方 Google Chrome 稳定版。缺少 Chrome 时，页面提供 [Google 中国安装入口](https://www.google.cn/chrome/)，由用户安装后重新检测。不会安装 Playwright Chromium 或改用其他浏览器。

在项目根目录运行：

```sh
npm --prefix browser_runtime ci --ignore-scripts
npm --prefix browser_runtime start
```

访问 `http://127.0.0.1:17322/`，将本机 `.browser-runtime/token` 中的访问码填入连接表单。终端只显示访问码文件路径，不显示内容。重启服务后需要重新连接。

进入页面自动检查宿主、Node、工作目录、Chrome 产品/Google 签名/架构和真实隐藏启动连接。通过后检测项收起。选择原型 A/B，点击启动、接管，再打开“测试页”。可在画面内点击、滚动、拖动、滑动、键盘输入；中文也可通过画面下方输入框发送。支持标签管理、放大查看和 Esc 收起。

画面操作默认为“自动”：鼠标按住移动对应网页原生拖动（滑块、文字选取、拖动控件），触摸按住移动对应滚动页面；滚轮/触控板在鼠标所在的网页位置滚动，也支持内部独立滚动区域和横向滚动。选“滑动”可用鼠标按住上下/左右推来滚页；选“拖动”可强制让触摸操作拖动控件。滑动模式转为桌面网页滚轮事件，不模拟远端移动浏览器的多点触摸或缩放。

画面边缘黑边不会触发输入；按住后移出画面仍可松开。失焦、隐藏页面、切换标签、退出接管或断线均取消手势；后端也为中断手势设置超时释放。移动和滚轮事件合并待处理数据，防止慢网络下动作无限排队。

接管绑定当前画面连接；断线会撤销权限，重连后需重新接管。结束接管保留浏览器；停止关闭本服务拥有的浏览器进程，保留独立资料。Ctrl+C 正常退出服务并关闭所拥有的会话。不会连接或关闭用户日常 Chrome。

可选环境变量：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `HAYBOT_BROWSER_PORT` | `17322` | 本机开发端口 |
| `HAYBOT_BROWSER_DATA` | 项目 `.browser-runtime/` | 私有访问码及 `profiles/{sessionId}` 资料目录 |

数据目录已加入 Git 忽略。请勿上传访问码、Cookie、资料目录。原型 A/B 是合成验收资料，不代表两个正式 Bot。

## 接入正式后台

宿主运行时仍在用户系统中启动，Chrome 不安装到 Docker。后台只负责鉴权和转发。在项目私有 `.env` 添加以下变量（不要把真实访问码写入仓库）：

```dotenv
BROWSER_RUNTIME_URL=http://host.docker.internal:17322
BROWSER_RUNTIME_TOKEN=填写本机.browser-runtime/token的内容
```

如果后台直接运行在宿主，地址使用 `http://127.0.0.1:17322`。后台转发时默认发送 `Host: 127.0.0.1:端口`；自定义宿主代理地址时可用 `BROWSER_RUNTIME_HOST` 明确指定服务允许的 Host。WebSocket 的 TCP 连接目标使用配置的地址，握手 Host 使用允许值，不重复发送 Host。仍仅监听 loopback，不开放 Chrome 调试端口。

应用新配置需要重建/重启后台。登录 HayBot 后，从左侧“浏览器工作台”进入；页面自动检测执行宿主，Chrome 缺失时显示中国官网安装入口。环境通过后，启动、接管，输入完整网页地址即可操作。地址和访问码只配置在服务端，管理页面无需再次填写访问码。

每个已登记且未归档的 Bot 固定使用 `bot-{bot_id}` 会话和独立持久化资料，客户端不能另选 sessionId。画面连接、租约和操作均绑定同一个 Bot 及当前管理登录；页面断开或退出登录会撤销控制。归档 Bot 时先停止对应浏览器，资料保留。

### 普通模式与实验性无头模式

2026-10-29 按用户最新要求，普通模式为默认值：`headless: false`，可能显示 Chrome 窗口、Dock/任务栏入口。此前原型中的“始终隐藏”约束不再适用于默认模式。已有会话不热切换，新代码启动会话时读取当前 Bot 的设置；没有显式设置的旧资料也默认普通模式。

正式工作台的“实验性功能 → 无头模式（headless）”允许选择 `headless: true`。开启前弹窗明确说明：隐藏浏览器窗口，但可能发生网站访问异常、额外登录验证、风控或账号访问受限，不保证解决小红书 300012。取消弹窗不保存；确认后才发送 `acknowledgeHeadlessRisk: true`，后端和宿主均校验。两种模式共用实时帧与接管通路，均支持放大、点击、滚动、拖动及输入。

设置只在停止状态可修改，按 Bot 保存在私有 `settings/{sessionId}.json`，下次启动生效；不强制重启当前会话。同一个 Bot 始终使用原来的持久化资料和登录隔离标记，不清除 Cookie。不同 Bot 设置互不影响。环境检测的短暂启动探针仍使用无头模式，普通模式真实启动失败时不会静默回退无头模式。

小红书域名的错误 URL `error_code=300012` 或错误页面文字会显示访问异常提示，建议停止自动重试、在普通 Chrome 检查同一网络。无头模式额外提示可停用后手动检查；普通模式提示排查网络或稍后再试。提示只表示观测到错误，不能确定是 IP、账号还是浏览器特征导致；不会自动更改 UA、加 stealth 或伪造指纹，不自动重试。模型观察遇到此错误返回 `site_access_blocked`；当前尚无自主浏览器任务循环或 QQ 错误通知。

“主人登录”必须先接管。开启后阻断 ARIA/模型观察，手动画面仍可使用；退出接管、关闭页面、停止或重启浏览器都不会自动解除隔离。请离开密码/验证码页面后点击“完成登录”，确认解除。接管期间也阻断模型观察，观察过程中发生接管或页面变化会丢弃已捕获结果。此阶段没有模型/QQ 读取截图的入口。

## 接口与边界

只监听 `127.0.0.1`；HTTP 使用 Bearer 访问码或交换得到的 HttpOnly/SameSite Strict Cookie。Host 与 Origin 必须匹配服务本机地址。不会开放 Chrome 调试 TCP 端口，驱动通过进程管道连接。

| 接口 | 用途 |
| --- | --- |
| `POST /api/connect` | Bearer 换取进程有效期内的网页 Cookie |
| `GET /api/health` | 鉴权连接检查 |
| `GET/POST /api/environment` | 缓存检测/主动重新检测 |
| `GET /api/sessions/{id}` | 会话状态、标签与画面版本 |
| `POST /api/sessions/{id}/start`、`stop` | 幂等启动/停止 |
| `GET/POST /api/sessions/{id}/settings` | 读取/保存启动模式，仅停止时保存；无头模式需显式风险确认 |
| `POST /api/sessions/{id}/claim`、`release` | 绑定实时连接的操作租约 |
| `POST /api/sessions/{id}/action` | 有限的导航、标签、坐标、滚动、pointer 手势和文字/按键操作 |
| `GET /api/sessions/{id}/observe` | 当前页有限长度 ARIA 快照 |
| `POST /api/sessions/{id}/login/begin`、`login/finish` | 持当前租约开启/解除持久化登录隔离 |
| `WS /api/sessions/{id}/live` | 只读状态和 JPEG 画面；初始状态返回 connectionId |

动作必须携带当前 `lease/generation/tabId`；执行队列实际执行前再次校验。导航、切换标签和接管使旧输入失效，失败的动作不自动重试。`claim` 需要同一会话仍在线的 `connectionId`。

`pointer` 动作使用同一 `gestureId`，分为 `start/move/end/cancel`；`start` 额外指定 `mode: drag|swipe`，除 cancel 外均带 viewport CSS 坐标 `x/y`。`scroll` 可携带 `x/y`，先移动到实际目标再转发滚轮。原型没有任意脚本执行接口。

多个查看端共享一次活动页采集，慢端丢弃帧；前端只解码最新待处理帧。当前采用 JSON/base64 便于原型验证，尚未做慢网络长时压力、CPU/带宽基准和跨域复杂页面验收。

17322 上仍保留直接访问宿主服务的开发页面；正式工作台走 HayBot 管理登录和 Bot 中继。现有后台为单个管理员账号，不包含多个管理员之间的租户分权。没有向 QQ 群友暴露浏览器控制、观察或截图入口。模型执行循环、QQ 浏览器回传、声音获取及真实站点评论任务尚未接入。

## 验证

```sh
npm --prefix browser_runtime test
npm --prefix browser_runtime run test:chrome
```

第一条覆盖环境阻断、鉴权、旧输入和分包中文。第二条启动真实本机 Chrome，使用临时目录与本地合成网页，结束后清理测试目录。仅 macOS 执行，需要 Xcode 命令行工具编译只读原生进程检查器；其他系统跳过。它只会终止测试临时目录明确归属的 Chrome 进程，用于崩溃恢复验收。

实测结果与未完成项见 [PROTOTYPE.md](../design/browser-runtime-20261028/PROTOTYPE.md)。

正式后台接入与验收见 [WORKBENCH.md](../design/browser-runtime-20261028/WORKBENCH.md)。
