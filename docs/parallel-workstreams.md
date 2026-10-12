# Android MCP — 双工作流、双 Chat Session 并行开发与交接规范

> 版本：v2，2026-10-12（Australia/Sydney）。本文件是协作约定，不代表两段 Chat 能自动共享记忆或在没有活动执行环境时持续运行。仓库：`grammy-jiang/android-mcp`；默认集成分支：`main`。

## 1. 核心决策

- **一个 Monorepo、两个独立工作流（Host / Native）、每个会话一个独立 Git Worktree、短期特性分支、统一向 `main` 集成。** 不设长期漂移的 `develop-host` / `develop-native` 分支。
- 通过 Git commit、Pull Request、CI 及本文件交换事实和工作状态；不要依赖另一个 Chat Session 的历史消息或未提交文件。
- 每次开始操作之前检查真实的 Git 状态、PR、CI、工作区和设备状态；本文记录的提交和测试数字只是创建时快照，不能当作实时状态。
- 默认先保持所有设备操作**只读**，未经明确授权与独立安全门禁不得开启 Root、任意 ADB shell、APK 安装、持久权限变更、设备重启或公网未认证监听。

## 2. 两个 Chat Session 的默认分工（可以显式调整）

| 会话 / 工作流 | 主要职责 | 专属工作区（macOS） | 允许主要修改的范围 | 当前入口 |
| --- | --- | --- | --- | --- |
| **Session A：Native** | Kotlin 契约、MCP Native 服务、APK/Android 生命周期、权限隔离、跨语言互操作 | `~/Projects/android-mcp-native-setup` | `android/**`、`docs/native-*.md`、`scripts/check-native.sh`、`scripts/smoke-native-jvm.py`、Native 专用 CI | Native N0 [PR #6](https://github.com/grammy-jiang/android-mcp/pull/6) 与 N1 [PR #9](https://github.com/grammy-jiang/android-mcp/pull/9) 已合并；后续以 GitHub 实时 PR 为准 |
| **Session B：Host** | Python Host MCP 的稳定性、安全加固、ADB 只读能力、开发基础设施、跨平台自动化质量 | 已采用专属 Host Worktree；后续新建短期分支或专属 Worktree，禁止共享写入 | `host/**`、`docs/host-*.md`、Host 专用脚本与 Host CI | 从最新 `origin/main` 创建 `feature/host-<topic>` 分支 |

工作流是职责边界而非永久锁定。若用户决定交换 A/B 角色，先在对应 PR 描述中声明新的拥有者，并核实没有另一会话正在写入相同目录或分支。**同一 Git branch / worktree 在任一时刻只能由一个会话拥有写权限。**

MacBook 上原有的 `~/Projects/android-mcp` 工作区当前仍位于已合并的 Host feature 分支；它不是给 Session B 直接复用的共享编辑目录。`sextant`（Raspberry Pi）是目前 USB 真机的临时接入与只读测试节点，不是开发主机。

## 3. 必须先核对的项目快照（2026-10-12；之后以 GitHub 为准）

- 默认分支：`main`；截至本次更新，Host PR #3、#4、#5、#8、#10、#11、#13 与 Native N0/N1 PR #6、#9 已合并。本轮文档基线 SHA 为 `310834b515799e5023902ad97aec4d592f77db31`；后续务必重新核实 GitHub 的实际 HEAD。
- Host 的只读里程碑：三个工具 `device_status`、`adb_observe`、`adb_develop`；安全加固版在 `sextant` Linux ARM64 上 301 个测试通过、约 99% 综合覆盖率，HTTP → USB ADB → OnePlus Pad 3 真机八组只读探测已复验。关键模块独立执行至少 95% 的语句与真实分支覆盖率门禁。**APK 安装、instrumentation 等设备变更仍默认禁用**。
- Native N0 JVM Kotlin 原型与 N1 **前台 localhost Android APK 框架**已合入主干。N1 需要显式启动 Activity，停止 Activity 即停止监听；不包含 Accessibility、Root 或外部认证。Native 的真实平板 APK 安装、运行及 Host/Native 联合控制权限仍**未验收**；N2 进度以 GitHub 的实际 PR 为准。
- MacBook 已安装 Android SDK 部分组件（本次检查约 3.5 GB）；Homebrew JDK 17 已存在，但默认 Java PATH 可能仍需显式设置。SDK/JDK 存在不代表 Native APK 真机验收完成；必须提供构建产物、CI 与设备证据。
- OnePlus Pad 3 目前经 `sextant` USB ADB 连接；MacBook USB 直连受 macOS 配件授权限制。不可把这个连接事实推断为 MacBook 上的设备可用。

## 4. 分支生命周期：短命、经常同步，避免历史分叉

1. 每个细分任务均从**最新 `origin/main`** 创建独立 `feature/host-*` 或 `feature/native-*` 分支；不要把历史 feature branch 当作新的集成主干。
2. 每项 PR 尽量控制为一个审查单元；建议活跃工作流每天检查一次 `origin/main`，以及每次有人合并 PR 后再次核对。一个 PR 若超过约两个工作日仍未合并，应优先缩小范围、拆 PR 或同步主干，而不是一直叠加新功能。
3. **同步前**先检查 `git status --porcelain`, `git worktree list`, 本地分支与远端分支 owner，以及 PR 的 head/base；存在未提交修改、未完成任务或归属不明时不要 rebase / merge / cherry-pick。
4. 对**独占且尚未共享/推送**的短期分支，可以先 `git fetch origin main`，再 `git rebase origin/main`；这会重写提交 ID，必须只针对自己拥有的分支。
5. 对**已推送且其他会话可能在使用**的分支，优先考虑把 `origin/main` merge 进该特性分支，或者为后续工作新开一个分支。确需 rebase 已推送分支时，必须确认独占归属及 PR 状态；绝不无条件 `git push --force`。确需推送改写历史只可在核对远端 HEAD 后审慎使用 `--force-with-lease`。
6. 每个 PR 经对应质量门禁、必要的独立安全审查后合入 `main`；合并后其他工作流同步 `main` 再继续。**不要求每天强制合并未通过测试的代码**。
7. 禁止自动 `reset --hard`、`clean -fd`、stash/覆盖其他会话的改动；禁止两个会话互相 rebasing 对方分支。发生冲突时停在可恢复状态，记录冲突并由分支拥有者处理。

## 5. 独立 Worktree 操作范式

Session B 在新的 MacBook 会话中先读 `AGENTS.md`、`docs/development.md`、本文件及 Host 相关安全/质量文档，再**检查并选择尚不存在的新路径/分支名**。以下仅为操作示例，不应在未检查状态时盲目复制执行：

```bash
cd ~/Projects/android-mcp
git worktree list
git status --short --branch
git fetch origin main
# 确认路径和分支均不存在、没有其他会话占用后：
git worktree add -b feature/host-<topic> ~/Projects/android-mcp-host-<topic> origin/main
cd ~/Projects/android-mcp-host-<topic>
python3 scripts/dev.py bootstrap
python3 scripts/dev.py doctor --require-hooks
bash scripts/check-host.sh
```

Session A 保留 Native 专属 Worktree 与当前 Native PR，不允许 Session B 切换、重置、重写该工作区。一个分支合并后，只有在确认没有未提交修改/未运行任务时才清理属于自己的 Worktree；不要直接删除共享的 Git 元数据。

## 6. 文件边界与跨工作流接口

- **Host 独占为主：** `host/**`、Host 专用测试、Host 的能力/安全说明、Host CI。
- **Native 独占为主：** `android/**`、Native 专用测试、Gradle/JDK、Native CI、Native 设计说明。
- **需要联合协调：** `contracts/**`、`docs/contracts.md`、`docs/host-native-coordination.md`、`docs/security.md`、`AGENTS.md`、通用 CI/质量规则、仓库根目录共享配置。
- 对共享接口的任何变更都先写 PR/Issue 说明协议版本、旧客户端兼容性、预期 API、迁移方案和测试样例；**一方不能私自改动共享 Schema 后假设另一方会适配**。
- 对破坏兼容性的协议变更，显式提升 Schema 版本；同时补全 Host Python 和 Native Kotlin fixture/反例测试。在 Native 代码尚未进入 `main` 之前，至少要在 Native 工作流中运行对应契约测试并说明验证范围。
- 避免两个会话同时更新一个 `docs/STATUS.md`：每个 PR 的描述/提交负责汇报状态；若需要持久交接文档，各工作流分别创建自己的 `docs/handoffs/host-*.md` 或 `docs/handoffs/native-*.md`。

## 7. 测试矩阵与真实设备协调

| Gate | Host 工作流 | Native 工作流 |
| --- | --- | --- |
| 本地验证 | Ruff、strict mypy、Bandit、per-module branch coverage、Host Pytest、doctor、包安装 | Gradle JDK 17 单测、共享契约、Python FastMCP ↔ Kotlin localhost HTTP smoke |
| GitHub CI | macOS/Linux × Python 3.11、3.12、3.13、3.14；按 Host 相关路径触发，所有 PR 执行仓库 Hygiene，另设每周依赖审计 | macOS/Linux Kotlin JVM CI；N1 具备 APK/AGP 构建规则，Emulator/Instrumentation 根据 Native 里程碑单独验收 |
| 真机 | 已授权 `sextant` 完成 localhost MCP ↔ USB ADB 的八组**只读**验收；后续继续显式授权 | N1 APK 框架已有，但真机安装/运行尚无验收证据；JVM 或 Emulator 通过不能代表真机成功 |

真机属于唯一共享的物理资源。两个会话只能**串行**安排同一平板的真实硬件测试；在 PR 描述中记录测试拥有者、范围、设备连接位置和结果。默认不采集、不保存、不公开设备诊断/日志/截图/序列号；不能运行未经用户明确授权的状态改变操作。

## 8. 统一的合并门禁与安全边界

- PR 范围明确、可回滚，附上具体测试命令与结果、风险/权限变更、兼容性说明；检查 GitHub 的实际 CI **在目标提交**通过后再合并。
- 涉及权限提升、设备修改、外部认证或 Host/Native 租约协调的 PR，必须有独立安全审查和负面用例；只读 JVM 原型或 Mock 测试不满足特权功能验收。
- Host 默认只监听 `127.0.0.1`，不将无认证 MCP HTTP 端口暴露到局域网/公网；Native 尚不应暴露高权限服务；Root、任意 Shell、系统设置变更、APK 安装/卸载均不在默认授权范围。
- 文档、质量修复可以提前单独 PR 合并；**不要因保持同步而绕过 CI 或把 Draft 功能强制合并**。

## 9. 新 Chat Session 的启动指令（Session B / Host，可直接复制）

> 请通过 MacBook Pro MCP 连接器访问私有仓库 `grammy-jiang/android-mcp`。首先读取 `docs/parallel-workstreams.md`、`AGENTS.md`、`docs/development.md`、`docs/security.md`、`docs/quality.md` 和 `docs/host-live-acceptance.md`，并核对最新 GitHub main、PR、CI、已有 worktree、正在运行的任务。你负责 **Host Workstream**，另一个 Chat Session 负责 Native 的 `~/Projects/android-mcp-native-setup` 与当时活跃的 Native PR，**不要修改它们**。从最新 `origin/main` 建立你自己独立且没有占用的 Worktree 与短期 `feature/host-*` 分支，先跑 Host 基线质量门禁，再选择一个小范围只读稳定性/安全性增强任务，编写测试、完成安全审查并开独立 PR。不能默认启用设备变更、Root 或公网监听，不能重写其他会话的分支；仅在满足合并门禁后合入 `main`。在 PR 描述中记录进度供另一个会话同步。

## 10. Session A / Native 的继续执行指令

保持 `~/Projects/android-mcp-native-setup` 为单写入者工作区；核对最新 Native PR、CI 与分支状态。N0 JVM、N1 前台 APK 框架已合并，后续按实际进度推进 Emulator、真机 APK 生命周期、权限隔离和安全门禁。真实设备只读测试与 Host 会话协调；任何需要修改 Host 或共享 Schema 的工作先提出单独协作 PR。不要覆盖 Host Worktree，不能把 Native JVM smoke 描述成 APK 验收。

## 11. 每次交接应留下的最小记录

每个工作流在其 PR 描述（或自己专属的 handoff 文件）说明：**当前 git branch / HEAD SHA / base SHA、修改的文件、测试及 CI 链接、是否进行真机只读测试、已知风险、阻碍项、下一个原子任务、是否有未提交的修改**。另一个会话以这些可核实记录作为输入，不从 Chat 消息推断对方的当前状态。

## 12. 并行 Chat 的运行现实

独立 Worktree + PR 使两个会话可同时推进不同任务，但**Git 不负责自动协调 Chat 执行，也不能保证对话结束后继续自动开发**。新消息可能中断当前一轮工具执行；继续时应查询命令、CI、Git 状态后恢复，不要假设命令成功或失败。跨会话的唯一持久事实以 GitHub、仓库文件与经核实的运行日志为准。
