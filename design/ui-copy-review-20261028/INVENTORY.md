# 前端文案审阅清单

原始编号固定保留；已删除项目标注状态。动态值以〔表达式〕表示。

## 手机 / 初始化与应用

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T001 | 待审阅 | 手机初始化与应用 | 空状态 | 正在读取初始化与应用状态… | frontend/src/AndroidApps.jsx:20:27 |
| T002 | 待审阅 | 手机初始化与应用 | 空状态 | 还没有初始化记录。 | frontend/src/AndroidApps.jsx:21:32 |
| T003 | 待审阅 | 手机初始化与应用 | 说明文字 | 版本 〔app.metadata.version〕 | frontend/src/AndroidApps.jsx:25:33 |
| T004 | 待审阅 | 手机初始化与应用 | 行内说明候选 | 安装 Google 套件 | frontend/src/AndroidApps.jsx:27:190 |
| T005 | 待审阅 | 手机初始化与应用 | 说明文字 | 请先在宿主构建兼容的 Google 系统镜像。 | frontend/src/AndroidApps.jsx:28:96 |
| T006 | 待审阅 | 手机初始化与应用 | 操作反馈与确认 | Via 安装已提交，状态会自动更新 | frontend/src/AndroidApps.jsx:30:239 |
| T007 | 待审阅 | 手机初始化与应用 | 补充文案候选 | 查看 Google 配套要求 | frontend/src/AndroidApps.jsx:31:130 |
| T008 | 待审阅 | 手机初始化与应用 | 说明文字 | 移除桌面上的其他图标、小组件与搜索栏，只保留 Via。 | frontend/src/AndroidApps.jsx:33:283 |
| T009 | 待审阅 | 手机初始化与应用 | 操作反馈与确认 | 桌面整理已提交，完成后可在手机画面中查看 | frontend/src/AndroidApps.jsx:33:601 |
| T010 | 待审阅 | 手机初始化与应用 | 行内说明候选 | 整理桌面，仅保留 Via | frontend/src/AndroidApps.jsx:33:626 |
| T011 | 待审阅 | 手机初始化与应用 → 安装 Google 套件？ | 行内说明候选 | 安装 Google 套件？ | frontend/src/AndroidApps.jsx:34:182 |
| T012 | 待审阅 | 手机初始化与应用 → 安装 Google 套件？ | 弹窗说明 | 这会重启手机并使用本地已构建的兼容镜像，包含 Google 服务框架、Play 服务和 Play 商店。手机数据和账号保留，Google 账号由 owner 自行登录。 | frontend/src/AndroidApps.jsx:34:210 |
| T013 | 待审阅 | 手机初始化与应用 → 安装 Google 套件？ | 操作反馈与确认 | Google 套件安装已提交，手机会重新开机 | frontend/src/AndroidApps.jsx:34:648 |

## 手机 / 任务设置 / 浏览兴趣与公开互动

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T014 | 待审阅 | AndroidCompanion.jsx | 说明文字 | 按时间采样画面与字幕，没有音频时不推测对白。 | frontend/src/AndroidCompanion.jsx:10:57 |
| T015 | 待审阅 | 主人的兴趣偏好 | 字段说明 | 填写喜欢、不感兴趣和尽量避开的内容；用于挑选适合分享或 @ 你的内容。 | frontend/src/AndroidCompanion.jsx:12:62 |
| T016 | 已删除 2026-10-28 | 角色自己的兴趣 | 字段说明 | 由你填写她喜欢探索的主题；不从人格或评论风格推导。留空时按本次探索浏览，不假设已有喜好。 | frontend/src/AndroidCompanion.jsx:13:66 |
| T017 | 待审阅 | 内容筛选要求 | 字段说明 | 例如：跳过带货、标题党和搬运；优先实际演示。 | frontend/src/AndroidCompanion.jsx:14:65 |
| T018 | 待审阅 | 视频缓冲等待（秒） | 字段说明 | 后台持续观察播放恢复，默认等 120 秒；期间不因两次短等待就换片。 | frontend/src/AndroidCompanion.jsx:15:60 |
| T019 | 待审阅 | 公开评论风格 | 字段说明 | 仅用于公开评论，不会读取私人聊天人格、记忆或日程；原有配置保留。 | frontend/src/AndroidCompanion.jsx:16:60 |
| T020 | 待审阅 | 公开评论风格 | 输入框占位 | 例如：简短自然，结合具体画面，不写套话。 | frontend/src/AndroidCompanion.jsx:16:216 |
| T021 | 待审阅 | AndroidCompanion.jsx | 行内说明候选 | 允许自主评论，无需逐条确认 | frontend/src/AndroidCompanion.jsx:20:43 |
| T022 | 待审阅 | AndroidCompanion.jsx | 行内说明候选 | 看到有意思的内容可以 @ owner | frontend/src/AndroidCompanion.jsx:21:43 |
| T023 | 待审阅 | Bot 登录的平台账号 ID | 补充文案候选 | Bot 登录的平台账号 ID | frontend/src/AndroidCompanion.jsx:22:22 |
| T024 | 待审阅 | Bot 登录的平台账号 ID | 字段说明 | 填写手机里实际发表评论的账号 ID；多个 Bot 使用同一账号时填写相同值，用于跨 Bot 去重。留空兼容原有账号分组。 | frontend/src/AndroidCompanion.jsx:22:76 |
| T025 | 待审阅 | owner 平台账号 ID | 补充文案候选 | owner 平台账号 ID | frontend/src/AndroidCompanion.jsx:23:22 |
| T026 | 待审阅 | owner 平台账号 ID | 字段说明 | 用于核对 @ 候选账号；填该平台真实公开账号 ID。 | frontend/src/AndroidCompanion.jsx:23:65 |
| T027 | 待审阅 | AndroidCompanion.jsx | 提示框 | 仅在已授权的手机任务中互动，不会自行无限刷视频。发布结果不明时不会重复发送。@ 需要实际选中可核对的账号；登录和验证由 owner 完成。 | frontend/src/AndroidCompanion.jsx:28:5 |

## 手机 / 实时画面

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T028 | 待审阅 | AndroidLive.jsx | 操作反馈与确认 | 当前浏览器不支持 H.264 视频，请切换截图模式 | frontend/src/AndroidLive.jsx:41:108 |
| T029 | 待审阅 | AndroidLive.jsx | 补充文案候选 | 视频解码失败，请重新连接或切换截图模式 | frontend/src/AndroidLive.jsx:47:39 |
| T030 | 待审阅 | AndroidLive.jsx | 补充文案候选 | 视频启动超时，请重新连接或切换截图模式 | frontend/src/AndroidLive.jsx:51:106 |
| T031 | 待审阅 | AndroidLive.jsx | 补充文案候选 | 实时连接已结束，请重新连接或切换截图模式 | frontend/src/AndroidLive.jsx:70:67 |
| T032 | 待审阅 | AndroidLive.jsx | 补充文案候选 | 实时画面格式异常，请重新连接 | frontend/src/AndroidLive.jsx:74:24 |
| T033 | 待审阅 | AndroidLive.jsx | 补充文案候选 | 实时连接失败，可重试或切换截图模式 | frontend/src/AndroidLive.jsx:76:31 |
| T034 | 待审阅 | AndroidLive.jsx | 补充文案候选 | 实时连接已结束，重新连接不会重放之前的输入 | frontend/src/AndroidLive.jsx:77:31 |
| T035 | 待审阅 | AndroidLive.jsx | 补充文案候选 | 当前浏览器不支持视频流，请使用截图模式 | frontend/src/AndroidLive.jsx:79:47 |
| T036 | 待审阅 | AndroidLive.jsx | 操作反馈与确认 | 请先重新连接实时画面 | frontend/src/AndroidLive.jsx:91:68 |
| T037 | 待审阅 | AndroidLive.jsx | 补充文案候选 | 已接管 · 实时操作 | frontend/src/AndroidLive.jsx:123:83 |
| T038 | 待审阅 | AndroidLive.jsx | 补充文案候选 | 实时视频 · 观看中 | frontend/src/AndroidLive.jsx:123:121 |
| T039 | 待审阅 | AndroidLive.jsx | 补充文案候选 | 正在缓冲实时画面… | frontend/src/AndroidLive.jsx:123:161 |
| T040 | 待审阅 | AndroidLive.jsx | 补充文案候选 | 正在连接实时画面… | frontend/src/AndroidLive.jsx:123:238 |
| T041 | 待审阅 | AndroidLive.jsx | 说明文字 | H.264 · 最高 30 fps | frontend/src/AndroidLive.jsx:123:258 |
| T042 | 待审阅 | AndroidLive.jsx | 行内说明候选 | 结束操作，继续观看 | frontend/src/AndroidLive.jsx:133:90 |
| T043 | 待审阅 | AndroidLive.jsx | 补充文案候选 | 正在接管… | frontend/src/AndroidLive.jsx:133:227 |
| T044 | 待审阅 | AndroidLive.jsx | 说明文字 | 观看不会占用 Bot。接管后可点击、拖动和键盘输入；Bot 手机任务会暂停。断线不重放输入，应用登录仍由 owner 完成。 | frontend/src/AndroidLive.jsx:137:5 |

## 手机工作台

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T045 | 待审阅 | AndroidPage.jsx | 空状态 | 加载安卓设备… | frontend/src/AndroidPage.jsx:94:106 |
| T046 | 待审阅 | AndroidPage.jsx | 补充文案候选 | 已有任务正在执行，可先停止或等待完成。 | frontend/src/AndroidPage.jsx:97:35 |
| T047 | 待审阅 | AndroidPage.jsx | 补充文案候选 | 请在任务设置中允许执行安卓任务并保存。 | frontend/src/AndroidPage.jsx:97:77 |
| T048 | 待审阅 | AndroidPage.jsx | 补充文案候选 | 正在 Owner 登录模式，请完成登录后恢复 Bot。 | frontend/src/AndroidPage.jsx:97:123 |
| T049 | 待审阅 | AndroidPage.jsx | 补充文案候选 | 任务设置有未保存的修改，请先保存。 | frontend/src/AndroidPage.jsx:97:165 |
| T050 | 待审阅 | AndroidPage.jsx | 补充文案候选 | 请先启动手机。 | frontend/src/AndroidPage.jsx:97:217 |
| T051 | 待审阅 | AndroidPage.jsx | 辅助文字 | 〔time(task.created)〕 · 〔task.steps.length〕 步 · QQ：〔({ready:'待发送',sending:'发送中',sent:'已确认发送',unknown:'结果未知',skipped:'未发送'})[task.notification] \|\| '未发送'〕 | frontend/src/AndroidPage.jsx:98:233 |
| T052 | 待审阅 | 创建安卓设备 | 副标题 | 〔device.config.width〕 × 〔device.config.height〕 · 当前 Bot 独占 / 每个 Bot 一台独立手机，应用和账号单独保存。 | frontend/src/AndroidPage.jsx:104:56 |
| T053 | 待审阅 | 创建安卓设备 | 操作反馈与确认 | 设备已创建，点击启动开机 | frontend/src/AndroidPage.jsx:105:204 |
| T054 | 待审阅 | 创建安卓设备 | 提示框 | 请先在宿主构建 Google 套件兼容镜像，再创建手机。 | frontend/src/AndroidPage.jsx:105:413 |
| T055 | 待审阅 | 创建安卓设备 | 操作反馈与确认 | 已停止任务，可手动操作设备 | frontend/src/AndroidPage.jsx:106:773 |
| T056 | 待审阅 | 创建安卓设备 | 提示框 | owner 登录模式：Bot 已暂停操作和取图。请自行完成账号登录、验证码，再点击「完成登录」。 / 应用登录必须由 owner 自行完成。登录前请先进入 owner 登录模式。 | frontend/src/AndroidPage.jsx:107:11 |
| T057 | 待审阅 | 创建安卓设备 | 操作反馈与确认 | 已退出登录模式，可重新提交任务 | frontend/src/AndroidPage.jsx:108:310 |
| T058 | 待审阅 | 创建安卓设备 | 操作反馈与确认 | Bot 已暂停，请自行登录应用 | frontend/src/AndroidPage.jsx:108:330 |
| T059 | 待审阅 | 创建安卓设备 | 补充文案候选 | 完成登录，恢复 Bot | frontend/src/AndroidPage.jsx:108:372 |
| T060 | 待审阅 | 创建安卓设备 | 补充文案候选 | owner 登录模式 | frontend/src/AndroidPage.jsx:108:388 |
| T061 | 待审阅 | 创建安卓设备 | 补充文案候选 | 安卓设备当前画面；点击或拖动进行操作 | frontend/src/AndroidPage.jsx:111:96 |
| T062 | 待审阅 | 创建安卓设备 | 空状态 | 点击「获取画面」查看手机 / 启动安卓后查看画面 | frontend/src/AndroidPage.jsx:111:225 |
| T063 | 待审阅 | 创建安卓设备 | 说明文字 | 画面时间：〔time(screen.at)〕。点击屏幕进行轻触，拖动进行滑动。 | frontend/src/AndroidPage.jsx:114:22 |
| T064 | 待审阅 | 创建安卓设备 | 输入框占位 | 先点中输入框，再输入中文或文字 | frontend/src/AndroidPage.jsx:118:209 |
| T065 | 待审阅 | 给手机一个任务 | 操作反馈与确认 | 任务已开始，可在下方查看步骤 | frontend/src/AndroidPage.jsx:124:159 |
| T066 | 待审阅 | 给手机一个任务 | 输入框占位 | 例如：打开设置，查看 Android 版本，然后回到桌面。 | frontend/src/AndroidPage.jsx:124:222 |
| T067 | 待审阅 | 给手机一个任务 | 说明文字 | 任务进行中。手动操作前请点击「人工接管」。 | frontend/src/AndroidPage.jsx:125:24 |
| T068 | 待审阅 | 给手机一个任务 | 说明文字 | 〔taskReason〕 任务设置 → | frontend/src/AndroidPage.jsx:126:24 |
| T069 | 待审阅 | 最近任务 | 空状态 | 还没有任务，提交一个目标开始。 | frontend/src/AndroidPage.jsx:129:186 |
| T070 | 待审阅 | 任务记录 | 副标题 | 执行结果与 QQ 回传分别展示。选择任务查看完整步骤和诊断。 | frontend/src/AndroidPage.jsx:131:131 |
| T071 | 待审阅 | 任务记录 | 输入框占位 | 搜索任务目标或结果… | frontend/src/AndroidPage.jsx:131:241 |
| T072 | 待审阅 | 任务记录 | 辅助文字 | 〔visibleTasks.length〕 条记录 | frontend/src/AndroidPage.jsx:131:611 |
| T073 | 待审阅 | 任务记录 | 空状态 | 没有匹配的任务记录。 / 暂无任务记录。 | frontend/src/AndroidPage.jsx:131:705 |
| T074 | 待审阅 | 公开互动记录 | 副标题 | 记录评论正文、平台、发送核对结果；结果未知时不会自动重发。 | frontend/src/AndroidPage.jsx:132:36 |
| T075 | 待审阅 | 公开互动记录 | 空状态 | 还没有公开互动记录。 | frontend/src/AndroidPage.jsx:132:629 |
| T076 | 待审阅 | 初始化与应用 | 空状态 | 请先在手机与任务中创建设备。 | frontend/src/AndroidPage.jsx:134:203 |
| T077 | 待审阅 | AndroidPage.jsx | 提示框 | 先在部署电脑运行 python3 scripts/android_runtime.py setup，再运行 start。按安装提示把运行时连接配置加入 HayBot，然后重建 app 服务。 | frontend/src/AndroidPage.jsx:136:30 |
| T078 | 待审阅 | 任务权限与模型 | 副标题 | 手机任务单独保存配置，独立选择支持图片的操作模型。 | frontend/src/AndroidPage.jsx:139:72 |
| T079 | 待审阅 | 任务权限与模型 | 说明文字 | 由你在下方提交目标后开始操作。 | frontend/src/AndroidPage.jsx:140:65 |
| T080 | 待审阅 | 任务权限与模型 | 行内说明候选 | 允许 QQ 私聊操作手机 | frontend/src/AndroidPage.jsx:141:44 |
| T081 | 待审阅 | 任务权限与模型 | 说明文字 | 仅下方授权用户可发起任务、查询进度或停止。 | frontend/src/AndroidPage.jsx:141:63 |
| T082 | 待审阅 | 任务权限与模型 | 补充文案候选 | 允许 QQ 私聊操作手机 | frontend/src/AndroidPage.jsx:141:254 |
| T083 | 待审阅 | 任务权限与模型 → QQ 授权用户 ID | 补充文案候选 | QQ 授权用户 ID | frontend/src/AndroidPage.jsx:142:46 |
| T084 | 待审阅 | 任务权限与模型 → QQ 授权用户 ID | 字段说明 | NapCat 填 QQ 号；官方机器人填私聊用户 ID。每个 Bot 单独配置。 | frontend/src/AndroidPage.jsx:142:64 |
| T085 | 待审阅 | 任务权限与模型 → QQ 授权用户 ID | 输入框占位 | 填写允许操作这台手机的用户 | frontend/src/AndroidPage.jsx:142:316 |
| T086 | 待审阅 | 任务权限与模型 | 行内说明候选 | 识别自然语言手机请求 | frontend/src/AndroidPage.jsx:143:44 |
| T087 | 待审阅 | 任务权限与模型 | 说明文字 | 使用当前 Bot 的对话模型识别明确委托；群聊和其他用户不能操作。 | frontend/src/AndroidPage.jsx:143:61 |
| T088 | 待审阅 | 任务权限与模型 | 补充文案候选 | 识别自然语言手机请求 | frontend/src/AndroidPage.jsx:143:276 |
| T089 | 待审阅 | 任务权限与模型 | 说明文字 | QQ 指令：/手机 任务内容 · /手机进度 · /停止手机 · /手机截图。任务完成后回复真实结果，截图指令发送图片。 | frontend/src/AndroidPage.jsx:144:11 |
| T090 | 待审阅 | 任务权限与模型 → 视觉供应商 | 行内说明候选 | 使用当前 Bot 的对话供应商 | frontend/src/AndroidPage.jsx:145:252 |
| T091 | 待审阅 | 任务权限与模型 → 操作模型 | 字段说明 | 填写已开通图片输入的模型名称。 | frontend/src/AndroidPage.jsx:146:55 |
| T092 | 待审阅 | 任务权限与模型 → 操作模型 | 输入框占位 | 填写视觉模型名称 | frontend/src/AndroidPage.jsx:146:264 |
| T093 | 待审阅 | 任务权限与模型 | 行内说明候选 | 按任务复杂程度自动分配预算 | frontend/src/AndroidPage.jsx:147:44 |
| T094 | 待审阅 | 任务权限与模型 | 说明文字 | 先制定计划，分阶段推进；有新进展时自动延长，停滞时保存成果并暂停。 | frontend/src/AndroidPage.jsx:147:64 |
| T095 | 待审阅 | 任务权限与模型 | 说明文字 | 到达阶段边界不会清空成果。继续任务会重新观察当前画面，保留步骤和已收集结果，不重放旧动作。 | frontend/src/AndroidPage.jsx:149:11 |
| T096 | 待审阅 | 浏览兴趣与公开互动 | 副标题 | 兴趣、内容筛选、评论风格及各平台授权集中配置。 | frontend/src/AndroidPage.jsx:150:49 |
| T097 | 待审阅 | AndroidPage.jsx | 行内说明候选 | 手机任务设置有未保存的修改 | frontend/src/AndroidPage.jsx:151:93 |
| T098 | 待审阅 | 设备维护 | 副标题 | 停止手机后可操作。移除容器保留数据，销毁设备会永久删除应用与账号。 | frontend/src/AndroidPage.jsx:153:45 |
| T099 | 待审阅 | AndroidPage.jsx | 弹窗说明 | 当前 Bot 的任务目标、执行结果、回传状态与完整步骤 | frontend/src/AndroidPage.jsx:155:274 |
| T100 | 待审阅 | AndroidPage.jsx | 说明文字 | QQ 结果发送：未发送 | frontend/src/AndroidPage.jsx:155:763 |
| T101 | 待审阅 | AndroidPage.jsx | 说明文字 | 计划：〔(task.progress.plan.milestones \|\| []).join(' → ')〕 | frontend/src/AndroidPage.jsx:155:991 |
| T102 | 待审阅 | AndroidPage.jsx | 说明文字 | 第 〔task.progress.stage.index〕 阶段 · 〔task.progress.stage.used_steps〕 / 〔task.progress.stage.step_limit〕 次决策 · 已用 〔Math.round(task.progress.stage.elapsed_seconds / 60)〕 分钟 | frontend/src/AndroidPage.jsx:155:1181 |
| T103 | 待审阅 | AndroidPage.jsx | 行内说明候选 | 旧任务中提到的候选链接 · 尚需重新核对 | frontend/src/AndroidPage.jsx:155:1642 |
| T104 | 待审阅 | AndroidPage.jsx | 操作反馈与确认 | 从当前状态继续，已有进度保留 | frontend/src/AndroidPage.jsx:155:2139 |
| T105 | 待审阅 | AndroidPage.jsx | 说明文字 | 此任务没有保存模型返回。旧版任务仅保留错误和步骤，原始正文无法还原。 | frontend/src/AndroidPage.jsx:155:2872 |
| T106 | 待审阅 | AndroidPage.jsx | 说明文字 | 模型：〔attempt.metadata.model〕 · 结束原因：未提供 · 正文 〔attempt.metadata.content_chars〕 字符 | frontend/src/AndroidPage.jsx:155:3120 |
| T107 | 待审阅 | 修改手机名称 | 弹窗说明 | 名称用于后台识别这台手机，支持 1–60 个字符，保存后立即生效。 | frontend/src/AndroidPage.jsx:156:239 |
| T108 | 待审阅 | 修改手机名称 | 补充文案候选 | 保存中… | frontend/src/AndroidPage.jsx:156:1043 |
| T109 | 待审阅 | 永久销毁这台手机？ / 移除安卓容器？ | 补充文案候选 | 永久销毁这台手机？ | frontend/src/AndroidPage.jsx:157:246 |
| T110 | 待审阅 | 永久销毁这台手机？ / 移除安卓容器？ | 补充文案候选 | 移除安卓容器？ | frontend/src/AndroidPage.jsx:157:260 |
| T111 | 待审阅 | 永久销毁这台手机？ / 移除安卓容器？ | 弹窗说明 | 应用、登录账号及全部手机数据将永久删除，无法恢复。此操作只影响当前 Bot 的安卓设备。 / 会移除已停止的容器，手机数据保留。再次点击「启动」即可重建并继续使用。 | frontend/src/AndroidPage.jsx:157:285 |
| T112 | 待审阅 | 永久销毁这台手机？ / 移除安卓容器？ | 操作反馈与确认 | 容器已移除，手机数据已保留 | frontend/src/AndroidPage.jsx:157:896 |

## 全局 / 登录 / 工作概览

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T113 | 待审阅 | 工作概览 | 页面副标题 | 查看机器人状态、消息与模型用量。 | frontend/src/App.jsx:29:46 |
| T114 | 待审阅 | 连接与模型 | 页面副标题 | 当前 Bot 的 QQ 接入与模型分配。 | frontend/src/App.jsx:30:41 |
| T115 | 待审阅 | 共享供应商 | 页面副标题 | 选择供应商和模型，管理多个本地或外部连接。 | frontend/src/App.jsx:31:48 |
| T116 | 待审阅 | 角色与群聊 | 页面副标题 | 管理角色身份、Owner 关系和不同场景的表达。 | frontend/src/App.jsx:32:44 |
| T117 | 待审阅 | 角色记忆 | 页面副标题 | 管理每位用户的长期记忆、共同经历和未来约定。 | frontend/src/App.jsx:33:44 |
| T118 | 已删除 2026-10-28 | 私人日记 | 页面副标题 | 翻看她写给自己的日记，设置每天回顾与自主分享。 | frontend/src/App.jsx:34:43 |
| T119 | 待审阅 | 每日日程 | 页面副标题 | 安排角色每天的活动、穿着与生活中的小插曲。 | frontend/src/App.jsx:35:46 |
| T120 | 待审阅 | 表情素材 | 页面副标题 | 管理逐图语义描述，让机器人在合适的时刻发表情。 | frontend/src/App.jsx:36:43 |
| T121 | 待审阅 | QQ 空间 | 页面副标题 | 编辑、定时发布角色动态，管理配图与可见范围。 | frontend/src/App.jsx:37:44 |
| T122 | 待审阅 | 主动互动 | 页面副标题 | 设置定时问候和主动搭话策略。 | frontend/src/App.jsx:38:47 |
| T123 | 待审阅 | 会话记录 | 页面副标题 | 查看当前 Bot 的会话记录，支持列表与气泡视图。 | frontend/src/App.jsx:39:43 |
| T124 | 待审阅 | 手机工作台 | 页面副标题 | 管理独立手机、查看画面并执行安卓操作任务。 | frontend/src/App.jsx:40:46 |
| T125 | 待审阅 | 运行日志 | 页面副标题 | 筛选运行事件，查看模型耗时、异常原因与消息处理链路。 | frontend/src/App.jsx:41:42 |
| T126 | 待审阅 | App.jsx | 补充文案候选 | 输出 Token 上限 | frontend/src/App.jsx:46:28 |
| T127 | 待审阅 | App.jsx | 操作反馈与确认 | 请求失败，请稍后重试 | frontend/src/App.jsx:58:90 |
| T128 | 待审阅 | 机器人状态 | 配置说明 | 外部 NapCat WebSocket / QQ 官方 WebSocket | frontend/src/App.jsx:69:58 |
| T129 | 待审阅 | 已接收消息 | 配置说明 | 累计接收的消息数量 | frontend/src/App.jsx:70:64 |
| T130 | 待审阅 | 已发送回复 | 配置说明 | 累计成功发送的消息数量 | frontend/src/App.jsx:71:60 |
| T131 | 待审阅 | Token 总用量 | 配置说明 | 输入 + 输出 Token | frontend/src/App.jsx:72:72 |
| T132 | 待审阅 | 常用入口 | 副标题 | 查看对话、处理手机任务或翻阅角色生活。 | frontend/src/App.jsx:75:34 |
| T133 | 待审阅 | 常用入口 → 查看会话 | 入口说明 | 最近私聊与群聊 | frontend/src/App.jsx:75:110 |
| T134 | 待审阅 | 常用入口 → 手机工作台 | 入口说明 | 任务、接管与执行结果 | frontend/src/App.jsx:75:140 |
| T135 | 待审阅 | 常用入口 → 翻阅日记 | 入口说明 | 已保存正文与写作习惯 | frontend/src/App.jsx:75:170 |
| T136 | 待审阅 | 常用入口 → 群聊参与 | 入口说明 | 公开人格与各群设置 | frontend/src/App.jsx:75:211 |
| T137 | 待审阅 | 服务连接 | 副标题 | QQ 官方接口与所选模型服务 | frontend/src/App.jsx:76:62 |
| T138 | 待审阅 | 服务连接 | 辅助文字 | QQ · 〔config.napcat.self_id〕 / 尚未配置外部连接 / AppID · 〔config.qq.app_id〕 / 尚未填写机器人凭证 | frontend/src/App.jsx:77:154 |
| T139 | 待审阅 | 服务连接 | 辅助文字 | 尚未选择模型 | frontend/src/App.jsx:78:182 |
| T140 | 待审阅 | Token 用量 | 副标题 | 按模型服务实际返回累计，重启保留 | frontend/src/App.jsx:79:46 |
| T141 | 待审阅 | 最近运行记录 | 副标题 | 查看全部可筛选事件、展开详情与处理链路 | frontend/src/App.jsx:80:36 |
| T142 | 待审阅 | App.jsx | 补充文案候选 | HayBot · QQ AI 机器人配置平台 | frontend/src/App.jsx:132:148 |
| T143 | 待审阅 | App.jsx | 操作反馈与确认 | 〔label〕请填写数字 | frontend/src/App.jsx:140:91 |
| T144 | 待审阅 | App.jsx | 操作反馈与确认 | 当前机器人有未保存的配置。确定离开当前页面吗？ | frontend/src/App.jsx:150:59 |
| T145 | 待审阅 | App.jsx | 操作反馈与确认 | 机器人正在连接 QQ | frontend/src/App.jsx:157:221 |
| T146 | 待审阅 | App.jsx | 补充文案候选 | 正在加载 HayBot | frontend/src/App.jsx:158:103 |
| T147 | 待审阅 | App.jsx | 说明文字 | QQ AI 机器人管理平台 | frontend/src/App.jsx:159:143 |
| T148 | 待审阅 | App.jsx | 说明文字 | 连接 QQ 官方机器人与多个模型供应商。 | frontend/src/App.jsx:159:213 |
| T149 | 待审阅 | App.jsx | 输入框占位 | 输入管理密码 | frontend/src/App.jsx:159:666 |
| T150 | 待审阅 | App.jsx | 辅助文字 | 密码保存在项目 .env 的 ADMIN_PASSWORD 中 | frontend/src/App.jsx:159:881 |
| T151 | 待审阅 | App.jsx | 说明文字 | 本地部署 · 数据自主掌控 | frontend/src/App.jsx:159:934 |
| T152 | 待审阅 | HayBot 导航 | 弹窗说明 | 选择机器人管理页面 | frontend/src/App.jsx:163:371 |
| T153 | 待审阅 | App.jsx | 补充文案候选 | 〔bots.filter(bot => bot.state === 'connected').length〕 在线 | frontend/src/App.jsx:164:355 |
| T154 | 待审阅 | App.jsx | 补充文案候选 | 当前 Bot · 〔currentBot?.name \|\| ''〕 | frontend/src/App.jsx:165:139 |
| T155 | 待审阅 | App.jsx | 补充文案候选 | 工作空间 · 共享资源 | frontend/src/App.jsx:165:178 |
| T156 | 待审阅 | App.jsx | 行内说明候选 | 当前 Bot 有未保存的配置停止机器人后可保存 | frontend/src/App.jsx:166:70 |
| T157 | 待审阅 | App.jsx | 补充文案候选 | 保存中… | frontend/src/App.jsx:166:353 |
| T158 | 待审阅 | App.jsx | 提示框 | 自动启动失败：〔status.start_error〕。已保存的机器人无需重新扫码，可检查配置后点击“启动机器人”重试。 | frontend/src/App.jsx:167:67 |
| T159 | 待审阅 | App.jsx | 提示框 | 后台连接中断，页面显示上次状态，正在重试。 | frontend/src/App.jsx:168:19 |
| T160 | 待审阅 | App.jsx | 提示框 | 有尚未保存的配置，请返回配置页面保存或取消更改。 | frontend/src/App.jsx:169:99 |
| T161 | 待审阅 | App.jsx | 提示框 | 连接、模型与角色策略在运行期间只读。修改这些配置前请先停止机器人。 | frontend/src/App.jsx:170:43 |
| T162 | 待审阅 | App.jsx | 说明文字 | HayBot · 本地机器人管理平台已运行 〔Math.floor(status.uptime / 60)〕 分钟 / 多个机器人独立运行 | frontend/src/App.jsx:185:5 |

## 机器人管理

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T163 | 待审阅 | BotsPage.jsx | 操作反馈与确认 | 机器人正在连接 QQ | frontend/src/BotsPage.jsx:29:129 |
| T164 | 待审阅 | BotsPage.jsx | 操作反馈与确认 | 机器人已恢复，保持停止状态 | frontend/src/BotsPage.jsx:29:170 |
| T165 | 待审阅 | BotsPage.jsx | 操作反馈与确认 | 机器人已创建，请配置 QQ 接入方式 | frontend/src/BotsPage.jsx:36:52 |
| T166 | 待审阅 | BotsPage.jsx | 操作反馈与确认 | 机器人及其当前数据已永久删除 | frontend/src/BotsPage.jsx:40:126 |
| T167 | 待审阅 | BotsPage.jsx | 操作反馈与确认 | 机器人已停止并归档，配置和历史已保留 | frontend/src/BotsPage.jsx:42:122 |
| T168 | 待审阅 | BotsPage.jsx | 辅助文字 | 〔bot.transport==='napcat'?'NapCat · QQ':'AppID'〕 · 〔bot.app_id〕 / 尚未配置 QQ 连接 | frontend/src/BotsPage.jsx:51:145 |
| T169 | 待审阅 | BotsPage.jsx | 补充文案候选 | 管理 〔bot.name〕 | frontend/src/BotsPage.jsx:52:127 |
| T170 | 待审阅 | 查看聊天记录 | 补充文案候选 | 查看 〔bot.name〕 的聊天记录 | frontend/src/BotsPage.jsx:56:581 |
| T171 | 待审阅 | BotsPage.jsx | 补充文案候选 | 正在启动… | frontend/src/BotsPage.jsx:56:982 |
| T172 | 已删除 2026-10-28 | BotsPage.jsx | 副标题 | 多个机器人同时在线，各自独立配置和运行。 | frontend/src/BotsPage.jsx:60:61 |
| T173 | 待审阅 | BotsPage.jsx | 空状态 | 正在加载机器人 | frontend/src/BotsPage.jsx:63:16 |
| T174 | 待审阅 | BotsPage.jsx | 空状态 | 还没有可用的机器人创建一个 Bot，分别设置 QQ 凭证、人格、模型与主动消息。新建机器人 | frontend/src/BotsPage.jsx:63:192 |
| T175 | 待审阅 | BotsPage.jsx | 说明文字 | 各 Bot 的会话、消息统计、接收者和提醒独立保存。模型供应商连接可共享；Ollama 推理排队执行，QQ 连接与消息接收独立运行。 | frontend/src/BotsPage.jsx:64:5 |
| T176 | 待审阅 | BotsPage.jsx | 操作反馈与确认 | QQ 凭证已保存，机器人正在自动连接 QQ | frontend/src/BotsPage.jsx:66:224 |
| T177 | 待审阅 | 新建机器人 / 重命名机器人 / 永久删除机器人 / 归档机器人 | 弹窗说明 | 将永久删除“〔dialog.bot.name〕”的配置、密钥、聊天记录、上下文和统计，无法恢复；其他机器人不受影响。已有平台备份不会自动清理。 / 将停止“〔dialog.bot.name〕”并移出列表。配置、人格、会话与记录保留，之后可以恢复。 / 为机器人设置一个易于识别的名称。每个 Bot 使用独立配置。 | frontend/src/BotsPage.jsx:67:358 |
| T178 | 待审阅 | 新建机器人 / 重命名机器人 / 永久删除机器人 / 归档机器人 | 补充文案候选 | 输入机器人名称确认删除 | frontend/src/BotsPage.jsx:67:755 |
| T179 | 待审阅 | 新建机器人 / 重命名机器人 / 永久删除机器人 / 归档机器人 | 输入框占位 | 〔dialog.bot.name〕 / 例如：生活助手 | frontend/src/BotsPage.jsx:67:916 |

## 会话记录

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T180 | 待审阅 | ChatsPage.jsx | 补充文案候选 | 用户 · 〔message.sender_id.slice(-6)〕 | frontend/src/ChatsPage.jsx:111:123 |
| T181 | 待审阅 | ChatsPage.jsx | 行内说明候选 | 图片 / 表情包 × 〔message.attachment_count〕 · 原图未保存 | frontend/src/ChatsPage.jsx:116:755 |
| T182 | 待审阅 | ChatsPage.jsx | 说明文字 | 仅查看聊天记录 · 每 5 秒自动刷新 | frontend/src/ChatsPage.jsx:118:67 |
| T183 | 待审阅 | ChatsPage.jsx | 提示框 | 会话加载失败：〔listError〕 | frontend/src/ChatsPage.jsx:119:19 |
| T184 | 待审阅 | ChatsPage.jsx | 输入框占位 | 搜索已加载会话 | frontend/src/ChatsPage.jsx:120:345 |
| T185 | 待审阅 | ChatsPage.jsx | 空状态 | 正在加载 | frontend/src/ChatsPage.jsx:121:22 |
| T186 | 待审阅 | ChatsPage.jsx | 补充文案候选 | [图片 / 表情包] | frontend/src/ChatsPage.jsx:121:646 |
| T187 | 待审阅 | ChatsPage.jsx | 辅助文字 | 〔item.message_count〕 条记录 | frontend/src/ChatsPage.jsx:121:676 |
| T188 | 待审阅 | ChatsPage.jsx | 空状态 | 没有匹配的会话 / 还没有聊天记录 | frontend/src/ChatsPage.jsx:121:773 |
| T189 | 待审阅 | ChatsPage.jsx | 补充文案候选 | 正在加载会话… | frontend/src/ChatsPage.jsx:124:120 |
| T190 | 待审阅 | ChatsPage.jsx | 说明文字 | 〔selected.kind === 'group' ? '群聊' : '单聊'〕 · 已保存 〔selected.message_count〕 条记录 / 从会话列表选择用户或群聊 | frontend/src/ChatsPage.jsx:124:147 |
| T191 | 待审阅 | ChatsPage.jsx | 提示框 | 记录加载失败：〔messageError〕 | frontend/src/ChatsPage.jsx:125:24 |
| T192 | 待审阅 | ChatsPage.jsx | 空状态 | 正在加载聊天记录 | frontend/src/ChatsPage.jsx:127:28 |
| T193 | 待审阅 | ChatsPage.jsx | 空状态 | 此会话暂无可显示的记录 / 收到 QQ 消息后，会在这里显示 | frontend/src/ChatsPage.jsx:127:149 |
| T194 | 待审阅 | ChatsPage.jsx | 说明文字 | 已加载 〔visibleMessages.length〕 条用户在左 · 机器人在右 | frontend/src/ChatsPage.jsx:128:13 |
| T195 | 待审阅 | ChatsPage.jsx | 说明文字 | 旧记录仅恢复升级时仍保留的模型上下文及已确认的主动消息，“旧上下文”的发送时间未保存。新记录独立留存，清空模型上下文不会删除聊天记录；收到的图片以占位说明显示，机器人发出的表情包可预览。 | frontend/src/ChatsPage.jsx:129:18 |

## 共享组件

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T196 | 待审阅 | console.jsx | 空状态 | 暂无运行日志 | frontend/src/components/console.jsx:23:28 |
| T329 | 待审阅 | android.js | 操作反馈与确认 | 〔label〕请填写1–〔max〕的整数 | frontend/src/lib/android.js:10:158 |
| T330 | 待审阅 | android.js | 操作反馈与确认 | 〔label〕请填写〔min〕–〔max〕的整数 | frontend/src/lib/android.js:16:138 |
| T331 | 待审阅 | android.js | 操作反馈与确认 | 开启 @ 前请允许评论并填写 owner 账号 ID 和昵称 | frontend/src/lib/android.js:25:102 |
| T332 | 待审阅 | memory-config.js | 操作反馈与确认 | 向量维度必须为 1–65536 的整数，或留空使用模型默认值 | frontend/src/lib/memory-config.js:12:119 |

## 全局 / 功能查找

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T197 | 待审阅 | 功能查找 → 工作概览 | 入口说明 | 状态 用量 | frontend/src/components/FeatureSearch.jsx:8:20 |
| T198 | 待审阅 | 功能查找 → 会话记录 | 入口说明 | 聊天 私聊 群聊 引用 | frontend/src/components/FeatureSearch.jsx:8:45 |
| T199 | 待审阅 | 功能查找 → 手机工作台 | 入口说明 | 安卓 实时画面 接管 任务 | frontend/src/components/FeatureSearch.jsx:9:20 |
| T200 | 待审阅 | 功能查找 → 任务记录 | 入口说明 | 手机 步骤 结果 送达 诊断 | frontend/src/components/FeatureSearch.jsx:9:66 |
| T201 | 待审阅 | 功能查找 → 初始化与应用 | 入口说明 | 安装 手机初始化记录 Google Play | frontend/src/components/FeatureSearch.jsx:10:31 |
| T202 | 待审阅 | 功能查找 → 手机任务设置 | 入口说明 | 角色兴趣 主人偏好 筛选 权限 视觉模型 | frontend/src/components/FeatureSearch.jsx:10:91 |
| T203 | 待审阅 | 功能查找 → 身份与私聊 | 入口说明 | 回复策略 系统提示词 | frontend/src/components/FeatureSearch.jsx:11:18 |
| T204 | 待审阅 | 功能查找 → Owner 关系 | 入口说明 | 主人 群成员身份 公开关系 | frontend/src/components/FeatureSearch.jsx:11:63 |
| T205 | 待审阅 | 功能查找 → 群聊参与 | 入口说明 | 群聊人格 自主回复 各群设置 判断记录 | frontend/src/components/FeatureSearch.jsx:12:28 |
| T206 | 待审阅 | 功能查找 → 公开评论风格 | 入口说明 | 公开评论人格 | frontend/src/components/FeatureSearch.jsx:12:81 |
| T207 | 待审阅 | 功能查找 → 回复设置 | 入口说明 | 防抖 分段 冷却 上下文 | frontend/src/components/FeatureSearch.jsx:13:31 |
| T208 | 待审阅 | 功能查找 → 角色记忆 | 入口说明 | 长期记忆 来源 约定 | frontend/src/components/FeatureSearch.jsx:13:64 |
| T209 | 待审阅 | 功能查找 → 记忆设置 | 入口说明 | 整理 检索 索引 | frontend/src/components/FeatureSearch.jsx:14:32 |
| T210 | 待审阅 | 功能查找 → 每日日程 | 入口说明 | 时间线 穿着 生活 | frontend/src/components/FeatureSearch.jsx:14:63 |
| T211 | 待审阅 | 功能查找 → 私人日记 | 入口说明 | 日记本 正文 版本 | frontend/src/components/FeatureSearch.jsx:15:17 |
| T212 | 待审阅 | 功能查找 → 写作习惯 | 入口说明 | 自动写作 自主分享 | frontend/src/components/FeatureSearch.jsx:15:60 |
| T213 | 待审阅 | 功能查找 → 主动互动 | 入口说明 | 搭话 问候 | frontend/src/components/FeatureSearch.jsx:16:21 |
| T214 | 待审阅 | 功能查找 → 一次性提醒 | 入口说明 | 定时消息 | frontend/src/components/FeatureSearch.jsx:16:66 |
| T215 | 待审阅 | 功能查找 → QQ 空间 | 入口说明 | 动态 草稿 定时发布 | frontend/src/components/FeatureSearch.jsx:17:33 |
| T216 | 待审阅 | 功能查找 → 发送记录 | 入口说明 | 主动消息 推送状态 | frontend/src/components/FeatureSearch.jsx:17:80 |
| T217 | 待审阅 | 功能查找 → 表情素材 | 入口说明 | 表情包 共享图库 | frontend/src/components/FeatureSearch.jsx:18:17 |
| T218 | 待审阅 | 功能查找 → 表情策略 | 入口说明 | 概率 冷却 语义索引 | frontend/src/components/FeatureSearch.jsx:18:59 |
| T219 | 待审阅 | 功能查找 → QQ 连接 | 入口说明 | NapCat WebSocket 官方 AppID | frontend/src/components/FeatureSearch.jsx:19:15 |
| T220 | 待审阅 | 功能查找 → 模型分配 | 入口说明 | Ollama 对话 记忆 模型供应商 | frontend/src/components/FeatureSearch.jsx:19:69 |
| T221 | 待审阅 | 功能查找 → 运行日志 | 入口说明 | 错误 事件 链路 诊断 | frontend/src/components/FeatureSearch.jsx:20:16 |
| T222 | 待审阅 | FeatureSearch.jsx | 补充文案候选 | 创建 归档 切换 Bot | frontend/src/components/FeatureSearch.jsx:24:95 |
| T223 | 待审阅 | FeatureSearch.jsx | 补充文案候选 | 连接目录 API Key 模型服务 | frontend/src/components/FeatureSearch.jsx:24:133 |
| T224 | 待审阅 | 查找功能 | 弹窗说明 | 按页面名称或原有功能名称查找入口 | frontend/src/components/FeatureSearch.jsx:27:388 |
| T225 | 待审阅 | 查找功能 | 输入框占位 | 查找功能，例如初始化、群聊人格… | frontend/src/components/FeatureSearch.jsx:27:622 |
| T226 | 待审阅 | 查找功能 | 空状态 | 没有找到匹配功能，试试更短的关键词。 | frontend/src/components/FeatureSearch.jsx:27:960 |

## 角色与群聊

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T227 | 待审阅 | 定义机器人的人设 | 副标题 | 作为系统提示词，随每次请求发送给模型 | frontend/src/ConfigurationPages.jsx:17:140 |
| T228 | 待审阅 | 定义机器人的人设 → 系统提示词 | 字段说明 | 描述角色、语气、回答语言与需要遵循的规则。 | frontend/src/ConfigurationPages.jsx:17:281 |
| T229 | 待审阅 | 定义机器人的人设 → 保留上下文（轮） | 字段说明 | 0–30；0 为关闭。单聊和群成员分别保存。 | frontend/src/ConfigurationPages.jsx:17:473 |
| T230 | 待审阅 | 定义机器人的人设 → 最大回复长度（字） | 字段说明 | 10–2000；超过长度时截断回复正文。 | frontend/src/ConfigurationPages.jsx:17:690 |
| T231 | 待审阅 | 定义机器人的人设 → 回复冷却（秒） | 字段说明 | 同一会话两轮回复的最小间隔，0–300 秒；新消息会排队等待，不再丢弃。 | frontend/src/ConfigurationPages.jsx:17:916 |
| T232 | 待审阅 | 消息防抖 | 副标题 | 用户连续发送的几条消息先合并，再调用一次模型；生成期间的新消息排队保留。 | frontend/src/ConfigurationPages.jsx:17:1208 |
| T233 | 待审阅 | 消息防抖 | 说明文字 | 每位用户单独等待，群聊按群成员隔离。关闭后每条消息依次处理，忙碌或冷却时也不会直接丢弃。 | frontend/src/ConfigurationPages.jsx:17:1299 |
| T234 | 待审阅 | 消息防抖 → 静默等待（秒） | 字段说明 | 0.2–10 秒，默认 3 秒。每收到一条新消息重新计时。 | frontend/src/ConfigurationPages.jsx:17:1696 |
| T235 | 待审阅 | 消息防抖 → 最长收集时间（秒） | 字段说明 | 1–60 秒，默认 10 秒，不能短于静默等待。不包含上一轮生成、冷却或排队等待。 | frontend/src/ConfigurationPages.jsx:17:1970 |
| T236 | 待审阅 | 消息防抖 → 每批最多消息数 | 字段说明 | 1–10 条，默认 10 条。达到上限即可处理，剩余消息进入下一批。 | frontend/src/ConfigurationPages.jsx:17:2259 |
| T237 | 待审阅 | 消息防抖 | 提示框 | 原始消息逐条保留。正在生成时不反复取消重算；指令不参与合并，确认 /reset 会清空该用户缓冲。仅调整防抖设置保留上下文，QQ 回复有效期仍然适用。 | frontend/src/ConfigurationPages.jsx:17:2498 |
| T238 | 待审阅 | 消息分段 | 副标题 | 把普通聊天长回复分成连续的独立气泡。短回复保持一条；指令、日程显示和主动消息不变。 | frontend/src/ConfigurationPages.jsx:17:2682 |
| T239 | 待审阅 | 消息分段 | 说明文字 | 优先按段落和句末拆分，保护链接与代码。达到气泡上限时合并剩余内容，不丢弃尾部。 | frontend/src/ConfigurationPages.jsx:17:2778 |
| T240 | 待审阅 | 消息分段 → 目标段长（字） | 字段说明 | 20–500，默认 100。实际会在自然语义处断开，完整长句或代码块可能超过此长度。 | frontend/src/ConfigurationPages.jsx:17:3157 |
| T241 | 待审阅 | 消息分段 → 每次最多气泡数 | 字段说明 | 1–4，默认 4。限制单次回复的消息数量。 | frontend/src/ConfigurationPages.jsx:17:3417 |
| T242 | 待审阅 | 消息分段 → 段间隔（秒） | 字段说明 | 0–5 秒，默认 0.8 秒。第一段立即发送，后续按顺序发送。 | frontend/src/ConfigurationPages.jsx:17:3657 |
| T243 | 待审阅 | 消息分段 | 提示框 | 仅调整分段设置会保留上下文。后台聊天记录按实际送达的气泡保存；中途失败或重置时停止后续发送。 | frontend/src/ConfigurationPages.jsx:17:3873 |
| T244 | 待审阅 | 上下文管理 | 副标题 | 模型上下文保存在 SQLite，修改模型或人格等内容后会清空；仅调整分段保留上下文，聊天记录独立保留 | frontend/src/ConfigurationPages.jsx:17:4029 |
| T245 | 待审阅 | 上下文管理 | 操作反馈与确认 | 确定清空所有对话上下文吗？此操作无法撤销。 | frontend/src/ConfigurationPages.jsx:17:4184 |
| T246 | 待审阅 | 公开评论风格 | 副标题 | 仅用于手机平台公开互动，独立于私聊和群聊人格。 | frontend/src/ConfigurationPages.jsx:17:4558 |
| T247 | 待审阅 | 公开评论风格 | 说明文字 | 公开评论风格与平台授权保存在手机任务配置中，可在机器人运行时独立管理。 | frontend/src/ConfigurationPages.jsx:17:4584 |
| T248 | 待审阅 | 公开评论风格 | 行内说明候选 | 编辑公开评论风格与平台权限 → | frontend/src/ConfigurationPages.jsx:17:4798 |

## 连接与模型 / QQ 连接

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T249 | 已删除 2026-10-28 | QQ 接入方式 | 副标题 | 每个机器人选择一种接入方式，官方机器人和外部 NapCat 可以同时运行。 | frontend/src/ConnectionPage.jsx:11:37 |
| T250 | 待审阅 | QQ 接入方式 | 说明文字 | 切换接入方式或账号会清空近期对话上下文，需要重新选择主动消息接收者；已有聊天档案、长期记忆和日程保留，并按账号分别隔离。 | frontend/src/ConnectionPage.jsx:13:7 |
| T251 | 待审阅 | 外部 NapCat 连接 | 补充文案候选 | 外部 NapCat 连接 | frontend/src/ConnectionPage.jsx:15:26 |
| T252 | 待审阅 | 外部 NapCat 连接 | 副标题 | 连接你已经运行并登录 QQ 的 NapCat，HayBot 不托管扫码登录。 | frontend/src/ConnectionPage.jsx:15:50 |
| T253 | 待审阅 | 外部 NapCat 连接 → 登录 QQ 号 | 字段说明 | 必须与 NapCat 当前登录账号一致，连接时会自动核对。 | frontend/src/ConnectionPage.jsx:17:57 |
| T254 | 待审阅 | 外部 NapCat 连接 → 登录 QQ 号 | 输入框占位 | 例如：123456789 | frontend/src/ConnectionPage.jsx:17:249 |
| T255 | 待审阅 | 外部 NapCat 连接 → WebSocket 服务地址 | 补充文案候选 | WebSocket 服务地址 | frontend/src/ConnectionPage.jsx:18:22 |
| T256 | 待审阅 | 外部 NapCat 连接 → WebSocket 服务地址 | 字段说明 | 填写 NapCat 的 WebSocket 服务端地址，不是 6099 WebUI 管理地址。 | frontend/src/ConnectionPage.jsx:18:63 |
| T257 | 待审阅 | 外部 NapCat 连接 → WebSocket 服务地址 | 输入框占位 | ws://192.168.31.100:3001 | frontend/src/ConnectionPage.jsx:18:252 |
| T258 | 待审阅 | 外部 NapCat 连接 → 连接 Token | 字段说明 | 已加密保存，留空保持；更换连接地址或 QQ 号后需重新填写。 / 与 NapCat WebSocket 服务端配置的 Token 一致；不要填写 WebUI 的登录 Token。 | frontend/src/ConnectionPage.jsx:19:61 |
| T259 | 待审阅 | 外部 NapCat 连接 → 连接 Token | 输入框占位 | •••••••• 已安全保存 / 填写 WebSocket 连接 Token | frontend/src/ConnectionPage.jsx:19:400 |
| T260 | 待审阅 | 外部 NapCat 连接 | 行内说明候选 | 清除已保存的 Token（仅限外部服务未启用鉴权时） | frontend/src/ConnectionPage.jsx:20:228 |
| T261 | 待审阅 | 外部 NapCat 连接 | 行内说明候选 | 测试 NapCat 连接 | frontend/src/ConnectionPage.jsx:22:271 |
| T262 | 待审阅 | 外部 NapCat 连接 | 行内说明候选 | NapCat 配置说明 | frontend/src/ConnectionPage.jsx:22:396 |
| T263 | 待审阅 | 官方机器人凭证 | 副标题 | 来自 QQ 开放平台，凭证加密保存在 SQLite 中。 | frontend/src/ConnectionPage.jsx:23:46 |
| T264 | 待审阅 | 官方机器人凭证 → AppID | 字段说明 | 在 QQ 开放平台机器人开发设置中获取。 | frontend/src/ConnectionPage.jsx:23:190 |
| T265 | 待审阅 | 官方机器人凭证 → AppSecret | 字段说明 | 留空保持已保存密钥，填写新值可替换。 / 保存后不会返回浏览器。 | frontend/src/ConnectionPage.jsx:23:380 |
| T266 | 待审阅 | 官方机器人凭证 → AppSecret | 输入框占位 | •••••••• 已安全保存 / 填写 AppSecret | frontend/src/ConnectionPage.jsx:23:589 |
| T267 | 待审阅 | 接收与回复场景 | 副标题 | 个人记忆及日程按群成员隔离；回复时会参考本群近期收到的公开发言，并区分发送者。 | frontend/src/ConnectionPage.jsx:24:37 |
| T268 | 待审阅 | 接收与回复场景 | 说明文字 | 收到用户单聊后，调用模型生成回答。 | frontend/src/ConnectionPage.jsx:25:59 |
| T269 | 待审阅 | 接收与回复场景 | 说明文字 | 总开关；具体参与方式在「角色与群聊」中配置。 | frontend/src/ConnectionPage.jsx:26:53 |
| T270 | 待审阅 | ConnectionPage.jsx | 行内说明候选 | 管理群聊参与、公开人格与 Owner 关系 → | frontend/src/ConnectionPage.jsx:28:127 |
| T271 | 待审阅 | ConnectionPage.jsx | 行内说明候选 | NapCat 连接帮助 | frontend/src/ConnectionPage.jsx:29:57 |
| T272 | 已删除 2026-10-28 | 连接步骤 | 副标题 | 先运行外部服务，再在 HayBot 中保存并测试连接。 | frontend/src/ConnectionPage.jsx:29:107 |
| T273 | 待审阅 | 连接步骤 | 行内说明候选 | 在 NapCat 中登录目标 QQ，添加并启用「WebSocket 服务端」。 | frontend/src/ConnectionPage.jsx:29:165 |
| T274 | 待审阅 | 连接步骤 | 行内说明候选 | 选择可访问的监听地址及端口，配置 Token，消息格式选择数组。 | frontend/src/ConnectionPage.jsx:29:213 |
| T275 | 待审阅 | 连接步骤 | 行内说明候选 | 把服务地址、相同 Token 和登录 QQ 号填到本页，保存后点击测试连接。 | frontend/src/ConnectionPage.jsx:29:254 |
| T276 | 待审阅 | 连接步骤 | 行内说明候选 | 配置模型并启动机器人。断线会自动重连，未确认的发送不会自动重发。 | frontend/src/ConnectionPage.jsx:29:301 |
| T277 | 待审阅 | 连接步骤 | 说明文字 | HayBot 在 Docker 中运行时，127.0.0.1 指向容器自身。NapCat 在这台电脑上时，可使用 ws://host.docker.internal:端口；在其他设备上时，使用那台设备的局域网地址。原生表情及 GIF 通过 NapCat 发送，实际显示以 QQ 客户端为准。 | frontend/src/ConnectionPage.jsx:29:347 |

## 私人日记

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T278 | 待审阅 | DiaryPage.jsx | 说明文字 | 写给自己，Owner 可翻看 · 写完安静保存 · 日记感受不会自动写入长期记忆 | frontend/src/DiaryPage.jsx:47:5 |
| T279 | 已删除 2026-10-28 | 写日记的习惯 | 副标题 | 沿用原角色人格。事情有依据，感受可以细腻，安静的一天也不必硬凑内容。 | frontend/src/DiaryPage.jsx:49:78 |
| T280 | 待审阅 | 写日记的习惯 | 说明文字 | 正在加载… | frontend/src/DiaryPage.jsx:50:18 |
| T281 | 待审阅 | 写日记的习惯 → 写作时间 | 字段说明 | 错过时可在下次运行补齐最近一天；不批量补造旧日记。 | frontend/src/DiaryPage.jsx:53:52 |
| T282 | 待审阅 | 写日记的习惯 → Owner 私聊账号 | 补充文案候选 | Owner 私聊账号 | frontend/src/DiaryPage.jsx:55:24 |
| T283 | 待审阅 | 写日记的习惯 → Owner 私聊账号 | 字段说明 | QQ 官方填写私聊用户 OpenID，NapCat 填 QQ 号。只选定这个人的私聊；群聊成员 OpenID 不能代替私聊 OpenID。留空时不读取任何人的私聊，也不向聊天提供日记。 | frontend/src/DiaryPage.jsx:55:59 |
| T284 | 待审阅 | 写日记的习惯 → 群聊素材 | 行内说明候选 | 参考当天已收到的群聊 | frontend/src/DiaryPage.jsx:56:226 |
| T285 | 待审阅 | 写日记的习惯 → 自主分享 | 字段说明 | 只在与绑定 Owner 的私聊中参考，不向群友提供日记。关闭后仅在后台查看。 | frontend/src/DiaryPage.jsx:57:55 |
| T286 | 待审阅 | 写日记的习惯 → 自主分享 | 行内说明候选 | 允许自行选择分享片段 | frontend/src/DiaryPage.jsx:57:272 |
| T287 | 待审阅 | 写日记的习惯 → 写作偏好（可选） | 字段说明 | 例如多留意让自己有感触的小事。不要填写每日必须发生的剧情。 | frontend/src/DiaryPage.jsx:58:68 |
| T288 | 待审阅 | 写日记的习惯 | 行内说明候选 | 日记设置有未保存的修改 | frontend/src/DiaryPage.jsx:60:85 |
| T289 | 待审阅 | 日记本 | 副标题 | 〔entries.total〕 篇 · 按日期保存，同一天补写会保留旧版本。 | frontend/src/DiaryPage.jsx:64:35 |
| T290 | 待审阅 | 日记本 | 补充文案候选 | 正在写… | frontend/src/DiaryPage.jsx:65:490 |
| T291 | 待审阅 | 日记本 | 说明文字 | 先保存日记设置，再开始写作。 | frontend/src/DiaryPage.jsx:66:19 |
| T292 | 待审阅 | 日记本 | 说明文字 | 正在回顾当天的素材并写作，保存后会出现在日记本里。 | frontend/src/DiaryPage.jsx:67:21 |
| T293 | 待审阅 | 日记本 | 说明文字 | 还没有保存正文 | frontend/src/DiaryPage.jsx:68:365 |
| T294 | 待审阅 | 日记本 | 辅助文字 | 第 〔item.revision〕 版 | frontend/src/DiaryPage.jsx:68:413 |
| T295 | 待审阅 | 日记本 | 说明文字 | 还没有日记。可以先写今天，或等她在设定时间自己写。 | frontend/src/DiaryPage.jsx:69:35 |
| T296 | 待审阅 | 翻开一页 | 副标题 | 〔entry.timezone〕 · 第 〔entry.revision〕 版 / 选择左侧日期，阅读她留下的文字。 | frontend/src/DiaryPage.jsx:72:52 |
| T297 | 待审阅 | 翻开一页 | 说明文字 | 正在读取… / 日记只在当前 Bot 的日记本里保存。 | frontend/src/DiaryPage.jsx:73:19 |
| T298 | 待审阅 | 翻开一页 | 提示框 | 〔entry.error〕；上一次保存的正文仍在。 | frontend/src/DiaryPage.jsx:74:27 |
| T299 | 待审阅 | 翻开一页 | 补充文案候选 | 这一篇尚未完成，可以重新写作。 | frontend/src/DiaryPage.jsx:75:62 |
| T300 | 待审阅 | 翻开一页 | 说明文字 | 素材：0 条聊天 · 0 项已完成手机任务。日程如有引用，仅作计划参考。 | frontend/src/DiaryPage.jsx:76:11 |
| T301 | 待审阅 | 翻开一页 | 说明文字 | 删除这篇日记及所有旧版本？删除后不会自动重新生成。 | frontend/src/DiaryPage.jsx:78:51 |

## 角色与群聊 / Owner 与群聊参与

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T302 | 待审阅 | GroupChatSettings.jsx | 说明文字 | 群聊自动回复总开关：已开启 / 已关闭 · 前往 QQ 连接修改 | frontend/src/GroupChatSettings.jsx:34:26 |
| T303 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 | 悬浮提示 | 身份与 Owner 关系 / 群聊参与方式 | frontend/src/GroupChatSettings.jsx:35:18 |
| T304 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 | 副标题 | 明确角色身份与可公开的关系事实，群聊人格不会覆盖 Owner 的私聊风格。 / 先理解本群对话，再决定是否接话。不需要回复时保持沉默。 | frontend/src/GroupChatSettings.jsx:35:74 |
| T305 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 → 默认模式 | 字段说明 | 适用于未单独配置的群；群聊自动回复总开关仍然有效。 | frontend/src/GroupChatSettings.jsx:37:102 |
| T306 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 → 参与积极程度 | 字段说明 | 影响开口意愿，不要求凑回复次数。 | frontend/src/GroupChatSettings.jsx:38:56 |
| T307 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 → 角色名字 | 字段说明 | 固定的角色身份，Owner 和普通群友都使用。公开人格不会覆盖此名字；留空时使用平台账号昵称。 | frontend/src/GroupChatSettings.jsx:39:66 |
| T308 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 → 群聊 Owner QQ 号 / 群聊 Owner 成员 OpenID | 补充文案候选 | 群聊 Owner QQ 号 | frontend/src/GroupChatSettings.jsx:40:55 |
| T309 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 → 群聊 Owner QQ 号 / 群聊 Owner 成员 OpenID | 补充文案候选 | 群聊 Owner 成员 OpenID | frontend/src/GroupChatSettings.jsx:40:73 |
| T310 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 → 群聊 Owner QQ 号 / 群聊 Owner 成员 OpenID | 字段说明 | 仅与当前账号下平台提供的真实发送者 ID 精确匹配。Owner 使用回复策略中的原角色人格；这项设置不会授予手机权限。官方渠道须填写群事件中的成员 OpenID，不猜测与 QQ 号或私聊 OpenID 的对应关系。 | frontend/src/GroupChatSettings.jsx:40:117 |
| T311 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 → 与 Owner 的公开关系 | 补充文案候选 | 与 Owner 的公开关系 | frontend/src/GroupChatSettings.jsx:41:22 |
| T312 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 → 与 Owner 的公开关系 | 字段说明 | 填写允许向群友说明的关系事实，例如「Owner 是我的男朋友，我是他的女朋友」。被问起时如实回答；公开人格不能否认这段关系，也不会把群友当成 Owner。留空时不猜测关系细节。 | frontend/src/GroupChatSettings.jsx:41:78 |
| T313 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 → 群聊公开人格 | 字段说明 | 仅对普通群友生效，Owner 继续使用回复策略中的原角色人格。这里填写公开交流风格；所有群聊回应都不读取私聊记录，保持角色名字及已填写的 Owner 关系一致。 | frontend/src/GroupChatSettings.jsx:42:112 |
| T314 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 → 角色公开兴趣 | 字段说明 | 由你填写，例如插画、游戏音乐、生活摄影。留空时不从人格自动推导兴趣；出现关键词也不会强制回复。 | frontend/src/GroupChatSettings.jsx:43:62 |
| T315 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 → 主动接话最短间隔（秒） | 补充文案候选 | 主动接话最短间隔（秒） | frontend/src/GroupChatSettings.jsx:44:22 |
| T316 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 → 主动接话最短间隔（秒） | 字段说明 | 按整个群计算；被直接 @ 的消息沿用普通回复冷却。 | frontend/src/GroupChatSettings.jsx:44:61 |
| T317 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 → 每群每小时主动回复上限 | 补充文案候选 | 每群每小时主动回复上限 | frontend/src/GroupChatSettings.jsx:45:22 |
| T318 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 → 每群每小时主动回复上限 | 字段说明 | 1–300；防止刷屏，不作为参与目标。直接 @ 的消息不受此上限限制。 | frontend/src/GroupChatSettings.jsx:45:59 |
| T319 | 待审阅 | 身份与 Owner 关系 / 群聊参与方式 | 说明文字 | 自然参与会接收并保存普通群消息，按整个群合并连续发言。群聊无法触发手机操作；设备权限仍仅限授权 Owner 私聊。QQ 官方 Bot 还需要在开放平台开启「接收所有消息」。仅收到 @ 事件时，仍可回复 @，无法旁听未推送的消息。 | frontend/src/GroupChatSettings.jsx:47:7 |
| T320 | 待审阅 | 各群参与设置 | 副标题 | 仅展示当前接入账号已收到消息的群。修改后使用页面底部的保存按钮。 | frontend/src/GroupChatSettings.jsx:49:59 |
| T321 | 待审阅 | 各群参与设置 | 补充文案候选 | 〔group.title〕参与方式 | frontend/src/GroupChatSettings.jsx:54:59 |
| T322 | 待审阅 | 各群参与设置 | 补充文案候选 | 〔group.title〕积极程度 | frontend/src/GroupChatSettings.jsx:55:68 |
| T323 | 待审阅 | 各群参与设置 | 说明文字 | 尚未收到群聊消息；收到后可按群设置。 | frontend/src/GroupChatSettings.jsx:58:63 |
| T324 | 待审阅 | 最近参与判断 | 副标题 | 记录开口、沉默和取消发送的原因，每 5 秒刷新。 | frontend/src/GroupChatSettings.jsx:60:36 |
| T325 | 待审阅 | 最近参与判断 | 说明文字 | 暂无参与判断。启用自然参与或安静旁听后开始记录。 | frontend/src/GroupChatSettings.jsx:62:36 |
| T326 | 待审阅 | 手机授权与私聊绑定 | 副标题 | 官方私聊 OpenID、群成员 OpenID 和手机权限按用途分别设置，不自动匹配。 | frontend/src/GroupChatSettings.jsx:64:60 |
| T327 | 待审阅 | 手机授权与私聊绑定 | 行内说明候选 | 编辑手机授权账号 → | frontend/src/GroupChatSettings.jsx:64:282 |
| T328 | 待审阅 | 手机授权与私聊绑定 | 行内说明候选 | 日记 Owner 绑定 → | frontend/src/GroupChatSettings.jsx:64:424 |

## 运行日志

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T333 | 待审阅 | LogsPage.jsx | 操作反馈与确认 | 已导出当前加载的 〔items.length〕 条日志 | frontend/src/LogsPage.jsx:86:12 |
| T334 | 待审阅 | 运行事件 | 副标题 | 查看事件详情，沿处理链路定位问题。新事件每 5 秒同步，保留最近 10,000 条。 | frontend/src/LogsPage.jsx:91:34 |
| T335 | 待审阅 | 运行事件 | 输入框占位 | 搜索事件、用户、模型、错误或链路编号 | frontend/src/LogsPage.jsx:92:141 |
| T336 | 待审阅 | 运行事件 | 行内说明候选 | 匹配 0 条，已加载 〔items.length〕 条 | frontend/src/LogsPage.jsx:93:224 |
| T337 | 待审阅 | 运行事件 | 提示框 | 〔error〕。已加载的日志会保留，可点击刷新重试。 | frontend/src/LogsPage.jsx:94:17 |
| T338 | 待审阅 | 运行事件 | 空状态 | 正在读取日志… | frontend/src/LogsPage.jsx:95:18 |
| T339 | 待审阅 | 运行事件 | 空状态 | 没有匹配的运行事件可以清除筛选，或等待机器人处理新消息。 | frontend/src/LogsPage.jsx:95:128 |
| T340 | 待审阅 | 运行事件 | 补充文案候选 | 查看日志 〔event.id〕：〔event.message〕 | frontend/src/LogsPage.jsx:95:431 |
| T341 | 待审阅 | 运行事件 | 说明文字 | 自动刷新中 / 已暂停自动刷新 · 已加载 〔items.length〕 条凭证自动隐藏；旧版事件可能没有模型与耗时详情。 | frontend/src/LogsPage.jsx:97:7 |
| T342 | 待审阅 | LogsPage.jsx | 操作反馈与确认 | 复制失败，请使用导出功能保存日志 | frontend/src/LogsPage.jsx:114:20 |
| T343 | 待审阅 | 事件详情 | 弹窗说明 | 查看处理信息、异常原因和关联聊天，凭证已隐藏。 | frontend/src/LogsPage.jsx:116:240 |
| T344 | 待审阅 | 事件详情 | 提示框 | 这是旧版记录，只保存了时间、级别与事件摘要。升级后的新事件会包含详细信息。 | frontend/src/LogsPage.jsx:119:44 |

## 全局 / 404 页面

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T345 | 待审阅 | main.jsx | 副标题 | 请检查地址或返回机器人管理。 | frontend/src/main.jsx:8:83 |

## 表情素材

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T346 | 待审阅 | MemesPage.jsx | 补充文案候选 | DeepSeek 同人表情包 | frontend/src/MemesPage.jsx:13:60 |
| T347 | 待审阅 | MemesPage.jsx | 操作反馈与确认 | 描述已保存，请重建语义索引 | frontend/src/MemesPage.jsx:57:7 |
| T348 | 待审阅 | MemesPage.jsx | 操作反馈与确认 | 图片必须小于 10 MB | frontend/src/MemesPage.jsx:61:39 |
| T349 | 待审阅 | 〔label〕 供应商 | 补充文案候选 | 〔label〕 供应商 | frontend/src/MemesPage.jsx:70:53 |
| T350 | 待审阅 | 〔label〕 供应商 | 补充文案候选 | 请选择 Embedding | frontend/src/MemesPage.jsx:70:374 |
| T351 | 待审阅 | 〔label〕 模型 | 补充文案候选 | 〔label〕 模型 | frontend/src/MemesPage.jsx:70:497 |
| T352 | 待审阅 | MemesPage.jsx | 提示框 | 正在读取表情包配置… | frontend/src/MemesPage.jsx:73:21 |
| T353 | 待审阅 | 表情包策略 | 副标题 | 仅作用于当前机器人。模型会结合上下文选择合适的表情，最多发送一张。 | frontend/src/MemesPage.jsx:76:77 |
| T354 | 待审阅 | 表情包策略 | 说明文字 | 适合时才发送，文字和图片合计最多 4 个气泡；指令和主动消息不受影响。 | frontend/src/MemesPage.jsx:78:64 |
| T355 | 待审阅 | 表情包策略 | 补充文案候选 | Rerank（可选） | frontend/src/MemesPage.jsx:80:69 |
| T356 | 待审阅 | 表情包策略 | 行内说明候选 | 沿用当前记忆模型配置 | frontend/src/MemesPage.jsx:81:213 |
| T357 | 待审阅 | 表情包策略 → 候选触发概率 | 字段说明 | 0–1，0.35 表示约 35% 的对话会尝试选图，并非一定发送。 | frontend/src/MemesPage.jsx:82:72 |
| T358 | 待审阅 | 表情包策略 → 发送冷却（秒） | 字段说明 | 同一用户两次表情包的最短间隔，0–86400 秒。 | frontend/src/MemesPage.jsx:82:149 |
| T359 | 待审阅 | 表情包策略 → 避开最近几张 | 字段说明 | 每个用户分别记录，0 表示允许连续重复。 | frontend/src/MemesPage.jsx:82:212 |
| T360 | 待审阅 | 表情包策略 → 提供给模型的候选数 | 字段说明 | 向量召回后供主对话模型挑选，1–10 张。 | frontend/src/MemesPage.jsx:82:264 |
| T361 | 待审阅 | 表情包策略 → 最低相似度 | 字段说明 | 低于此值不进入候选，默认 0.2。 | frontend/src/MemesPage.jsx:82:324 |
| T362 | 待审阅 | 表情包策略 → 检索超时（秒） | 字段说明 | 超时后本轮正常发送文字。 | frontend/src/MemesPage.jsx:82:374 |
| T363 | 待审阅 | 表情包策略 | 行内说明候选 | 策略可在机器人运行时保存，不清空聊天或记忆。 | frontend/src/MemesPage.jsx:85:80 |
| T364 | 待审阅 | 语义索引 | 副标题 | 表情包使用独立索引，支持单独选择 Embedding 与 Rerank。 | frontend/src/MemesPage.jsx:88:83 |
| T365 | 待审阅 | 语义索引 | 补充文案候选 | 请先选择并保存 Embedding 模型。 | frontend/src/MemesPage.jsx:89:140 |
| T366 | 待审阅 | 语义索引 | 补充文案候选 | 可以继续聊天，索引进度每 5 秒更新。 | frontend/src/MemesPage.jsx:89:176 |
| T367 | 待审阅 | 语义索引 | 补充文案候选 | 有图片尚未索引，点击构建即可补齐。 | frontend/src/MemesPage.jsx:89:226 |
| T368 | 待审阅 | 语义索引 | 补充文案候选 | 索引可用。修改描述或模型后需要重新构建。 | frontend/src/MemesPage.jsx:89:246 |
| T369 | 待审阅 | 表情包图库 · 〔library.total〕 张 | 悬浮提示 | 表情包图库 · 〔library.total〕 张 | frontend/src/MemesPage.jsx:91:69 |
| T370 | 待审阅 | 表情包图库 · 〔library.total〕 张 | 副标题 | 图库由所有机器人共享；逐图描述、文字和场景可编辑。新增图片先补充描述再启用。 | frontend/src/MemesPage.jsx:91:109 |
| T371 | 待审阅 | 表情包图库 · 〔library.total〕 张 | 输入框占位 | 搜索画面、图中文字或适用场景 | frontend/src/MemesPage.jsx:92:164 |
| T372 | 待审阅 | 表情包图库 · 〔library.total〕 张 | 空状态 | 没有匹配的表情包 / 还没有表情包，可以上传图片。 | frontend/src/MemesPage.jsx:93:30 |
| T373 | 待审阅 | 表情包图库 · 〔library.total〕 张 | 补充文案候选 | 编辑 〔item.name〕 | frontend/src/MemesPage.jsx:93:263 |
| T374 | 待审阅 | 表情包图库 · 〔library.total〕 张 | 说明文字 | 待补充适用场景 | frontend/src/MemesPage.jsx:93:655 |
| T375 | 待审阅 | 表情包图库 · 〔library.total〕 张 | 补充文案候选 | 编辑描述 〔item.name〕 | frontend/src/MemesPage.jsx:93:816 |
| T376 | 待审阅 | 表情包图库 · 〔library.total〕 张 | 补充文案候选 | 删除 〔item.name〕 | frontend/src/MemesPage.jsx:93:956 |
| T377 | 待审阅 | 表情包图库 · 〔library.total〕 张 | 说明文字 | DeepSeek 同人包来自 anka-afk/deepseek-fanart-meme-pack，描述由 DeepSeek Flash 自动生成，可能有识别误差。素材原作者权利及包内 LICENSE 保留；未取得额外商业授权。QQ 官方接入按首帧静态图片发送，NapCat 保留原始动图并按表情发送。 | frontend/src/MemesPage.jsx:95:7 |
| T378 | 待审阅 | 逐图语义描述 | 弹窗说明 | 图片、文字、适用场景共同用于检索。保存后更新索引即可生效。 | frontend/src/MemesPage.jsx:97:242 |
| T379 | 待审阅 | 逐图语义描述 | 补充文案候选 | 图中文字（无则留空） | frontend/src/MemesPage.jsx:97:667 |
| T380 | 待审阅 | 逐图语义描述 | 补充文案候选 | 适用场景（每行一条） | frontend/src/MemesPage.jsx:97:699 |
| T381 | 待审阅 | 逐图语义描述 | 补充文案候选 | 不适用场景（每行一条） | frontend/src/MemesPage.jsx:97:737 |
| T382 | 待审阅 | 逐图语义描述 | 补充文案候选 | 情绪标签（每行一个） | frontend/src/MemesPage.jsx:97:769 |
| T383 | 待审阅 | 逐图语义描述 | 说明文字 | 所有启用此集合的机器人都会受影响。 | frontend/src/MemesPage.jsx:97:1124 |
| T384 | 待审阅 | 逐图语义描述 | 说明文字 | 自动描述模型：〔editor.provenance.model〕；置信度：〔Math.round(draft.confidence*100)〕%。保存即标记已人工核对。 / 自定义图片。请根据画面准确填写，避免语义误配。 | frontend/src/MemesPage.jsx:97:1269 |
| T385 | 待审阅 | 从图库删除表情包？ | 行内说明候选 | 从图库删除表情包？ | frontend/src/MemesPage.jsx:98:208 |
| T386 | 待审阅 | 从图库删除表情包？ | 弹窗说明 | 所有机器人将停止使用此图。已有聊天记录中的图片仍保留。 | frontend/src/MemesPage.jsx:98:232 |

## 连接与模型 / 记忆模型

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T387 | 待审阅 | 〔purpose === 'embedding' ? 'Embedding 嵌入' : 'Rerank 重排'〕供应商 | 补充文案候选 | 〔purpose === 'embedding' ? 'Embedding 嵌入' : 'Rerank 重排'〕供应商 | frontend/src/MemoryModelSelectors.jsx:9:23 |
| T388 | 待审阅 | 〔purpose === 'embedding' ? 'Embedding 嵌入' : 'Rerank 重排'〕供应商 | 字段说明 | 开启长期记忆前必须配置。 / 可选，关闭时使用初步检索顺序。 | frontend/src/MemoryModelSelectors.jsx:9:126 |
| T389 | 待审阅 | 〔purpose === 'embedding' ? 'Embedding' : 'Rerank'〕 模型名称 | 补充文案候选 | 〔purpose === 'embedding' ? 'Embedding' : 'Rerank'〕 模型名称 | frontend/src/MemoryModelSelectors.jsx:12:23 |
| T390 | 待审阅 | 〔purpose === 'embedding' ? 'Embedding' : 'Rerank'〕 模型名称 | 输入框占位 | 模型名称或 Xinference 部署 UID / 填写服务提供的嵌入模型名称 | frontend/src/MemoryModelSelectors.jsx:13:216 |

## 角色记忆

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T391 | 待审阅 | 记忆策略 | 副标题 | 整理实际对话，保留偏好、边界、共同经历和带日期的约定。 | frontend/src/MemoryPage.jsx:27:76 |
| T392 | 待审阅 | 记忆策略 | 说明文字 | 需先配置独立的 Embedding；Rerank 可选。已有记忆不会因关闭开关被删除。 | frontend/src/MemoryPage.jsx:28:59 |
| T393 | 待审阅 | 记忆策略 | 行内说明候选 | 配置 Embedding 与 Rerank 模型 | frontend/src/MemoryPage.jsx:29:74 |
| T394 | 待审阅 | 记忆策略 → 每几轮整理一次 | 字段说明 | 1–30 轮；停止聊天 30 秒后也会整理待处理消息。 | frontend/src/MemoryPage.jsx:31:50 |
| T395 | 待审阅 | 记忆策略 → 每次选入的记忆数 | 字段说明 | 相关记忆最多 1–30 条，固定保留项优先。 | frontend/src/MemoryPage.jsx:31:111 |
| T396 | 待审阅 | 记忆策略 → 初步检索条数 | 字段说明 | 全文与语义检索候选，5–100 条。 | frontend/src/MemoryPage.jsx:31:173 |
| T397 | 待审阅 | 记忆策略 → 记忆上下文字符预算 | 字段说明 | 包括摘要与相关记忆，500–16000 字符。 | frontend/src/MemoryPage.jsx:31:239 |
| T398 | 待审阅 | 记忆策略 → 检索接口超时（秒） | 字段说明 | 5–120 秒；接口异常时使用全文检索。 | frontend/src/MemoryPage.jsx:31:300 |
| T399 | 待审阅 | 记忆策略 | 行内说明候选 | 查看当前用户的长期记忆 | frontend/src/MemoryPage.jsx:33:116 |
| T400 | 待审阅 | 记忆策略 | 行内说明候选 | 遗忘并防止旧聊天重新提取 | frontend/src/MemoryPage.jsx:33:170 |
| T401 | 待审阅 | 记忆策略 | 行内说明候选 | 先说明影响，二次确认后清空当前用户的上下文与长期记忆 | frontend/src/MemoryPage.jsx:33:225 |
| T402 | 待审阅 | 记忆策略 | 说明文字 | 策略修改保存后生效，下方记忆操作立即生效。 | frontend/src/MemoryPage.jsx:34:17 |
| T403 | 待审阅 | 用户记忆 | 空状态 | 选择用户后查看与管理对应记忆。 | frontend/src/MemoryPage.jsx:37:162 |
| T404 | 待审阅 | MemoryPage.jsx | 操作反馈与确认 | 重要度请填写 0–100 的整数 | frontend/src/MemoryPage.jsx:65:107 |
| T405 | 待审阅 | MemoryPage.jsx | 操作反馈与确认 | 记忆已保存，后续对话使用新信息 | frontend/src/MemoryPage.jsx:70:152 |
| T406 | 待审阅 | 摘要与检索 | 副标题 | 记忆原文、来源与摘要保存在本机；调用外部模型时只发送此用户范围内的资料。 | frontend/src/MemoryPage.jsx:78:70 |
| T407 | 待审阅 | 摘要与检索 | 操作反馈与确认 | 已安排重建此用户的索引 | frontend/src/MemoryPage.jsx:79:583 |
| T408 | 待审阅 | 摘要与检索 | 说明文字 | 还没有摘要。正常聊天后会自动整理，也可点击「整理最近聊天」。 | frontend/src/MemoryPage.jsx:81:54 |
| T409 | 待审阅 | 摘要与检索 | 行内说明候选 | 有整理任务失败，原始聊天已保留。 | frontend/src/MemoryPage.jsx:82:55 |
| T410 | 待审阅 | 长期记忆 | 副标题 | 〔snapshot.owner.label〕 · 共 〔snapshot.total〕 条有效记忆 / 正在读取… | frontend/src/MemoryPage.jsx:85:34 |
| T411 | 待审阅 | 长期记忆 | 输入框占位 | 搜索当前页内容或类型 | frontend/src/MemoryPage.jsx:86:98 |
| T412 | 待审阅 | 长期记忆 | 空状态 | 当前页没有匹配的记忆。 / 还没有保存长期记忆。重要偏好会从真实对话中整理，也可以手动添加。 | frontend/src/MemoryPage.jsx:87:24 |
| T413 | 待审阅 | 长期记忆 | 补充文案候选 | 编辑记忆 〔item.id〕 | frontend/src/MemoryPage.jsx:88:392 |
| T414 | 待审阅 | 长期记忆 | 补充文案候选 | 遗忘记忆 〔item.id〕 | frontend/src/MemoryPage.jsx:88:532 |
| T415 | 待审阅 | 长期记忆 | 说明文字 | 〔at(item.due_at)〕 — 〔at(item.end_at)〕 · 时间已过，未经确认履行 | frontend/src/MemoryPage.jsx:90:44 |
| T416 | 待审阅 | 记忆修改记录 | 副标题 | 最近 50 次新增、更正与遗忘；遗忘后的内容不会保留在此记录里。 | frontend/src/MemoryPage.jsx:95:81 |
| T417 | 待审阅 | 记忆修改记录 | 空状态 | 还没有记忆修改记录。 | frontend/src/MemoryPage.jsx:96:35 |
| T418 | 待审阅 | 记忆修改记录 | 说明文字 | 修改前：〔record.before.content〕 | frontend/src/MemoryPage.jsx:96:443 |
| T419 | 待审阅 | 记忆修改记录 | 说明文字 | 修改后：〔record.after.content〕 | frontend/src/MemoryPage.jsx:96:511 |
| T420 | 待审阅 | 记忆修改记录 | 说明文字 | 记忆已到期，不再参与检索，摘要与近期上下文已清理。 | frontend/src/MemoryPage.jsx:96:583 |
| T421 | 待审阅 | 记忆修改记录 | 说明文字 | 用户通过 /reset 二次确认，已清空上下文和全部长期记忆（0 条），后台聊天档案保留。 | frontend/src/MemoryPage.jsx:96:646 |
| T422 | 待审阅 | 记忆修改记录 | 说明文字 | 内容已遗忘，相关旧任务与摘要已失效。 | frontend/src/MemoryPage.jsx:96:755 |
| T423 | 待审阅 | 编辑记忆 / 添加记忆 | 弹窗说明 | 仅影响当前用户。保存后立即生效，并清理可能含旧信息的摘要与近期上下文。 | frontend/src/MemoryPage.jsx:98:276 |
| T424 | 待审阅 | 编辑记忆 / 添加记忆 → 记忆内容 | 输入框占位 | 例如：用户不喝咖啡，喜欢清淡的茶。 | frontend/src/MemoryPage.jsx:98:967 |
| T425 | 待审阅 | 编辑记忆 / 添加记忆 | 说明文字 | 优先加入对话记忆，仍受单次上下文预算限制。 | frontend/src/MemoryPage.jsx:98:1262 |
| T426 | 待审阅 | 编辑记忆 / 添加记忆 → 开始时间 | 字段说明 | 按当前设备时区填写，保存时转换为带时区的具体时间。 | frontend/src/MemoryPage.jsx:98:1506 |
| T427 | 待审阅 | 编辑记忆 / 添加记忆 → 到期时间（可选） | 字段说明 | 到期后不再参与检索，留空长期保留。 | frontend/src/MemoryPage.jsx:98:2292 |
| T428 | 待审阅 | 遗忘这条记忆？ | 行内说明候选 | 遗忘这条记忆？ | frontend/src/MemoryPage.jsx:99:216 |
| T429 | 待审阅 | 遗忘这条记忆？ | 弹窗说明 | 仅遗忘当前用户的此条记忆，清理相关摘要和近期上下文，并阻止旧聊天再次提取。原始聊天档案保留。 | frontend/src/MemoryPage.jsx:99:238 |
| T430 | 待审阅 | 记忆来源 | 弹窗说明 | 记忆 #〔sources?.item.id〕，只显示当前用户范围内的来源消息。 | frontend/src/MemoryPage.jsx:100:240 |
| T431 | 待审阅 | 记忆来源 | 说明文字 | 此记忆由管理员手动添加，没有关联的聊天消息。 | frontend/src/MemoryPage.jsx:100:741 |

## 主动互动

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T432 | 待审阅 | ProactivePage.jsx | 补充文案候选 | 自然地关心一下近况，避免重复问候。 | frontend/src/ProactivePage.jsx:17:88 |
| T433 | 待审阅 | 基本设置 | 副标题 | 仅向选定的单聊发送，使用当前人格与最近文字上下文 | frontend/src/ProactivePage.jsx:40:34 |
| T434 | 待审阅 | 基本设置 | 说明文字 | 机器人停止时，自动消息一起暂停。 | frontend/src/ProactivePage.jsx:41:59 |
| T435 | 待审阅 | 基本设置 → 单聊接收者 | 字段说明 | 先在 QQ 单聊机器人，再刷新接收者。 | frontend/src/ProactivePage.jsx:43:55 |
| T436 | 待审阅 | 基本设置 → 活跃时段结束 | 字段说明 | 其余时间免打扰；起止相同表示全天。 | frontend/src/ProactivePage.jsx:46:50 |
| T437 | 待审阅 | 基本设置 | 说明文字 | 问候、搭话与提醒共享额度，QQ 平台仍可能限流。 | frontend/src/ProactivePage.jsx:47:96 |
| T438 | 待审阅 | 基本设置 → 每日自动消息上限 | 字段说明 | 正整数为次数上限，0 表示不限次数。 | frontend/src/ProactivePage.jsx:47:407 |
| T439 | 待审阅 | 基本设置 → 冷却时间（分钟） | 字段说明 | 0–1440 分钟，0 表示不冷却。 | frontend/src/ProactivePage.jsx:48:57 |
| T440 | 待审阅 | 基本设置 → 未回应暂停（次） | 字段说明 | 1–20 次；收到新单聊后恢复。 | frontend/src/ProactivePage.jsx:49:59 |
| T441 | 待审阅 | 主动搭话 | 副标题 | 在随机间隔后自然地发起聊天 | frontend/src/ProactivePage.jsx:52:34 |
| T442 | 待审阅 | 主动搭话 | 说明文字 | 正在聊天或回复时跳过；连续未回应时暂停。 | frontend/src/ProactivePage.jsx:53:59 |
| T443 | 待审阅 | 主动搭话 → 最短间隔（分钟） | 字段说明 | 5–1440 分钟（最长 24 小时）。 | frontend/src/ProactivePage.jsx:54:129 |
| T444 | 待审阅 | 主动搭话 → 最长间隔（分钟） | 字段说明 | 5–1440 分钟，不能小于最短间隔。 | frontend/src/ProactivePage.jsx:54:360 |
| T445 | 待审阅 | ProactivePage.jsx | 辅助文字 | 〔config.greetings.map(rule => rule.name).join(' · ')〕 / 尚未添加 | frontend/src/ProactivePage.jsx:56:63 |
| T446 | 待审阅 | ProactivePage.jsx | 说明文字 | 按所选时区每天触发，错过时段后不集中补发。 | frontend/src/ProactivePage.jsx:56:244 |
| T447 | 待审阅 | ProactivePage.jsx | 补充文案候选 | 简短自然地问候一下。 | frontend/src/ProactivePage.jsx:59:280 |
| T448 | 待审阅 | 内容预览 | 副标题 | 生成示例但不发送，生成用量计入 Token 统计 | frontend/src/ProactivePage.jsx:60:34 |
| T449 | 待审阅 | 内容预览 | 输入框占位 | 希望它主动说些什么？ | frontend/src/ProactivePage.jsx:61:143 |
| T450 | 待审阅 | 一次性提醒 | 副标题 | 按指定时间发送固定文字 | frontend/src/ProactivePage.jsx:65:88 |
| T451 | 待审阅 | 一次性提醒 → 提醒时间（设备时区） | 补充文案候选 | 提醒时间（设备时区） | frontend/src/ProactivePage.jsx:67:49 |
| T452 | 待审阅 | 一次性提醒 → 提醒内容 | 输入框占位 | 例如：拿快递 | frontend/src/ProactivePage.jsx:67:362 |
| T453 | 待审阅 | 一次性提醒 | 说明文字 | 受总开关、连接、活跃时段与日上限约束；超过设定时间 5 分钟后不补发。 | frontend/src/ProactivePage.jsx:70:7 |
| T454 | 待审阅 | 一次性提醒 | 空状态 | 暂无提醒 | frontend/src/ProactivePage.jsx:71:507 |
| T455 | 待审阅 | 推送状态 | 补充文案候选 | 〔config.daily_limit〕 次 | frontend/src/ProactivePage.jsx:75:166 |
| T456 | 待审阅 | 推送状态 | 说明文字 | 正在生成或发送消息 / 等待下一次触发 | frontend/src/ProactivePage.jsx:76:7 |
| T457 | 待审阅 | 推送状态 | 说明文字 | 下次搭话候选：〔showTime(contact.next_idle)〕 | frontend/src/ProactivePage.jsx:77:34 |
| T458 | 待审阅 | 推送状态 | 说明文字 | 测试会真实发送给接收者，每分钟最多一次。请先保存并启动机器人。 | frontend/src/ProactivePage.jsx:79:7 |
| T459 | 待审阅 | 推送状态 | 说明文字 | 最近互动：〔showTime(contact.last_received)〕 | frontend/src/ProactivePage.jsx:80:19 |
| T460 | 待审阅 | 推送状态 | 说明文字 | 〔contact.capability_detail〕验证时间：〔showTime(contact.checked_at)〕 | frontend/src/ProactivePage.jsx:81:38 |
| T461 | 待审阅 | 推送状态 | 说明文字 | 状态刷新失败：〔error〕 | frontend/src/ProactivePage.jsx:82:17 |
| T462 | 待审阅 | 发送记录 | 副标题 | 实际结果与跳过原因 | frontend/src/ProactivePage.jsx:84:34 |
| T463 | 待审阅 | 发送记录 | 说明文字 | 处理中 | frontend/src/ProactivePage.jsx:84:307 |
| T464 | 待审阅 | 发送记录 | 空状态 | 暂无发送记录 | frontend/src/ProactivePage.jsx:84:343 |
| T465 | 待审阅 | ProactivePage.jsx | 提示框 | 主动推送权限以 QQ 接口为准。被拒绝后自动暂停，需手动重新测试；结果未知的消息不会自动重发。 | frontend/src/ProactivePage.jsx:85:5 |

## 共享供应商 / 模型分配

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T466 | 待审阅 | OpenAI Embedding | 配置说明 | 支持 OpenAI 与兼容嵌入接口，使用 /embeddings。 | frontend/src/ProvidersPage.jsx:14:112 |
| T467 | 待审阅 | Gemini Embedding | 配置说明 | 使用 Gemini 原生嵌入接口，自动区分入库与查询任务。 | frontend/src/ProvidersPage.jsx:15:135 |
| T468 | 待审阅 | Ollama Embedding | 配置说明 | 支持本地或外部 Ollama。原生使用 /api/embed，以 /v1 结尾时使用兼容嵌入接口。 | frontend/src/ProvidersPage.jsx:16:106 |
| T469 | 待审阅 | DashScope Embedding | 配置说明 | 使用 DashScope 原生文本嵌入接口。地址按 API Key 所属地域与业务空间填写。 | frontend/src/ProvidersPage.jsx:17:130 |
| T470 | 待审阅 | DashScope Rerank | 配置说明 | 使用 DashScope 原生文本重排接口，填写对应地域与业务空间地址。 | frontend/src/ProvidersPage.jsx:18:121 |
| T471 | 待审阅 | Xinference Rerank | 配置说明 | 使用 /v1/rerank，模型名称填写已经部署的模型 UID。 | frontend/src/ProvidersPage.jsx:19:121 |
| T472 | 待审阅 | Ollama | 配置说明 | 本地与外部 Ollama 共用此类型。Docker 内置：http://ollama:11434；宿主机：http://host.docker.internal:11434；外部服务填写实际地址。以 /v1 结尾时自动使用兼容接口。 | frontend/src/ProvidersPage.jsx:20:64 |
| T473 | 待审阅 | OpenAI Compatible | 配置说明 | 使用 Chat Completions 协议。填写 API 基础地址，例如 https://api.openai.com/v1；兼容服务请填写其基础地址。 | frontend/src/ProvidersPage.jsx:21:86 |
| T474 | 待审阅 | OpenAI Responses | 配置说明 | 使用 Responses 协议。填写 API 基础地址，例如 https://api.openai.com/v1。 | frontend/src/ProvidersPage.jsx:22:90 |
| T475 | 待审阅 | Anthropic Compatible | 配置说明 | 使用 Messages 协议，API Key 通过 x-api-key 发送。填写基础地址，例如 https://api.anthropic.com/v1。 | frontend/src/ProvidersPage.jsx:23:90 |
| T476 | 待审阅 | DeepSeek | 配置说明 | 使用 DeepSeek Chat Completions 协议。官方地址为 https://api.deepseek.com，也可配置兼容服务。 | frontend/src/ProvidersPage.jsx:24:73 |
| T477 | 待审阅 | ProvidersPage.jsx | 补充文案候选 | Embedding 嵌入 | frontend/src/ProvidersPage.jsx:26:43 |
| T478 | 待审阅 | ProvidersPage.jsx | 操作反馈与确认 | 请填写默认模型名称，再进行实际调用测试 | frontend/src/ProvidersPage.jsx:55:84 |
| T479 | 待审阅 | ProvidersPage.jsx | 操作反馈与确认 | 请先选择或填写模型名称 | frontend/src/ProvidersPage.jsx:68:58 |
| T480 | 待审阅 | ProvidersPage.jsx | 操作反馈与确认 | 请填写温度、超时和输出 Token 上限 | frontend/src/ProvidersPage.jsx:69:150 |
| T481 | 待审阅 | 当前机器人的模型 | 副标题 | 每个 Bot 独立选择供应商、模型与生成参数；共享连接在工作空间的「共享供应商」中管理。 | frontend/src/ProvidersPage.jsx:85:49 |
| T482 | 待审阅 | 当前机器人的模型 → 模型供应商 | 字段说明 | 可以添加多个同类型供应商，并用名称区分本地、外部服务或不同账号。 | frontend/src/ProvidersPage.jsx:87:58 |
| T483 | 待审阅 | 当前机器人的模型 → 使用模型 | 字段说明 | 从下方模型列表选择，也可手动填写模型名称或模型别名。 | frontend/src/ProvidersPage.jsx:88:54 |
| T484 | 待审阅 | 当前机器人的模型 → 使用模型 | 输入框占位 | 选择或填写模型名称 | frontend/src/ProvidersPage.jsx:88:216 |
| T485 | 待审阅 | 当前机器人的模型 → 请求超时（秒） | 字段说明 | 默认 120 秒，可设 5–600 秒（最长 10 分钟）。QQ 回复仍受消息有效期限制。 | frontend/src/ProvidersPage.jsx:89:59 |
| T486 | 待审阅 | 当前机器人的模型 → 温度 | 字段说明 | 此供应商关闭温度参数，实际使用服务默认值。 / 0–1，较低时回答更稳定。 / 0–2，较低时回答更稳定。 | frontend/src/ProvidersPage.jsx:90:58 |
| T487 | 待审阅 | 当前机器人的模型 → 输出 Token 上限 | 补充文案候选 | 输出 Token 上限 | frontend/src/ProvidersPage.jsx:91:22 |
| T488 | 待审阅 | 当前机器人的模型 → 输出 Token 上限 | 字段说明 | 128–32768，默认 1024；推理模型可适当增大，以留出思考与正文的预算。 | frontend/src/ProvidersPage.jsx:91:66 |
| T489 | 待审阅 | 当前机器人的模型 | 辅助文字 | 使用当前填写的模型参数，测试不会发送 QQ 消息。 | frontend/src/ProvidersPage.jsx:94:482 |
| T490 | 待审阅 | 当前机器人的模型 | 辅助文字 | 本次测试：输入 〔result.input_tokens〕 / 输出 〔result.output_tokens〕 Token；不计入 Bot 聊天统计。 | frontend/src/ProvidersPage.jsx:96:79 |
| T491 | 待审阅 | 当前机器人的记忆模型 | 补充文案候选 | 当前机器人的记忆模型 | frontend/src/ProvidersPage.jsx:99:29 |
| T492 | 待审阅 | 当前机器人的记忆模型 | 副标题 | 与对话模型独立配置；可共用供应商连接，用户记忆始终隔离。 | frontend/src/ProvidersPage.jsx:99:51 |
| T493 | 待审阅 | 供应商连接 | 副标题 | 所有 Bot 共用的连接目录 · API Key 加密保存，不回传原文 | frontend/src/ProvidersPage.jsx:100:57 |
| T494 | 待审阅 | 供应商连接 | 说明文字 | 默认模型 · 〔item.default_model〕 | frontend/src/ProvidersPage.jsx:101:467 |
| T495 | 待审阅 | 供应商连接 | 补充文案候选 | 已保存 API Key | frontend/src/ProvidersPage.jsx:101:648 |
| T496 | 待审阅 | 供应商连接 | 补充文案候选 | 未设置 API Key | frontend/src/ProvidersPage.jsx:101:664 |
| T497 | 待审阅 | 供应商连接 | 补充文案候选 | 编辑 〔item.name〕 | frontend/src/ProvidersPage.jsx:101:1236 |
| T498 | 待审阅 | 供应商连接 | 空状态 | 暂无供应商，添加一个连接开始配置。 | frontend/src/ProvidersPage.jsx:101:1322 |
| T499 | 待审阅 | ProvidersPage.jsx | 提示框 | Ollama 本地与外部连接可同时添加。服务地址由 Python 后台访问；其他协议也支持填写自建兼容服务地址。修改共享连接会影响使用它的 Bot，并清空模型上下文（聊天档案保留），请先停止相关机器人。模型须具备相应的文字或视觉能力。 | frontend/src/ProvidersPage.jsx:102:13 |
| T500 | 待审阅 | 手机与素材模型 | 副标题 | 独立保存的模型配置有各自入口，保留当前设置的作用范围。 | frontend/src/ProvidersPage.jsx:104:58 |
| T501 | 待审阅 | 手机与素材模型 | 辅助文字 | 查看与修改视觉供应商、模型和任务预算 | frontend/src/ProvidersPage.jsx:104:267 |
| T502 | 待审阅 | 手机与素材模型 | 辅助文字 | 查看与修改 Embedding 和可选 Rerank | frontend/src/ProvidersPage.jsx:104:450 |
| T503 | 待审阅 | ProvidersPage.jsx | 行内说明候选 | 管理共享供应商连接 → | frontend/src/ProvidersPage.jsx:104:632 |
| T504 | 待审阅 | 编辑模型供应商 / 添加模型供应商 | 弹窗说明 | 连接供所有 Bot 选择。名称留空自动生成，例如 ollama-1、ollama-2。 | frontend/src/ProvidersPage.jsx:105:283 |
| T505 | 待审阅 | 编辑模型供应商 / 添加模型供应商 → 自定义名称 | 输入框占位 | 留空自动命名 | frontend/src/ProvidersPage.jsx:105:600 |
| T506 | 待审阅 | 编辑模型供应商 / 添加模型供应商 → 默认模型（可选） | 字段说明 | Bot 选择此供应商时自动填入；不会更改已保存的 Bot 模型。 | frontend/src/ProvidersPage.jsx:105:697 |
| T507 | 待审阅 | 编辑模型供应商 / 添加模型供应商 → 默认模型（可选） | 输入框占位 | 例如：gemma4:latest | frontend/src/ProvidersPage.jsx:105:887 |
| T508 | 待审阅 | 编辑模型供应商 / 添加模型供应商 | 提示框 | 此连接正在被机器人使用，目前可修改名称、默认模型与对话 Thinking。 | frontend/src/ProvidersPage.jsx:105:948 |
| T509 | 待审阅 | 编辑模型供应商 / 添加模型供应商 → Ollama 接口模式 | 补充文案候选 | Ollama 接口模式 | frontend/src/ProvidersPage.jsx:109:76 |
| T510 | 待审阅 | 编辑模型供应商 / 添加模型供应商 → Ollama 接口模式 | 字段说明 | 自动模式：/v1 地址使用 OpenAI 兼容接口，其他地址使用 Ollama 原生 API。 | frontend/src/ProvidersPage.jsx:109:116 |
| T511 | 待审阅 | 编辑模型供应商 / 添加模型供应商 → Ollama 接口模式 | 行内说明候选 | Ollama 原生 API | frontend/src/ProvidersPage.jsx:109:366 |
| T512 | 待审阅 | 编辑模型供应商 / 添加模型供应商 → Ollama 接口模式 | 行内说明候选 | OpenAI 兼容 API | frontend/src/ProvidersPage.jsx:109:411 |
| T513 | 待审阅 | 编辑模型供应商 / 添加模型供应商 → API Key | 字段说明 | 留空保留原 Key；更换地址或协议时留空会清除原 Key。勾选下方开关可主动清除。 / 可选。本地 Ollama 通常无需填写；外部服务按其要求填写。 | frontend/src/ProvidersPage.jsx:110:53 |
| T514 | 待审阅 | 编辑模型供应商 / 添加模型供应商 → API Key | 输入框占位 | •••••••• 已加密保存 / 填写 API Key（可选） | frontend/src/ProvidersPage.jsx:110:361 |
| T515 | 待审阅 | 编辑模型供应商 / 添加模型供应商 | 行内说明候选 | 清除已保存的 API Key | frontend/src/ProvidersPage.jsx:111:64 |
| T516 | 待审阅 | 编辑模型供应商 / 添加模型供应商 | 说明文字 | 保存后生效，不影响尚未保存的连接。 | frontend/src/ProvidersPage.jsx:111:85 |
| T517 | 待审阅 | 编辑模型供应商 / 添加模型供应商 | 补充文案候选 | 清除已保存的 API Key | frontend/src/ProvidersPage.jsx:111:134 |
| T518 | 待审阅 | 编辑模型供应商 / 添加模型供应商 → 向量维度（可选） | 字段说明 | 留空使用模型默认值。更换模型或维度后需要重建用户记忆索引。 | frontend/src/ProvidersPage.jsx:112:96 |
| T519 | 待审阅 | 编辑模型供应商 / 添加模型供应商 | 说明文字 | 所选模型需支持视觉；Ollama 还会检查模型能力。 | frontend/src/ProvidersPage.jsx:113:82 |
| T520 | 待审阅 | 编辑模型供应商 / 添加模型供应商 | 说明文字 | 若模型拒绝 temperature，可关闭使用服务默认值。 | frontend/src/ProvidersPage.jsx:114:173 |
| T521 | 待审阅 | 编辑模型供应商 / 添加模型供应商 → 输出 Token 限制字段 | 补充文案候选 | 输出 Token 限制字段 | frontend/src/ProvidersPage.jsx:114:391 |
| T522 | 待审阅 | 编辑模型供应商 / 添加模型供应商 → 输出 Token 限制字段 | 字段说明 | 一般兼容服务使用 max_tokens；要求新字段的模型使用 max_completion_tokens。 | frontend/src/ProvidersPage.jsx:114:435 |
| T523 | 待审阅 | 编辑模型供应商 / 添加模型供应商 → Anthropic API 版本 | 补充文案候选 | Anthropic API 版本 | frontend/src/ProvidersPage.jsx:114:826 |
| T524 | 待审阅 | 编辑模型供应商 / 添加模型供应商 → Anthropic API 版本 | 字段说明 | 兼容服务通常使用 2023-06-01。2026-10-21 版本不发送温度参数。 | frontend/src/ProvidersPage.jsx:114:873 |
| T525 | 待审阅 | 编辑模型供应商 / 添加模型供应商 → Anthropic API 版本 | 行内说明候选 | 2023-06-01（兼容） | frontend/src/ProvidersPage.jsx:114:1103 |
| T526 | 待审阅 | 编辑模型供应商 / 添加模型供应商 | 行内说明候选 | 对话 Thinking | frontend/src/ProvidersPage.jsx:115:79 |
| T527 | 待审阅 | 编辑模型供应商 / 添加模型供应商 | 说明文字 | 仅控制普通聊天回复，默认关闭以减少等待。日程、记忆整理和主动消息保持原有行为；需模型支持。保存后从下一次对话请求生效。 | frontend/src/ProvidersPage.jsx:115:97 |
| T528 | 待审阅 | 编辑模型供应商 / 添加模型供应商 | 补充文案候选 | 对话 Thinking | frontend/src/ProvidersPage.jsx:115:188 |
| T529 | 待审阅 | 编辑模型供应商 / 添加模型供应商 | 说明文字 | 删除“〔editor.name〕”的连接与密钥？此操作无法恢复。 | frontend/src/ProvidersPage.jsx:116:111 |
| T530 | 待审阅 | 编辑模型供应商 / 添加模型供应商 | 说明文字 | 正在使用：〔editor.used_by.map(bot => `${bot.name}${bot.archived ? '（已归档）' : ''}`).join('、')〕。解除所有引用后可删除。 | frontend/src/ProvidersPage.jsx:117:39 |

## 机器人管理 / 扫码添加

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T531 | 待审阅 | QQConnectDialog.jsx | 操作反馈与确认 | 二维码图片生成失败，可使用下方 QQ 官方授权链接 | frontend/src/QQConnectDialog.jsx:34:219 |
| T532 | 待审阅 | 扫码添加 QQ 机器人 | 行内说明候选 | 扫码添加 QQ 机器人 | frontend/src/QQConnectDialog.jsx:67:241 |
| T533 | 待审阅 | 扫码添加 QQ 机器人 | 弹窗说明 | 使用手机 QQ 扫码并完成官方授权，自动获取凭证；完成添加后立即启动并连接 QQ。 | frontend/src/QQConnectDialog.jsx:67:267 |
| T534 | 待审阅 | 扫码添加 QQ 机器人 → 机器人名称（可选） | 字段说明 | 留空将按 AppID 自动命名，之后可以修改。 | frontend/src/QQConnectDialog.jsx:68:52 |
| T535 | 待审阅 | 扫码添加 QQ 机器人 → 机器人名称（可选） | 输入框占位 | 例如：工作助手 | frontend/src/QQConnectDialog.jsx:68:190 |
| T536 | 待审阅 | 扫码添加 QQ 机器人 | 说明文字 | 正在获取 QQ 官方二维码… | frontend/src/QQConnectDialog.jsx:69:121 |
| T537 | 待审阅 | 扫码添加 QQ 机器人 | 补充文案候选 | QQ 官方机器人授权二维码 | frontend/src/QQConnectDialog.jsx:69:236 |
| T538 | 待审阅 | 扫码添加 QQ 机器人 | 行内说明候选 | 打开 QQ 官方授权页面 | frontend/src/QQConnectDialog.jsx:69:407 |
| T539 | 待审阅 | 扫码添加 QQ 机器人 | 补充文案候选 | 已添加，正在连接 QQ | frontend/src/QQConnectDialog.jsx:69:579 |
| T540 | 待审阅 | 扫码添加 QQ 机器人 | 说明文字 | AppID · 〔binding.app_id〕 | frontend/src/QQConnectDialog.jsx:69:614 |
| T541 | 待审阅 | 扫码添加 QQ 机器人 | 说明文字 | 暂未获得二维码，请重试 | frontend/src/QQConnectDialog.jsx:69:673 |
| T542 | 待审阅 | 扫码添加 QQ 机器人 | 提示框 | 此 AppID 已属于“〔existing.name〕”，将更新该机器人的凭证，保留原配置和聊天记录，不创建重复 Bot。请先在机器人管理中恢复该机器人。 / 请先在其他页面停止该机器人，再回到这里确认。 / 请确认更新。 | frontend/src/QQConnectDialog.jsx:70:18 |
| T543 | 待审阅 | 扫码添加 QQ 机器人 | 说明文字 | QQ 授权页可能将 HayBot 显示为“第三方机器人”。请核对官方域名 q.qq.com 后授权；凭证仅在后台解密、加密保存。二维码过期或关闭窗口后需重新扫码。 | frontend/src/QQConnectDialog.jsx:72:5 |

## 主动互动 / QQ 空间

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T544 | 待审阅 | QQ 号列表 | 字段说明 | 使用逗号或空格分隔。 | frontend/src/QzonePage.jsx:20:422 |
| T545 | 待审阅 | QzonePage.jsx | 操作反馈与确认 | 请选择未来的发布时间 | frontend/src/QzonePage.jsx:43:129 |
| T546 | 待审阅 | QzonePage.jsx | 操作反馈与确认 | 单张配图不能超过10MB | frontend/src/QzonePage.jsx:61:51 |
| T547 | 待审阅 | QzonePage.jsx | 提示框 | 正在读取空间配置… | frontend/src/QzonePage.jsx:73:32 |
| T548 | 待审阅 | QQ 空间 | 副标题 | 此功能需要 NapCat 登录的 QQ 账号。 | frontend/src/QzonePage.jsx:74:63 |
| T549 | 待审阅 | QQ 空间 | 说明文字 | 当前为官方机器人接入。请切换到已有 NapCat 机器人，再管理动态。 | frontend/src/QzonePage.jsx:74:89 |
| T550 | 待审阅 | QzonePage.jsx | 提示框 | NapCat 尚未连接，可以编辑草稿；发布前请启动机器人。 | frontend/src/QzonePage.jsx:78:27 |
| T551 | 待审阅 | 编辑动态草稿 / 写一条动态 | 副标题 | 发布到当前 NapCat 账号的 QQ 空间，默认仅自己可见。 | frontend/src/QzonePage.jsx:79:95 |
| T552 | 待审阅 | 编辑动态草稿 / 写一条动态 → 动态正文 | 输入框占位 | 分享此刻的想法… | frontend/src/QzonePage.jsx:80:222 |
| T553 | 待审阅 | 编辑动态草稿 / 写一条动态 | 输入框占位 | 可选：本次生成要求，例如轻松地分享校园生活 | frontend/src/QzonePage.jsx:81:156 |
| T554 | 待审阅 | 编辑动态草稿 / 写一条动态 | 操作反馈与确认 | 正文已生成，请检查后发布 | frontend/src/QzonePage.jsx:81:389 |
| T555 | 待审阅 | 编辑动态草稿 / 写一条动态 | 说明文字 | 绑定 Owner 后，只使用其私聊和对应日程作为生活素材，不读取其他用户；仅参考已经开始的活动和已发生的事件。正文会隐藏身份、联系方式和聊天原话，生成后可编辑。 | frontend/src/QzonePage.jsx:82:9 |
| T556 | 待审阅 | 编辑动态草稿 / 写一条动态 | 补充文案候选 | 配图 〔i+1〕 | frontend/src/QzonePage.jsx:83:118 |
| T557 | 待审阅 | 编辑动态草稿 / 写一条动态 | 补充文案候选 | 移除配图 〔i+1〕 | frontend/src/QzonePage.jsx:83:188 |
| T558 | 待审阅 | 编辑动态草稿 / 写一条动态 | 说明文字 | 单张10MB，配图总计20MB；动图取首帧。 | frontend/src/QzonePage.jsx:85:217 |
| T559 | 待审阅 | 编辑动态草稿 / 写一条动态 → 一次定时发布（可选） | 补充文案候选 | 一次定时发布（可选） | frontend/src/QzonePage.jsx:86:111 |
| T560 | 待审阅 | 编辑动态草稿 / 写一条动态 → 一次定时发布（可选） | 字段说明 | 按当前设备时区填写；留空保存为草稿。 | frontend/src/QzonePage.jsx:86:145 |
| T561 | 待审阅 | 随机分享与 Owner | 补充文案候选 | 随机分享与 Owner | frontend/src/QzonePage.jsx:90:70 |
| T562 | 待审阅 | 随机分享与 Owner | 副标题 | 由生活和对话触发分享欲，随机等待后再决定，不按固定时刻打卡。 | frontend/src/QzonePage.jsx:90:93 |
| T563 | 待审阅 | 随机分享与 Owner | 说明文字 | 活跃时段内随机评估，允许跳过或一天不发。需要 NapCat 在线。 | frontend/src/QzonePage.jsx:92:63 |
| T564 | 待审阅 | 随机分享与 Owner → Owner QQ 号 | 补充文案候选 | Owner QQ 号 | frontend/src/QzonePage.jsx:94:24 |
| T565 | 待审阅 | 随机分享与 Owner → Owner QQ 号 | 字段说明 | 每个 Bot 单独填写，可随时修改或清空。仅作为素材来源，不改变下面设置的可见范围。 | frontend/src/QzonePage.jsx:94:62 |
| T566 | 待审阅 | 随机分享与 Owner → Owner QQ 号 | 输入框占位 | 填写与你对话的 Owner QQ 号 | frontend/src/QzonePage.jsx:94:297 |
| T567 | 待审阅 | 随机分享与 Owner | 说明文字 | 未绑定 Owner，不会自动读取任何人的聊天和日程。 / 已找到此 Owner 的单聊范围。 / Owner 需先私聊此机器人，建立独立对话范围后才会自动分享。修改 Owner 会让旧的自动素材及待发任务失效。 | frontend/src/QzonePage.jsx:95:11 |
| T568 | 待审阅 | 随机分享与 Owner → 活跃时段结束 | 字段说明 | 00:00 表示午夜；开始与结束相同表示全天。 | frontend/src/QzonePage.jsx:96:279 |
| T569 | 待审阅 | 随机分享与 Owner | 补充文案候选 | 随机评估最短间隔（分钟） | frontend/src/QzonePage.jsx:97:37 |
| T570 | 待审阅 | 随机分享与 Owner | 补充文案候选 | 随机评估最长间隔（分钟） | frontend/src/QzonePage.jsx:97:86 |
| T571 | 待审阅 | 随机分享与 Owner | 补充文案候选 | 新事件最短等待（分钟） | frontend/src/QzonePage.jsx:97:132 |
| T572 | 待审阅 | 随机分享与 Owner | 补充文案候选 | 新事件最长等待（分钟） | frontend/src/QzonePage.jsx:97:177 |
| T573 | 待审阅 | 随机分享与 Owner | 补充文案候选 | 两条动态最短间隔（分钟） | frontend/src/QzonePage.jsx:97:221 |
| T574 | 待审阅 | 随机分享与 Owner | 字段说明 | 0 表示不限次数，上限不是每天必发数量。 / 0–1，越高越容易进入模型评估；模型仍可决定不发。 / 〔undefined〕 | frontend/src/QzonePage.jsx:97:407 |
| T575 | 待审阅 | 随机分享与 Owner → 内容来源 | 行内说明候选 | 按 Owner 日程与聊天自然生成 | frontend/src/QzonePage.jsx:98:364 |
| T576 | 待审阅 | 随机分享与 Owner → 内容来源 | 行内说明候选 | 固定正文（避免重复发布） | frontend/src/QzonePage.jsx:98:412 |
| T577 | 待审阅 | 随机分享与 Owner → 额外可公开素材 | 字段说明 | 可补充已发生的经历或穿搭；不要填写身份、联系方式或他人隐私。 | frontend/src/QzonePage.jsx:100:65 |
| T578 | 待审阅 | 随机分享与 Owner | 说明文字 | 下次随机评估约 〔showTime(snapshot.random.next_check)〕，不保证发布。 / 〔snapshot.random?.last_reason〕 〔snapshot.random.last_reason〕 | frontend/src/QzonePage.jsx:101:20 |
| T579 | 待审阅 | 随机分享与 Owner | 行内说明候选 | 空间策略有未保存的修改 | frontend/src/QzonePage.jsx:101:349 |
| T580 | 待审阅 | 动态记录 · 〔posts.total〕 条 | 悬浮提示 | 动态记录 · 〔posts.total〕 条 | frontend/src/QzonePage.jsx:104:69 |
| T581 | 待审阅 | 动态记录 · 〔posts.total〕 条 | 副标题 | 草稿、定时及发布结果保存在本机；结果未知时请先去 QQ 空间核对。 | frontend/src/QzonePage.jsx:104:106 |
| T582 | 待审阅 | 动态记录 · 〔posts.total〕 条 | 空状态 | 还没有动态记录，先写一条草稿。 | frontend/src/QzonePage.jsx:105:28 |
| T583 | 待审阅 | 动态记录 · 〔posts.total〕 条 | 补充文案候选 | 动态配图 〔i+1〕 | frontend/src/QzonePage.jsx:105:548 |
| T584 | 待审阅 | 动态记录 · 〔posts.total〕 条 | 说明文字 | 定时：〔showTime(p.scheduled_at)〕 | frontend/src/QzonePage.jsx:105:606 |
| T585 | 待审阅 | 动态记录 · 〔posts.total〕 条 | 说明文字 | 说说 ID：〔p.tid〕 | frontend/src/QzonePage.jsx:105:748 |
| T586 | 待审阅 | 发布到 QQ 空间？ / 删除这条 QQ 空间说说？ / 取消这条草稿或定时任务？ | 补充文案候选 | 发布到 QQ 空间？ | frontend/src/QzonePage.jsx:108:242 |
| T587 | 待审阅 | 发布到 QQ 空间？ / 删除这条 QQ 空间说说？ / 取消这条草稿或定时任务？ | 补充文案候选 | 删除这条 QQ 空间说说？ | frontend/src/QzonePage.jsx:108:285 |
| T588 | 待审阅 | 发布到 QQ 空间？ / 删除这条 QQ 空间说说？ / 取消这条草稿或定时任务？ | 补充文案候选 | 取消这条草稿或定时任务？ | frontend/src/QzonePage.jsx:108:301 |
| T589 | 待审阅 | 发布到 QQ 空间？ / 删除这条 QQ 空间说说？ / 取消这条草稿或定时任务？ | 弹窗说明 | 将立即发布到当前账号，可见范围为「〔audiences[confirm.post.visibility]〕」，共 〔confirm.post.images.length〕 张配图。 / 会调用 NapCat 删除该账号已发布的这条说说。 / 内容会保留为已取消记录，不再自动发送。 | frontend/src/QzonePage.jsx:108:331 |

## 每日日程 / 修改记录

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T590 | 待审阅 | 对话引起的修改 | 副标题 | 自动同步已确认的聊天约定，保留修改前后与触发对话。 | frontend/src/ScheduleChanges.jsx:38:69 |
| T591 | 待审阅 | 对话引起的修改 | 空状态 | 今天还没有因对话修改日程。例如：聊到“今晚留下陪我”，角色答应后会自动调整安排，无需报出具体时间。 | frontend/src/ScheduleChanges.jsx:39:24 |
| T592 | 待审阅 | 对话引起的修改 | 说明文字 | 确认依据：〔change.diff.evidence〕 | frontend/src/ScheduleChanges.jsx:43:32 |

## 每日日程

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T593 | 待审阅 | SchedulePage.jsx | 操作反馈与确认 | 当日日程已重置，新安排已生效 | frontend/src/SchedulePage.jsx:50:22 |
| T594 | 待审阅 | 角色的日常生活 | 副标题 | 生活设定作为生成模板；每位用户拥有独立日程、穿着、事件与约定。 | frontend/src/SchedulePage.jsx:63:90 |
| T595 | 待审阅 | 角色的日常生活 | 说明文字 | 让活动、穿着和已经发生的事件参与聊天；对话中确认的改约会实时同步到日程，无需报出具体时刻。 | frontend/src/SchedulePage.jsx:64:59 |
| T596 | 待审阅 | 角色的日常生活 → 生活设定 | 字段说明 | 填写身份、工作日与周末安排、作息和穿衣偏好。人格沿用「身份与私聊」，模型沿用当前 Bot 的选择。 | frontend/src/SchedulePage.jsx:66:61 |
| T597 | 待审阅 | 角色的日常生活 → 生活设定 | 输入框占位 | 例如：经管系大一学生，周一到周五在学校上课，住校；周末回家。喜欢早起，晚上去图书馆，穿衣偏休闲。 | frontend/src/SchedulePage.jsx:67:154 |
| T598 | 待审阅 | 角色的日常生活 → 日程时区 | 字段说明 | 按此时区每天 00:00 更新；默认北京时间，与主动消息时区分别配置。 | frontend/src/SchedulePage.jsx:69:62 |
| T599 | 待审阅 | 角色的日常生活 → 日程时区 | 输入框占位 | Asia/Shanghai | frontend/src/SchedulePage.jsx:70:154 |
| T600 | 待审阅 | 角色的日常生活 | 说明文字 | 生成模型：请先选择模型 | frontend/src/SchedulePage.jsx:74:7 |
| T601 | 待审阅 | 角色的日常生活 | 行内说明候选 | 在 QQ 查看今天的完整安排 | frontend/src/SchedulePage.jsx:75:65 |
| T602 | 待审阅 | 角色的日常生活 | 行内说明候选 | 重新生成今天的日程并立即生效 | frontend/src/SchedulePage.jsx:75:121 |
| T603 | 待审阅 | SchedulePage.jsx | 提示框 | 请先保存生活设定，再生成或重置日程。已有日程按保存的配置运行。 | frontend/src/SchedulePage.jsx:77:25 |
| T604 | 待审阅 | SchedulePage.jsx | 提示框 | 〔snapshot.error〕。已有日程会保留，可检查模型后重试。 | frontend/src/SchedulePage.jsx:78:36 |
| T605 | 待审阅 | 今日日程 | 副标题 | 〔snapshot.date〕 · 〔snapshot.timezone〕 · 当前 〔minute〕 / 正在读取当天安排… | frontend/src/SchedulePage.jsx:79:73 |
| T606 | 待审阅 | 今日日程 | 补充文案候选 | 正在生成… | frontend/src/SchedulePage.jsx:83:20 |
| T607 | 待审阅 | 今日日程 | 补充文案候选 | 正在同步对话中确认的安排… | frontend/src/SchedulePage.jsx:86:133 |
| T608 | 待审阅 | 今日日程 | 补充文案候选 | 正在调用模型生成完整日程，慢速模型可能需要几分钟。 | frontend/src/SchedulePage.jsx:86:151 |
| T609 | 待审阅 | 今日日程 | 空状态 | 今天的故事，还没有展开请先选择用户，或通过 QQ 与机器人互动建立用户范围。 / 填写生活设定，开启并保存每日日程后，即可生成今天的安排。 / 点击「生成当日日程」，或等待后台自动生成。 | frontend/src/SchedulePage.jsx:87:16 |
| T610 | 待审阅 | 今日日程 | 提示框 | 每日日程已关闭。下方保留的安排不会参与聊天或自动更新。 | frontend/src/SchedulePage.jsx:88:31 |
| T611 | 待审阅 | 今日日程 | 说明文字 | 生成于 〔at(plan.generated_at)〕 · 最近调整 〔at(plan.updated_at)〕 | frontend/src/SchedulePage.jsx:89:75 |
| T612 | 待审阅 | 今日日程 | 提示框 | 已确认的跨日安排 · 〔snapshot.continuity.target_date〕〔snapshot.continuity.reason〕〔snapshot.continuity.activities.map(item => `${item.start}–${item.end} ${item.activity} · ${item.location}`).join('；')〕分钟时间由系统推定，实际进展会随对话调整。 / 按对话中确认的时间衔接。 | frontend/src/SchedulePage.jsx:90:33 |
| T613 | 待审阅 | 今日日程 | 说明文字 | 穿着：〔item.outfit〕 | frontend/src/SchedulePage.jsx:100:301 |
| T614 | 待审阅 | 今日日程 | 说明文字 | 下次更新：〔new Date(snapshot.next_refresh * 1000).toLocaleString('zh-CN', { timeZone: snapshot.timezone, hour12: false })〕（〔snapshot.timezone〕）。平台运行期间自动更新，重启后补齐当天日程。随机事件仅在发生后进入聊天上下文。 | frontend/src/SchedulePage.jsx:106:29 |
| T615 | 待审阅 | SchedulePage.jsx | 提示框 | 以下约定时间有冲突，请在记忆页面核对：〔plan.commitment_conflicts.map(item => item.content).join('；')〕 | frontend/src/SchedulePage.jsx:108:46 |
| T616 | 待审阅 | 重置当日日程 | 弹窗说明 | 重新生成今天的全部安排、穿着和随机事件。成功后立即替换，生成失败会保留原日程；聊天记录不受影响。 | frontend/src/SchedulePage.jsx:110:202 |

## 记忆与日程 / 用户范围

| 编号 | 状态 | 位置 | 类型 | 原文 | 源码 |
|---|---|---|---|---|---|
| T617 | 待审阅 | UserScopeSelector.jsx | 补充文案候选 | 暂无用户，请先通过 QQ 与机器人互动 | frontend/src/UserScopeSelector.jsx:30:269 |
| T618 | 待审阅 | UserScopeSelector.jsx | 辅助文字 | 按 Bot 与用户隔离 | frontend/src/UserScopeSelector.jsx:30:515 |
