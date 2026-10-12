# Android Native MCP — N3 稳定化分步实施计划

**日期：** 2026-10-12（Australia/Sydney）
**用途：** 独立 Native 开发会话执行、恢复和逐步验收；不是“已完成”声明
**审查依据：** `/Users/grammy-jiang/Projects/android-mcp-native-review-20261012.md`
**Native 工作目录：** `/Users/grammy-jiang/Projects/android-mcp-native-setup`
**仓库：** <https://github.com/grammy-jiang/android-mcp>
**N3 Draft PR：** <https://github.com/grammy-jiang/android-mcp/pull/16>
**编制时 N3 已推送 HEAD：** `364520425f5f38b4ab4169977e5663638a69f196`
**编制时 `origin/main`：** `0a1e0a418dab134d5081c5d7308843379f69fb8a`

> 这些 SHA 仅是 2026-10-12 的基线快照。每次开始开发或合并前必须刷新 Git / PR / CI。真实 OnePlus Pad 3 只允许之前明确批准的只读 Host 测试；本计划任何步骤都不授权向它安装 APK、Root、重启、修改系统、执行 UI 控制或刷机。

## A. 项目目标与不变量

目标：将 Native N3 的用户主动启动型 Android 前台 MCP 服务从已验证的开发原型推进到**可预测、可安全停止、可恢复且跨 API 版本明确受支持**的本地只读服务，再决定能否合并 PR #16。

所有工作包共同遵守：

1. N2 Activity-only 模式保留：用户手动启动；离开 Activity 后停止监听；回到前台后允许再次启动。
2. N3 Foreground Service 模式保留：用户在可见 UI 上手动启动；退到 Home 后继续监听；有持续可见通知和明确 Stop；`START_NOT_STICKY`，不随设备启动或崩溃自行恢复。
3. 两种模式不可同时拥有 `127.0.0.1:38765`；任何时刻只有一个进程内 owner。未知停机状态必须拒绝抢占。
4. `device_status` 是唯一工具；返回已版本化 JSON Schema v1、非敏感的合成只读状态。禁止引入任意 Shell、ADB 控制、Accessibility、Root 或敏感用户数据。
5. 不公开 `0.0.0.0` / LAN listener；没有 Host↔Native 认证、联合 Lease、正式 ChatGPT Cloud/Work 通道之前，**不得扩展敏感或有副作用能力**。
6. 每个微步骤都必须让现有可用路径保持可用，且失败时能够回滚/拒绝，不得以删除测试、跳过 CI 换取“通过”。
7. Host 与 Native 是两个独立工作流；不得修改 Host 专属文件/工作树。Native 内多 Agent 也必须独立 worktree 和独占写入文件。

## B. 当前基线和未提交工作（执行 N3-00 前重新核对）

- N1/N2 已合并到 `main`；API36 ARM64 Mac 模拟器与 Linux x86_64 CI 均曾对 N2 执行真实 MCP HTTP/Activity 生命周期验收。
- N3 PR #16 在已推送提交 `3645204` 上有 5 项全绿检查（Linux 模拟器、APK/Lint、macOS/Linux JVM MCP、仓库卫生），但是**不能证明**本地未提交补丁已获得 PR 验收。
- Native 工作区在编制时还有两份未提交修改：
  - `android/app/src/main/java/org/androidmcp/nativeapp/LocalMcpGateway.kt`：进程内 AtomicReference owner，含 stop 无条件释放问题。
  - `docs/native-foreground-n3.md`：记录并发模式保护和本地验证；没有提交。

- 之前的独立审查问题：N3-01 START/STOP 竞态（P1）；N3-02 gateway 关闭失败所有权（P1）；N3-03 API30–33 兼容证据（P1/P2）；N3-04 停止 oracle 和通知 Stop（P2）；N3-05 认证边界（P2）；N3-06 Gradle/CI（P2）；N3-07 通知权限文档说明（advisory）。

冻结检查（只读）：

```bash
cd /Users/grammy-jiang/Projects/android-mcp-native-setup
git status --short --branch
git rev-parse HEAD
git worktree list
git diff -- android/app/src/main/java/org/androidmcp/nativeapp/LocalMcpGateway.kt docs/native-foreground-n3.md
gh pr view 16 -R grammy-jiang/android-mcp --json state,headRefOid,baseRefOid,isDraft,mergeStateStatus
```

**严禁**对其他开发会话拥有的分支做强制 push、`reset --hard`、`clean -fd`、静默 stash 或覆盖 dirty 文件。若需要多个本地子任务并行，先创建独立 worktree 与短期分支，明确唯一集成人。

## C. 建议 Android 版本策略（必须明确后才实现）

**首选：整个 APK 保留现有 `minSdk=30`，但 N3 Foreground Service 初期只面向 API34+；API30–33 保留可用的 N2 Activity-only 模式。**

- Android API30/33：N3 控件禁用/不可进入，并显示“该服务模式需要 Android 14+”；N2 模式继续通过真实测试。
- Android API34/36：N3 需通过 start/stop、Home、通知授权、竞态、端口所有权、通知 Stop 动作等验收。
- 如果未来确实要让 N3 后台服务覆盖 API30–33，另开短期兼容工作包，不要在修复竞态时隐式承诺旧版兼容。
- 官方 `FOREGROUND_SERVICE_TYPE_SPECIAL_USE` 类型始于 API34。Android 13+ 的 `POST_NOTIFICATIONS` **不是启动前台服务的系统硬前置条件**；当前项目选择“没有通知可见性则拒绝 N3 启动”是主动设定的产品安全策略，应写明。

参考：<https://developer.android.com/reference/android/content/pm/ServiceInfo> 及 <https://developer.android.com/develop/ui/compose/notifications/notification-permission>

## D. 原子工作包与逐步验收

### N3-00：冻结基线和保护测试（第一步，必做）

**依赖：** 无。
**只读输入：** N3 PR #16、Native 工作树、独立审查报告、N2 与 N3 文档。
**行动：**

- 核对 live HEAD/base/main、dirty 文件、PR checks、已经启动的工作，必要时保存当前 dirty patch 的副本与哈希。
- 保留原样，不直接提交原有存在问题的 owner 补丁，也不覆盖它。
- 记录 N2/N3 应保持的 MCP tool/Schema/权限/地址/生命周期行为。
- 建立受保护回归表，区分历史 CI 通过与当前未执行的检查。

**检查：** `bash scripts/check-native.sh`；已配置 SDK 时 `bash scripts/check-native-apk.sh`；模拟器仅用显式 `emulator-5554`，必须核验 `ro.kernel.qemu=1` 后才可运行 `bash scripts/check-native-emulator.sh`。
**输出：** 基线 SHA/命令/结果及变更保护表。
**通过标准：** 现有功能仍可重复通过，未提交补丁原样保存。
**回滚：** 无源码修改。

### N3-01：定义最小服务生命周期状态机（核心设计门禁）

**依赖：** N3-00。
**对应发现：** N3-01、N3-02。
**独占文件：** `NativeMcpForegroundService.kt`、新建的 Native-only 状态模型/单元测试（如需要）。
**行动：**

- 定义 STOPPED → STARTING → RUNNING → STOPPING → STOPPED；未能确认启动/停止时进入 FAILED_CLOSED/UNKNOWN。
- 规定 START while RUNNING、STOP while STOPPED、START while STOPPING、STOP while STARTING、重复通知动作、onDestroy 与进程死亡的确切语义。
- 选择唯一的有序控制通道（主线程接收 intent，单个 worker/actor 负责资源变更），generation/operation token 避免旧任务影响新一轮启动。
- 验证 Android `stopSelfResult(startId)` 与 stop 操作完成顺序；旧 stop 不能无条件 `stopSelf()` 终止新 start。
- UI 中 “Start requested” 与 “Running” 必须区分，以实际 readiness 为准，不可仅因提交异步任务就显示成功。

**优先测试：** 状态转换单测、重复命令与相反命令交错、不会出现 RUNNING 无通知或 UNKNOWN 被当 STOPPED。
**完成标准：** 状态/线程归属清楚；失败路径有可验证结果；尚不需要改变 wire contract。
**回滚：** 独立小提交，可退回现有原型。

### N3-02：修复 Foreground Service START/STOP/onDestroy 竞态

**依赖：** N3-01 已确定状态模型。
**对应发现：** N3-01。
**独占文件：** `NativeMcpForegroundService.kt` 和受控 lifecycle helper。
**行动：**

- 用上一阶段状态机取代 `AtomicBoolean started` 充当唯一运行事实的假设。
- 所有 gateway start/stop 在已定义队列中有序执行；Stop 结束并确认 listener 关闭后，才能标记已停止和移除前台通知。
- 处理 `onDestroy`、重复 STOP、通知 Stop、Activity Stop 和快速 Start→Stop→Start；不允许旧 stop 杀死新 start。
- 收到无法恢复的异常时 fail closed，提供适量结构化错误供 UI 显示；不把内部日志/用户数据写进公开 MCP 工具响应。
- 不引入自动重启、boot receiver 或背景隐藏连接。

**快速门禁：** 相关 Kotlin 单元测试/模拟调度器、APK compile/Lint；涉及行为改动必须用本地 AVD 验证。
**完成标准：** 对每种交错具有确定结果；服务不存在/仍运行与 UI、监听端口的事实一致。
**回滚：** 独立提交撤销本阶段，保持 N2 旧模式正常。

### N3-03：修复 LocalMcpGateway 单一 owner / 失败关闭语义

**依赖：** N3-01，实际接入建议在 N3-02 之后。
**对应发现：** N3-02。
**独占文件：** `LocalMcpGateway.kt` 及其 Kotlin 测试 seam。这个文件与 N3-02 **不能交给两个 Agent 同时改**。
**行动：**

- 整理现有 dirty atomic owner 补丁；明确其只是进程内端口保护，绝非 Host/Native 认证或分布式 Lease。
- 启动过程分别追踪 owner acquisition、Ktor listener readiness、实际 MCP HTTP 可用；`embedded.start(wait=false)` 不能直接等同于已 ready。
- stop 成功且真实 listener 已经关闭以后，才允许释放 owner；如果 stop 抛异常、超时或 socket 状态不确定，保持 UNKNOWN/拒绝第二个启动。
- 重复 stop、start 失败、端口被其他服务占用、模式争用须各有 fail-closed 结果与可恢复路径；禁止静默“强制释放锁”。
- 保持只读工具/127.0.0.1/非导出 Service 不变。

**优先测试：** 注入端口冲突、start 异步失败、stop 异常/超时、双模式并发竞争；本地 AVD 必须证明 loser 显示失败、winner 的 MCP/通知仍正常。
**完成标准：** 不会出现 listener 还活着却 owner 已释放，也不会把绑定失败宣称 RUNNING。
**回滚：** 回退该小提交，不修改 Host 组件。

### N3-04：加强“已经真正停止”的证据、通知 Stop Action

**依赖：** N3-02/03 完成最终接入；测试用例骨架可以提前写。
**对应发现：** N3-04。
**文件：** `scripts/smoke-native-emulator.py`、`scripts/smoke-native-foreground-emulator.py`、`android/tests/**`。
**行动：**

- 停止判据必须交叉确认：MCP 不能响应、Android 侧 ServiceRecord 实际消失、端口/监听未被占用、前台通知已撤下。
- 单纯 HTTP 超时/ADB forward 中断不能认定 stop PASS；对挂住但尚未关闭的 listener、ADB 断线、重复通知、缓存残留加负向测试。
- 在模拟器通知栏中**真正触发 Stop 按钮对应的 PendingIntent**，验证它走到安全关闭路径；不可只检查 Kotlin 源码里有 action 字段。
- 验证用户在 Activity UI Stop、通知 Stop、`force-stop` 三条路径的不同语义；确认 `START_NOT_STICKY` 适用。
- 压力测试至少覆盖快速 START/STOP/START、切模式、应用旋转/进入 Home、端口冲突，并保留 seed 或重复步骤。模拟器日志输出须有界且脱敏。

**完成标准：** 强 stop oracle 的正反测试通过，通知 Stop 真点击通过；不留下 ADB forward 及服务/通知残留。
**回滚：** 独立的测试与脚本提交。

### N3-05：API 支持版本矩阵、权限与特殊前台服务策略

**依赖：** N3-00 确认默认策略与 N3-01 契约。可与测试工具工作并行准备。
**对应发现：** N3-03、N3-07。
**文件：** `BackgroundMcpActivity.kt`、Native-only 版本 helper、必要时 `android/app/build.gradle.kts`、文档/版本测试。
**行动：**

- 推荐维持 app `minSdk=30`，只对 API34+ 启用 N3；低版本保留 N2，显示不支持，不执行 N3 Service。
- API30、33 模拟器验证 N2 正常且 N3 被明确拒绝；API34、36 验证 N3 完整 start/stop/通知/后台行为。
- 核对 Manifest `specialUse` subtype 的合法性和最小权限；对将来 Google Play 分发另设审核门槛，不能把本地开发授权等同于 Play 批准。
- 记录 Android 13+ 通知权限是项目自选可见性门禁，不是系统不授予便必然无法启动前台服务。

**完成标准：** 支持矩阵与代码和 CI 对齐，最低版本没有隐性失效路径。
**回滚：** 单独版本/可用性提交，N2 不回归。

### N3-06：Gradle 依赖治理、慢速 CI 成本和发布质量

**依赖：** N3-02/03 的架构边界明确；只读依赖分析可提前并行。
**对应发现：** N3-06。
**文件：** `android/**` Gradle 元数据、Native 专属 `.github/workflows/native-*`、`scripts/check-native*.sh`。
**行动：**

- 保留目前 Gradle Wrapper distribution SHA、AGP/Kotlin/MCP SDK/Ktor 明确版本；审查传递依赖，并评估 Gradle dependency locking 与 verification metadata。
- 不借整改机会做无审查的依赖大升级，也不改 `host/**` 或 Host CI。
- 快速本地/PR 检查：Kotlin unit、Ruff、pytest、manifest、lint、配置/安全检查。
- Linux Android 16 与 Android 14 真实模拟器 E2E 为 N3 的关键 PR 合并验收；API30/33 的 N2 保持兼容测试要有 exact-SHA 证据，可合理分配至目标 CI/定期慢速 CI。
- GitHub Actions 保留 SHA 固定、最小 token 权限、明确超时；并显示每个任务的 executed/passed/skipped/blocked，而非只用单一“绿色”标签。

**完成标准：** 不降级现有质量；必要 CI 触发准确；依赖与测试结果可复现，成本可控。
**回滚：** CI/依赖改动单独提交，不能和复杂并发代码混在一个不可分辨的大提交里。

### N3-07：完整稳定化验收与插件二次复审

**依赖：** N3-02..N3-06 的关键改动全部合流；无待发布 dirty 功能代码。
**按资源成本执行：**

1. `uv run --project host --locked --group dev ruff check scripts/smoke-native-emulator.py scripts/smoke-native-foreground-emulator.py android/tests`
2. `uv run --project host --locked --group dev pytest -q android/tests`
3. `bash scripts/check-native.sh`（Kotlin 协议/JVM HTTP/SDK-free guard）
4. `uv run --project host --locked --group dev pre-commit run --all-files`
5. `bash scripts/check-native-apk.sh`（licensed Android SDK、API36、JDK17，build/Lint/signature/准确权限）
6. `bash scripts/check-native-emulator.sh`（仅在 `emulator-5554` 且 `ro.kernel.qemu=1` 之后）
7. API30/33/34/36 独立仿真验收与至少一种并发/失败注入压力测试。
8. GitHub PR #16 **确切新 HEAD** 的 Android emulator、Native macOS/Linux、repository/security，以及必要 Host 回归 CI。
9. 使用 `chatgpt-mcp-engineering` Verification/review 按最新改动重审 N3-01..N3-07，记录 severity、证据、修正、验收。

**完成标准：** P1 发现全部关闭；必要的 P2 合并门禁覆盖；没有跳过/未运行却声称通过的检查；新 PR 提交在所有要求平台上有真实通过记录。
**失败处理：** 继续 Draft，针对一个缺陷做一轮最小补丁，重验后再前进，不一次性重写。

### N3-08：准备合并、验证整合和回滚

**依赖：** N3-07 全部通过及 PR #16 二次审查。
**行动：**

- 先重新 fetch `origin/main` 与 Host 工作流最近已合并成果，确认当前 Native branch/worktree 无未知 dirty 更改和并发写入。
- 将 N3 修复按小提交合入 Draft PR #16；每一波完成后核对 exact-head CI，尽量不要把分支长期与主干分离。
- 确认审查关闭所有 blocker，PR 不再是 Draft，然后进行有检查条件的 merge；禁止 force push `main`。
- Merge 后针对真正的 `main` SHA 重新验证 Native/Kotlin/Android CI，记录结果、已知剩余限制与版本矩阵。
- 若合并后出现回归，以独立 revert PR/提交恢复 N2 已验证基线，不以覆盖工作树“解决”。

**完成标准：** `main` 正确合并并通过合并后检查；交接文档记录 HEAD/merge SHA、结果和下一步。
**下一阶段：** 再单独规划 caller 认证、Host↔Native pairing、MCP conformance、ChatGPT Chat/Work 目标连接、敏感读操作/Accessibility 以及真机 APK 测试。不要混入 N3。

## E. 合理并行：文件所有权与合流顺序

| 工作轨道 | 可并行做什么 | 独占文件 | 合流依赖 |
| --- | --- | --- | --- |
| A: Kotlin 生命周期 | N3-01 → N3-02 → N3-03 **顺序** | `NativeMcpForegroundService.kt`、`LocalMcpGateway.kt`、状态模型/单元测试 | 与其他轨道合并后才能开始最终 Android E2E |
| B: 测试 harness | N3-04 的独立 Python fixtures、stop/通知否定案例可以提前做 | `scripts/smoke-native-*.py`、`android/tests/**` | A 的最新状态合同稳定后修正 oracle |
| C: API 版本策略 | API30/33/34/36 的兼容研究和独立脚本可并行 | 版本文档、Native API-gate helper，必要时 `BackgroundMcpActivity.kt` | 兼容代码在独占文件 owner 审查后合流 |
| D: 构建/CI | 依赖治理与 Native-only Workflow 策划可并行 | Gradle/`native-*` CI；独占 CI 集成人 | 最终 tests 真实运行必须使用合并后的 exact SHA |
| H: Host Session | 继续独立维护/增强 Host | `host/**` 与 Host 专属 worktree | N3-08 定期同步 `main` |

同一 Git Worktree 任意时刻**只能有一个写入者**。需要子 Agent 并行时建立独立短命分支和 worktree，而不是共享当前有 dirty 文件的 `android-mcp-native-setup`。

## F. 交付门禁、反馈成本及交接格式

每个小变更：先做受影响单元测试，不必每次跑完整 6 分钟的 Android CI；生命周期/Manifest/真实 wire 行为改变时，至少本地 Android 模拟器验收；集成前一定跑完整 N3-07。API36 既有 GitHub emulator 曾约需 5–7 分钟，这是历史记录而不是运行承诺。

每次改动的交接输出：

```text
Stream: Native
Work package: N3-XX
Branch / HEAD: <branch> / <full SHA>
Base main: <full SHA>
Owned files and changes: ...
Cross-stream shared contracts changed: none | RFC/PR
Dirty inputs preserved: ...
Test evidence: <command, environment/API/ABI, execution, actual result>
Security boundary: loopback only, read-only, no physical tablet
PR/checks: <URL, exact HEAD and state>
Known failures / unknowns: ...
Next smallest eligible step: ...
```

**永不以绿色 CI 的存在声称尚未执行的工作成功。** N3 的 MCP conformance/ChatGPT surface、真正设备安装、跨进程 Host/Native 认证、Play 分发许可属于后续独立门禁。

## G. 第一轮马上执行的顺序

1. N3-00 保护和冻结两份 dirty 代码，并建立现有稳定基线。
2. N3-01 设计/测试状态机（优先纯 JVM deterministic tests）。
3. N3-02 Service start/stop/onDestroy 有序处理，保留原有 MCP 只读接口。
4. N3-03 Gateway owner 的确认释放和失败关闭，双模式争用测试。
5. N3-04 通知 Stop 实际验收、强关闭 oracle、负向网络/端口测试。
6. N3-05 版本门禁 API30/33 vs 34/36；不让低版本隐性异常。
7. N3-06 依赖/CI/版本矩阵，按需安排与前两项不冲突的并行任务。
8. N3-07 全量 exact-head 复验 + 插件审查复核。
9. N3-08 PR #16 经审核合并回 `main`，验证合并后的主干。

## H. 参考

- 本地审查：`/Users/grammy-jiang/Projects/android-mcp-native-review-20261012.md`
- N3 文档：`docs/native-foreground-n3.md`
- N2 模拟器：`docs/native-emulator-n2.md`
- 双工作流规范：`/Users/grammy-jiang/Projects/android-mcp-workflow-docs/docs/parallel-workstreams.md`
- Android Service startId/stopSelfResult：<https://developer.android.com/reference/android/app/Service#stopSelfResult(int)>
- Android specialUse：<https://developer.android.com/develop/background-work/services/fgs/service-types>
- Android ServiceInfo：<https://developer.android.com/reference/android/content/pm/ServiceInfo>
- 通知权限：<https://developer.android.com/develop/ui/compose/notifications/notification-permission>
- MCP 规格：<https://modelcontextprotocol.io/specification/>

**状态提醒：** 本文是计划，不表示 N3-00..08 的实施已经完成，不表示 N3 已合并，也不表示真实设备或者正式 ChatGPT MCP 连接得到验证。
