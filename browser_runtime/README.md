# 浏览器运行时原型

独立宿主服务，验证 Google Chrome 隐藏运行、持久化资料、实时画面和人工接管。当前未接入正式 HayBot 后台、Bot 任务或 QQ；8080 上的安卓运行时不受影响。

当前实现和实机验收范围为 **macOS arm64**。macOS Intel 有架构检查分支，未实测；Windows/Linux 只有安装路径发现，身份和启动流程尚未实现，会阻断启动。

## 启动

前置条件：Node >=20、官方 Google Chrome 稳定版。缺少 Chrome 时，页面提供 [Google 中国安装入口](https://www.google.cn/chrome/)，由用户安装后重新检测。不会安装 Playwright Chromium 或改用其他浏览器。

在项目根目录运行：

```sh
npm --prefix browser_runtime ci --ignore-scripts
npm --prefix browser_runtime start
```

访问 `http://127.0.0.1:17322/`，将本机 `.browser-runtime/token` 中的访问码填入连接表单。终端只显示访问码文件路径，不显示内容。重启服务后需要重新连接。

进入页面自动检查宿主、Node、工作目录、Chrome 产品/Google 签名/架构和真实隐藏启动连接。通过后检测项收起。选择原型 A/B，点击启动、接管，再打开“测试页”。可在画面内点击、滚动、键盘输入；中文也可通过画面下方输入框发送。支持标签管理、放大查看和 Esc 收起。

接管绑定当前画面连接；断线会撤销权限，重连后需重新接管。结束接管保留浏览器；停止关闭本服务拥有的浏览器进程，保留独立资料。Ctrl+C 正常退出服务并关闭所拥有的会话。不会连接或关闭用户日常 Chrome。

可选环境变量：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `HAYBOT_BROWSER_PORT` | `17322` | 本机开发端口 |
| `HAYBOT_BROWSER_DATA` | 项目 `.browser-runtime/` | 私有访问码及 `profiles/{sessionId}` 资料目录 |

数据目录已加入 Git 忽略。请勿上传访问码、Cookie、资料目录。原型 A/B 是合成验收资料，不代表两个正式 Bot。

## 接口与边界

只监听 `127.0.0.1`；HTTP 使用 Bearer 访问码或交换得到的 HttpOnly/SameSite Strict Cookie。Host 与 Origin 必须匹配服务本机地址。不会开放 Chrome 调试 TCP 端口，驱动通过进程管道连接。

| 接口 | 用途 |
| --- | --- |
| `POST /api/connect` | Bearer 换取进程有效期内的网页 Cookie |
| `GET /api/health` | 鉴权连接检查 |
| `GET/POST /api/environment` | 缓存检测/主动重新检测 |
| `GET /api/sessions/{id}` | 会话状态、标签与画面版本 |
| `POST /api/sessions/{id}/start`、`stop` | 幂等启动/停止 |
| `POST /api/sessions/{id}/claim`、`release` | 绑定实时连接的操作租约 |
| `POST /api/sessions/{id}/action` | 有限的导航、标签、坐标、滚动和文字/按键操作 |
| `GET /api/sessions/{id}/observe` | 当前页有限长度 ARIA 快照 |
| `WS /api/sessions/{id}/live` | 只读状态和 JPEG 画面；初始状态返回 connectionId |

动作必须携带当前 `lease/generation/tabId`；执行队列实际执行前再次校验。导航、切换标签和接管使旧输入失效，失败的动作不自动重试。`claim` 需要同一会话仍在线的 `connectionId`。

多个查看端共享一次活动页采集，慢端丢弃帧；前端只解码最新待处理帧。当前采用 JSON/base64 便于原型验证，尚未做慢网络长时压力、CPU/带宽基准和跨域复杂页面验收。

这是直接访问宿主服务的开发页面。生产接入仍需经过 HayBot 现有登录、Bot 归属、Owner 权限和后台中继；不能把这个访问码表单当作正式产品权限设计。尚未实现 Owner 登录隔离、模型执行循环、QQ 回传、声音获取或真实站点评论任务。

## 验证

```sh
npm --prefix browser_runtime test
npm --prefix browser_runtime run test:chrome
```

第一条覆盖环境阻断、鉴权、旧输入和分包中文。第二条启动真实本机 Chrome，使用临时目录与本地合成网页，结束后清理测试目录。仅 macOS 执行，需要 Xcode 命令行工具编译只读原生进程检查器；其他系统跳过。它只会终止测试临时目录明确归属的 Chrome 进程，用于崩溃恢复验收。

实测结果与未完成项见 [PROTOTYPE.md](../design/browser-runtime-20261028/PROTOTYPE.md)。
