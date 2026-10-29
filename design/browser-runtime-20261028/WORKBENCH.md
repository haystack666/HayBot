# 浏览器工作台：后台与手动接管

> 2026-10-29 最新模式与平台范围见 [MODES.md](MODES.md)：固定无头，移除小红书专门支持。本文较早的 headed/实验性开关或最小化结论仅作历史记录。

2026-10-29，`feature/browser-runtime`，在原项目 `/Volumes/Samsung2T/PJFiles/hayqqbot` 开发。磁盘短暂离线期间创建的临时恢复副本已不存在；实际改动和验收都在原项目进行。

同日后续新增普通模式默认值和实验性 headless 开关，最新行为与新增验收见 [MODES.md](MODES.md)。下方数字记录工作台首次接入时的验证。

## 实现范围

- 新增后台 `/api/bots/{bot_id}/browser` 状态、环境、生命周期、控制、登录隔离和只读 live 接口。
- 私有宿主地址/访问码由 `BROWSER_RUNTIME_URL`、`BROWSER_RUNTIME_TOKEN` 配置，允许可选 `BROWSER_RUNTIME_HOST`。访问码不传给管理前端。
- 工作台跟随现有管理登录；HTTP 和 WebSocket 都校验来源。后台通过 catalog 查找未归档 Bot，映射固定 `bot-{id}` 会话。控制请求同时校验活跃连接、Bot、管理登录与租约；宿主再次校验租约、tab 与 generation。
- Docker 通过 `host.docker.internal` 连接宿主，Host 保持宿主允许的 loopback 值。WebSocket 使用 canonical URI 和显式 TCP 目标，避免两个 Host 头。
- 前端加入侧栏与功能搜索入口、折叠环境检测、安装入口、画面放大、接管、中文输入、标签操作、拖动/滑动和深浅主题。
- 登录模式在宿主资料目录保存暂停标记，停止/重启或画面断开都不解除。接管与登录期间禁止模型 ARIA 观察；在途观察完成前再次检查隔离和页面版本。完成登录由管理员明确确认。
- 退出管理登录关闭上游连接，宿主撤销连接租约；归档 Bot 先停止对应浏览器。

当前是单管理员后台，没有不同管理员之间的租户隔离。工作台不是 QQ 任务授权：模型任务循环及 QQ 浏览器能力还未接入，两种 QQ 接入均无法通过本次新增接口读页或操控。

## 验收

实际环境：macOS arm64、Node 22.23.4、Google Chrome 156.0.8078.73、Docker 中 Python 3.12.15。使用官方 Chrome，无个人资料；只访问本地合成网页。

| 验收 | 结果 |
| --- | --- |
| 后台浏览器 + Android live + 多 Bot + 应用回归 | 28 项通过，含匿名/来源/未知 Bot 拒绝、跨 Bot 租约拒绝、私有 Host、真实 WS 转发、退出撤销、归档定向停止 |
| 浏览器单元/API | 14 项通过，含在途观察隔离、登录持久化、旧输入拒绝和手势实现同步 |
| 前端现有回归 | 18 项通过 |
| 原型真实 Chrome | 2 项通过：隐藏进程、A/B 资料、崩溃恢复、拖动/滑动/触摸/放大坐标和断开释放 |
| 正式工作台端到端 | 1 项通过：登录管理台→环境检测→启动→接管→导航→滑块拖动→主人登录→停止/重启仍隔离→明确完成→切 Bot→放大/Esc→深浅主题/390px 布局→退出撤销 |
| 前端构建 | 通过；保留现有 jmuxer/stream 和主包体积提示 |

端到端使用独立验收容器 `haybot-browser-workbench-validation`、18081 管理端口、17323 临时宿主、临时 Bot 数据与浏览器资料，未替换 8080 服务。测试自身关闭 Chrome 并清理临时资料；结束后移除验收容器与临时环境文件。

```sh
npm --prefix frontend run build
npm --prefix browser_runtime test
npm --prefix browser_runtime run test:chrome
node --test frontend/tests/*.test.mjs
```

工作台端到端为 opt-in，默认跳过。需先为隔离后台配置 17323 宿主连接；测试从权限 0600 的环境文件读取测试管理密码与运行时 token（不会输出）。不要指向正式后台：

```sh
HAYBOT_WORKBENCH_URL=http://127.0.0.1:18081 \
HAYBOT_WORKBENCH_TEST_ENV=.browser-runtime/workbench-validation.env \
node --test browser_runtime/integration/workbench.test.mjs
```

截图：`prototype/browser-workbench-light.png`、`prototype/browser-workbench-dark.png`。

## 后续范围

模型任务循环、Owner 的 QQ 指令授权、任务截图/诊断隔离、进度与通知回执、平台发布去重、未知结果核验和任务收尾仍需继续开发。当前 macOS 结果不代表 Windows/Linux 或 Bilibili/抖音/小红书真实站点验收，也没有新增音频采集能力。
