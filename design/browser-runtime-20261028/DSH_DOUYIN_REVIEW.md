# dsh_douyin_tools 源码研究

研究日期：2026-10-29。研究对象：`kdcadmin/dsh_douyin_tools`，提交 `02880589e9dfd13f55384c2fd8458785b572e9ed`（2026-10-27）。只读研究源码；没有安装或运行该项目。

## 结论

可以借鉴它的静音参数、平台工具、结果核验、任务互斥和媒体分析方式。但该版本不能证明已经实现“macOS 有界面 Chrome 始终隐藏、没有 Dock 图标、不抢焦点，同时保持实时查看和接管”。

隔离实验表明，它的屏幕外启动参数在本机没有隐藏窗口。因此不应直接复制参数并宣称解决当前弹窗问题。

## 浏览器启动的三条路径

1. 默认持久资料路径：Python 默认 `DOUYIN_HEADLESS=1`；宿主平时也传入 `1`，有验证码标记才传入 `0`。这条路径的启动参数没有 `--mute-audio` 和屏幕外窗口坐标。
2. 可选独立进程路径：仅在 `DOUYIN_DETACHED=1` 等条件满足时使用。启动有界面 Chrome，带 `--mute-audio`、`--window-size=1440,900`、`--window-position=-32000,-32000`，再通过 CDP 连接。Windows 使用的进程分离标志不能据此解释为隐藏 Chrome 图形窗口。
3. 用户 Chrome 的 CDP 路径：配置连接地址后复用已登录浏览器；其辅助启动函数会使用个人默认资料目录。这不符合我们按 Bot 隔离资料的选择。

README 中 `dy_run mode: headless` 指 DSH 模型子会话，与 Chrome 的 `headless` 是两回事。

源码中的历史注释对 headed/headless 是否影响评论区有互相矛盾的描述，不能将这些注释视为当前网站或不同系统的验证结论。

来源：

- [宿主的 Chrome 模式选择](https://github.com/kdcadmin/dsh_douyin_tools/blob/02880589e9dfd13f55384c2fd8458785b572e9ed/index.js#L517-L540)
- [Python 默认值](https://github.com/kdcadmin/dsh_douyin_tools/blob/02880589e9dfd13f55384c2fd8458785b572e9ed/vendor/douyin-mcp/mcp_server.py#L79-L88)
- [独立 Chrome 启动](https://github.com/kdcadmin/dsh_douyin_tools/blob/02880589e9dfd13f55384c2fd8458785b572e9ed/vendor/douyin-mcp/mcp_server.py#L228-L270)
- [浏览器管理与启动分支](https://github.com/kdcadmin/dsh_douyin_tools/blob/02880589e9dfd13f55384c2fd8458785b572e9ed/vendor/douyin-mcp/mcp_server.py#L293-L405)
- [个人 Chrome 辅助启动](https://github.com/kdcadmin/dsh_douyin_tools/blob/02880589e9dfd13f55384c2fd8458785b572e9ed/index.js#L1400-L1455)

## 本机隔离实验

环境：macOS arm64，官方 Google Chrome 156.0.8078.73，项目现有 Playwright。使用系统临时目录内的新资料，合成页面，不访问平台，不操作现有 Bot 会话。结束后关闭测试浏览器并删除资料。

在现有 Playwright 持久资料启动方式上增加该库独立路径的三个参数：

```text
--mute-audio
--window-size=1440,900
--window-position=-32000,-32000
```

| 操作 | CDP 实际窗口位置 | macOS 状态 |
| --- | --- | --- |
| 启动 | left=0, top=33, normal | active=true，visibleWindowCount=1，activationPolicy=0 |
| 同页导航 | left=0, top=33, normal | 仍在前台且有可见窗口 |
| 创建新标签页 | left=0, top=33, normal | 仍在前台且有可见窗口 |
| 显式 bringToFront | left=0, top=33, normal | 仍在前台且有可见窗口 |

同一个测试中，不显式调用 `bringToFront`，页面输入成功，CDP screencast 收到 6 帧。说明实时采集与文本输入不要求这次显式激活调用，但不证明任意站点、后台视频、弹窗均可正常工作。

该实验复用了它的参数，没有完整执行其 Python 裸进程/CDP 启动分支，也没有在 Windows/Linux 上验证。不能把这个结果推广为所有启动方式都无效。

没有做系统音频回录；本轮不声称已完成静音的听觉验收。

## 更值得借鉴的执行方式

- 平台工具返回结构化信息：搜索、推荐流、视频详情、评论、点赞、私信等分别实现；不是让模型完全依靠截图坐标猜测。
- `Net` 监听页面实际产生的 JSON 网络响应，辅助获取视频信息、搜索结果和发布回执。有些读取路径也会在页面上下文请求接口，因此不能概括为“全部只是被动监听”。
- 评论仍通过页面编辑器输入和提交。优先以发布回执的 CID、视频 ID、父评论 ID 校验；无回执则尝试列表/页面回读，最后返回 `unknown`，不自动重发。它的部分 DOM 文本回读证据较弱，我们应优先核验账号、目标和平台对象 ID。
- `withActionLock` 按资料目录串行执行动作，并使用进程间文件锁，避免多个会话同时操作同一账号。
- “看片”使用媒体获取、抽帧、音轨转写，带时长预算和 `partial` 标记，避免只看标题就声称看完。实际返回结果以转写文本等元数据为主；不能因此认定每轮模型都看到了抽取的全部帧。
- 浏览器生命周期与短任务分离，减少任务进程退出导致浏览器关闭。我们已有独立 runtime，可保留现有结构。

来源：

- [网络响应采集](https://github.com/kdcadmin/dsh_douyin_tools/blob/02880589e9dfd13f55384c2fd8458785b572e9ed/vendor/douyin-mcp/mcp_server.py#L701-L778)
- [评论提交及核验](https://github.com/kdcadmin/dsh_douyin_tools/blob/02880589e9dfd13f55384c2fd8458785b572e9ed/vendor/douyin-mcp/mcp_server.py#L1901-L1966)
- [任务锁与成功判定](https://github.com/kdcadmin/dsh_douyin_tools/blob/02880589e9dfd13f55384c2fd8458785b572e9ed/lib/actions.mjs#L1-L52)
- [媒体分析流程](https://github.com/kdcadmin/dsh_douyin_tools/blob/02880589e9dfd13f55384c2fd8458785b572e9ed/vendor/douyin-mcp/mcp_server.py#L2843-L3003)

## 对 HayBot 的建议

第一步先解决日常干扰：独立 Chrome 默认静音；切换工作台标签页时避免不必要的 `bringToFront`。新标签页、站点弹出窗口仍需单独验证和处理，不能承诺只删一行就彻底解决。

窗口隐藏应独立于 `headless` 模式设计，并按操作系统验收。屏幕外坐标、进程分离、最小化都不能等同于隐藏窗口/移除 Dock 图标。继续保留用户已经选择的 headed 默认值，以及两种模式下相同的实时查看、放大、拖动和接管能力。

后续自主任务采用“模型决定目标与选择内容，平台适配器执行操作并返回证据”。平台适配器负责读 ID、解析页面状态、检查真实 @、核验评论与分享，不规定模型必须依次选第几个视频。结构识别失败时回到观察和探索。

不照搬个人默认 Chrome 资料、单一共享账号资料、`--remote-allow-origins=*`，或在整个共享上下文按数量关闭标签页的做法。该库的 `_sweep_tabs` 会遍历上下文标签页，不能直接用于用户的个人浏览器。

本次没有修改产品代码、运行模式或部署。

项目采用 [MIT License](https://github.com/kdcadmin/dsh_douyin_tools/blob/02880589e9dfd13f55384c2fd8458785b572e9ed/LICENSE)；若后续复制实质代码，需要保留对应版权和许可声明。
