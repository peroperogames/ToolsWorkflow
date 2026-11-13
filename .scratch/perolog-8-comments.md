# PeroLog #8 — comments as of now

PR: https://github.com/peroperogames/PeroLog/pull/8 (head c5fdbf5)

## Conversation comments (16)

### Maverick114514 — 10/20/2026 07:47:34

@perotoolsbot review o1


### tanyyt — 10/21/2026 01:53:23

@perotoolsbot review

### tanyyt — 10/21/2026 06:30:50

@perotoolsbot review

### perotoolsbot[bot] — 10/21/2026 07:02:53

⚠️ Unity: 编译通过；单元测试没有跑完，也就没有报告，不能算通过。

### Maverick114514 — 10/21/2026 07:23:14

@perotoolsbot review


### perotoolsbot[bot] — 10/21/2026 07:54:23

⚠️ Unity: 编译通过；单元测试没有跑完，也就没有报告，不能算通过。

### Gatongone — 10/21/2026 08:03:21

@perotoolsbot rebuild

### Gatongone — 10/21/2026 08:08:32

@perotoolsbot rebuild

### perotoolsbot[bot] — 10/21/2026 08:09:28

🔧 **重新构建与测试**（只跑门禁，未做评审）
仓库类型：Unity package com.prpr.log

没有构建/测试步骤运行——该仓库没有，或工具链不可用，详见日志。

### Gatongone — 10/21/2026 08:19:07

@perotoolsbot rebuild

### perotoolsbot[bot] — 10/21/2026 08:33:20

⚠️ Unity: 编译通过；单元测试没有跑完（卡在 `PeroTools2.Log.Tests.UploadCases.UploadTimeoutFailedTest`），也就没有报告，不能算通过。

**测试卡在**：`PeroTools2.Log.Tests.UploadCases.UploadTimeoutFailedTest`（单独运行也没有产出报告，其余用例因此没有跑）

### perotoolsbot[bot] — 10/21/2026 08:33:53

🔧 **重新构建与测试**（只跑门禁，未做评审）
仓库类型：Unity package com.prpr.log

⚠️ Unity: 编译通过；单元测试没有跑完（卡在 `PeroTools2.Log.Tests.UploadCases.UploadTimeoutFailedTest`），也就没有报告，不能算通过。

### perotoolsbot[bot] — 10/21/2026 08:58:17

⚠️ Unity: 编译通过；单元测试没有跑完（单独跑都过，最小的复现组合是 `PeroTools2.Log.Tests.UrlUploadTests.UploadTimeoutFailedTest`），也就没有报告，不能算通过。

**测试卡住，但没有单个用例能复现**：最小的组合是 `PeroTools2.Log.Tests.UrlUploadTests.UploadTimeoutFailedTest`（单独跑各自都过，一起跑就挂；其余用例因此没有跑）

### perotoolsbot[bot] — 10/21/2026 08:58:42

🔧 **重新构建与测试**（只跑门禁，未做评审）
仓库类型：Unity package com.prpr.log

⚠️ Unity: 编译通过；单元测试没有跑完（单独跑都过，最小的复现组合是 `PeroTools2.Log.Tests.UrlUploadTests.UploadTimeoutFailedTest`），也就没有报告，不能算通过。

### perotoolsbot[bot] — 10/21/2026 09:34:40

🔴 Unity: 11 个单元测试失败。

**单元测试失败**：
- PeroTools2.Log.Tests.InitDirLogUploaderTests.AutoUploadHonorsMaxUploadCountTest(1) — Unhandled log message: '[Exception] AssertionException:   Auto upload should honor MaxUploadCountPerTime
- PeroTools2.Log.Tests.InitDirLogUploaderTests.AutoUploadHonorsMaxUploadCountTest(3) — Unhandled log message: '[Exception] AssertionException:   Auto upload should honor MaxUploadCountPerTime
- PeroTools2.Log.Tests.InitDirLogUploaderTests.AutoUploadHonorsMaxUploadCountTest(5) — Unhandled log message: '[Exception] AssertionException:   Auto upload should honor MaxUploadCountPerTime
- PeroTools2.Log.Tests.InitDirLogUploaderTests.ManualUploadCleansStaleMemoBeforeRotationTest — The frozen current log should be uploaded after rotation
- PeroTools2.Log.Tests.InitDirLogUploaderTests.ManualUploadExcludesActiveLoggingFileTest — Manual upload should upload the frozen snapshot and exclude the active log file
- PeroTools2.Log.Tests.InitDirLogUploaderTests.ManualUploadIgnoresMaxUploadCountAndKeepsMemoTest — Automatic upload should honor MaxUploadCountPerTime
- PeroTools2.Log.Tests.InitDirLogUploaderTests.ManualUploadIgnoresMaxUploadCountTest — Manual upload should ignore MaxUploadCountPerTime
- PeroTools2.Log.Tests.InitDirLogUploaderTests.ManualUploadSuccessTest
- PeroTools2.Log.Tests.InitDirLogUploaderTests.UploadFailedTest — System.NullReferenceException : Object reference not set to an instance of an object
- PeroTools2.Log.Tests.InitDirLogUploaderTests.UploadPartiallyFailedTest — System.NullReferenceException : Object reference not set to an instance of an object
- PeroTools2.Log.Tests.InitDirLogUploaderTests.UploadSuccessTest

### perotoolsbot[bot] — 10/21/2026 09:35:17

🔧 **重新构建与测试**（只跑门禁，未做评审）
仓库类型：Unity package com.prpr.log

🔴 Unity: 11 个单元测试失败。

## Inline review comments (57)

### perotoolsbot[bot] — 10/20/2026 06:38:39 — Test/Runtime/PeroLogTests.cs:720  (id 4322146453, reply_to )

⚠️ **ReSharper**: The field is sometimes used inside synchronized block and sometimes used without synchronization

### Maverick114514 — 10/20/2026 06:43:49 — Test/Runtime/PeroLogTests.cs:720  (id 4322178867, reply_to 4322146453)

不存在这个问题

### perotoolsbot[bot] — 10/20/2026 06:45:10 — Test/Runtime/PeroLogTests.cs:720  (id 4322187577, reply_to 4322146453)

同意，这里确实没有真实的并发问题：`m_PreSeededUploadedDir` 只在测试线程的 SetUp/TearDown 里顺序读写，`lock` 保护的是共享的静态 `s_UploadedDirs` 列表而非这个字段。ReSharper 那条提示只是看到同一字段在锁内（`uploadedDirs.Remove(m_PreSeededUploadedDir)`）和锁外（`if (null != …)`、`= null`）都被访问而触发的模式检查，是误报。如果想让后续维护的人不再疑惑，可考虑把判空也挪进锁内或统一加锁，但现状语义上没问题。

### perotoolsbot[bot] — 10/20/2026 06:52:36 — Runtime/Log/StdIo/BaseStdIo.cs:88  (id 4322237285, reply_to )

**memo 防护在构造阶段是死代码**：`GetNextLogFilePath` 里的 `IsPathInLogMemo(nextFilePath)` 依赖 `m_LogUploader`，但 `m_LogUploader` 是 `Build()` 里 `foreach (var f in options) f(stdIo)` 阶段才由 `WithUploader` 赋值的，而 `GetNextLogFilePath` 在构造函数里就已经执行完，此刻 `m_LogUploader` 恒为 null，`IsPathInLogMemo` 对所有候选名恒返回 false。也就是说本次 PR 声明要防的「选名时排除 memo 里已记录的文件名」在重建的关键路径（构造函数选名）上根本没有生效，重建实际只靠 `File.Exists` 兜底。当 memo 条目指向的文件已被外部删除（而 memo 条目要等下次上传触发 `RemoveNotExistSucceedFilesInMemo` 才会被清理）时，重建仍会选中该 memo 名并写入，新内容将永久被 `IsContainsInLogMemo` 判为已上传而不再上传——这正是本 PR 想修的问题。建议把最终选名推迟到 `CreateStreams`（options 已应用之后）再做，或在 `CreateStreams` 里对已选名字再查一次 memo，命中则重新轮转选名。

### perotoolsbot[bot] — 10/20/2026 06:52:37 — Runtime/Log/StdIo/BaseStdIo.cs:179  (id 4322237425, reply_to )

**跨锁读写 `m_LogFile` 失去同步（相对旧代码的回退）**：`m_LogFile` 现在只在 `ReopenLogFileStream`（`OnUploadStart` 的 `m_Locker` 临界区内）写入，而这里是在全局 `s_File2StdIo` 锁内读取——两把锁之间没有 happens-before，`m_LogFile` 又是非 volatile 的普通字段。改到旧实现里「正在写的文件集合」是注册表 Keys，写入（轮转后 `s_File2StdIo.Remove/Add`）与读取都在 `s_File2StdIo` 锁内完成，是正确同步的；本次把写者换到 `m_Locker` 后读者拿到的可能是陈旧值。后果：上传线程轮转到新文件时，另一个线程（如重建选名）可能因读到过期快照而选中对方刚刚创建、即将写入的活动文件——两个实例都用 `FileAccess.Write, FileShare.Read` 打开同一个文件，后打开者直接抛 IOException，文件日志静默失效。建议让轮转在 `s_File2StdIo` 锁内同步更新 `m_LogFile`（与读取同锁），或将 `m_LogFile` 声明为 volatile。

### perotoolsbot[bot] — 10/20/2026 06:52:38 — Runtime/Log/StdIo/BaseStdIo.cs:263  (id 4322237589, reply_to )

**基名族保护会让长进程内的冻结文件永久堆积**：按本 PR 自己的描述，同一进程内多次 Build 时 `sessionId`/`initTime`/`deviceId` 都不变，基名族恒定；配合「重建永远换新文件」的命名，每次重建都会新增一个 `_N.log`，而 `DeleteExpiredFiles` 对活实例的整个族（含早已上传的冻结文件）无条件保留，`m_LogFileExpireTimeS` 过期逻辑在进程存活期间永不生效。旧代码只保护「当前正在写入的文件」，上一轮重建留下的冻结文件到期后会被删除。对频繁重建的长生命周期进程，磁盘占用将无界增长。另外该保护的原始理由（「删掉之后轮转会把名字复用」）在新的命名方案下已基本不成立：`GetNextLogFilePath` 已同时跳过磁盘已存在与 memo 已记录的名字，轮转不再复用旧名。建议缩小保护范围：只保留「上传器待上传列表/尚未上传」的冻结文件，已上传并超过过期时间的文件仍可删除。

### perotoolsbot[bot] — 10/20/2026 06:52:40 — Test/Runtime/ILogTests/StdIoTests.cs:787  (id 4322237717, reply_to )

**测试覆盖的是构造函数路径，而非本 PR 在 PeroLog.cs 新增的核心逻辑**：该用例通过 `GetStdIo` 直接二次构建，`previousStdIo` 是在第二个实例的构造函数「按基名查重 → Dispose 旧实例」路径里被释放的，`PeroLog.BuildHelper` 里的 `DisposeCurrentStdIo()`（以及 Dispose 抛异常时复位 `s_IsBuilding` 的 catch 逻辑）完全没有被走到。这两个新增逻辑目前没有任何测试：`DisposeCurrentStdIo` 只有在 Dispose 失败（`m_WriteToFileTask.Wait()` 抛 AggregateException）时才会复位 `s_IsBuilding`，而该分支一旦漏掉就会让所有日志只进 `s_InitCacheLogs` 且缓存无界增长。建议补一个通过 `PeroLog.lastBuilder.BuildPeroLog()` 连续构建两次、并模拟旧 StdIo Flush 抛异常的用例，断言旧实例 `m_IsDisposed` 为 true 且 `s_IsBuilding` 已被复位。

### perotoolsbot[bot] — 10/20/2026 06:52:41 — Test/Runtime/ILogTests/StdIoTests.cs:  (id 4322237900, reply_to )

**断言消息与断言语义相反，会误导后续调试**：`CollectionAssert.Contains` 断言的是旧文件**仍然存在**（重建未删除旧文件），消息却写「删除了同名的旧文件」，测试失败时排查者会朝相反的方向找原因。同时上方 `RebuildStdIoClearFileTest` 里的注释「理想状况是在已有的日志文件的末尾写入」也是旧行为描述，与新行为（重建换新文件）相反。建议把消息改为「重建后同名的旧日志文件不应被删除」并同步更新该注释。

### Maverick114514 — 10/20/2026 07:11:26 — Runtime/Log/StdIo/BaseStdIo.cs:263  (id 4322362844, reply_to 4322237589)

这个正是本次修改的意图之一，不能复用用过的编号。复用编号会导致业务收集日志之后难以确认顺序，导致排查困难

### perotoolsbot[bot] — 10/20/2026 07:12:50 — Runtime/Log/StdIo/BaseStdIo.cs:263  (id 4322372866, reply_to 4322237589)

明白了，保留「编号不复用」确实是设计意图，我不再把这点当成问题。但请留意一个副作用：活实例的整个基名族在进程存活期间都不会被 `DeleteExpiredFiles` 清理（过期时间只对族外文件生效），频繁重建的长生命周期进程磁盘会持续增长。编号不复用和「已上传的冻结文件到期后可删」并不冲突——删掉的是早已上传的旧 `_N.log`，新编号照旧递增、不会复用。当前按族整体保护的实现把这个过期回收一并禁掉了，建议改为只保护「尚未上传/在待上传列表上」的冻结文件。

### Maverick114514 — 10/20/2026 07:14:13 — Runtime/Log/StdIo/BaseStdIo.cs:88  (id 4322382464, reply_to 4322237285)

确认成立，已修（264a19c）。

`CreateStreams` 里在 options 应用之后再查一次 memo：命中就用 `GetNextLogFilePath` 重新轮转选名，并同步 `uploader.UpdateLoggingFile(m_LogFile, nextLogFile)`——否则新名字会被当成 logging file 排除掉。选名要用的「正在写入」快照仍然在进入 `m_Locker` 之前取，保持原有锁顺序。

### Maverick114514 — 10/20/2026 07:14:19 — Runtime/Log/StdIo/BaseStdIo.cs:179  (id 4322383206, reply_to 4322237425)

确认成立，采用 volatile 方案：`private volatile string m_LogFile;`（264a19c）。

没有改成「轮转时进 s_File2StdIo 同步更新」是因为锁序会反过来：构造流程是持有 `s_File2StdIo` 去 Dispose 旧 StdIo，而旧 StdIo 的 Dispose 要拿 `m_Locker`；轮转里再嵌套 `s_File2StdIo` 就成了 `s_File2StdIo → m_Locker` 与 `m_Locker → s_File2StdIo` 交叉，直接死锁。

补充一点：基名相同的两个实例本来就互斥（构造时按基名查重会先 Dispose 旧的），所以这条路径上更现实的是丢快照导致选名撞车；volatile 保证读到的不是陈旧值，剩下的窗口由 `File.Exists` 兜底。

### Maverick114514 — 10/20/2026 07:14:26 — Runtime/Log/StdIo/BaseStdIo.cs:263  (id 4322383992, reply_to 4322237589)

确认成立，已按要求缩小保护范围（264a19c）。

`DeleteExpiredFiles` 现在只保留精确的活跃写入路径（`GetFilesBeingWritten()` 的完整路径集合，包含正在写入的活动 `_N` 文件），冻结文件过期即删；`GetLiveLogFileStems` / `IsLiveLogFileFamily` 一并删除。

名字复用风险也确实消掉了：`GetNextLogFilePath` 已经同时跳过「磁盘已存在」「正在写入」「memo 已记录」三种名字，测试里补了对应断言（bd52e09）。

### Maverick114514 — 10/20/2026 07:14:28 — Test/Runtime/ILogTests/StdIoTests.cs:787  (id 4322384288, reply_to 4322237717)

确认成立，已补两个用例到 `Test/Runtime/PeroLogTests.cs`（bd52e09）：

- `RebuildShouldDisposePreviousStdIoTest`：`PeroLog.lastBuilder.BuildPeroLog()` 连续两次，断言 `s_StdIo` 换成新实例、旧实例 `m_IsDisposed` 为 true、`s_IsBuilding` 已复位。
- `RebuildShouldResetIsBuildingWhenDisposeThrowsTest`：`m_WriteToFileTask.Wait()` 抛 AggregateException 依赖写任务时序、无法稳定复现，所以注入一个 Dispose 里抛 `AggregateException` 的假 `BaseStdIo` 到 `s_StdIo`，断言异常外抛且 `s_IsBuilding` 被复位。

本地在 Unity 2022.3.62f3 的测试工程里跑了完整 PlayMode 套件：**475 passed / 0 failed**。

### Maverick114514 — 10/20/2026 07:14:30 — Test/Runtime/ILogTests/StdIoTests.cs:  (id 4322384504, reply_to 4322237900)

确认成立，已改（bd52e09）：

- 断言消息 → 「重建后同名的旧日志文件不应被删除」
- 注释 → 「第二个stdio写入：新的命名方案下重建会另起一个 _N 新文件，旧文件作为冻结快照原样保留」

### perotoolsbot[bot] — 10/20/2026 07:15:43 — Runtime/Log/StdIo/BaseStdIo.cs:263  (id 4322392831, reply_to 4322237589)

感谢确认与修复，四处都已核对过新代码（volatile `m_LogFile`、`CreateStreams` 里二次 memo 检查并同步 `UpdateLoggingFile`、`DeleteExpiredFiles` 改为只保护精确活动路径、以及两个新测试用例），实现与锁序推理一致，全部符合预期。已把相应线程标记为已解决。

### perotoolsbot[bot] — 10/20/2026 07:15:46 — Test/Runtime/ILogTests/StdIoTests.cs:787  (id 4322393214, reply_to 4322237717)

收到，两个用例已覆盖 `DisposeCurrentStdIo` 与异常分支，且 475 个 PlayMode 用例全部通过，我这边已无遗留问题。多谢确认。

### perotoolsbot[bot] — 10/20/2026 07:15:46 — Test/Runtime/ILogTests/StdIoTests.cs:  (id 4322393277, reply_to 4322237900)

修改已确认，两处都改到位了：断言消息「重建后同名的旧日志文件不应被删除」与 `CollectionAssert.Contains` 的语义一致，注释也同步更新为新行为描述。所有遗留问题均已解决，PR 可以继续。

### perotoolsbot[bot] — 10/20/2026 07:15:50 — Runtime/Log/StdIo/BaseStdIo.cs:88  (id 4322393680, reply_to 4322237285)

三个修复都确认到位：`CreateStreams` 里补的 memo 复查把「构造期死代码」真正激活了（顺带 `UpdateLoggingFile` 的同步处理也避免了新名字被当作 logging file 排除）；`volatile m_LogFile` 与锁序说明相符；缩窄后的过期清理保护范围、注入式异常测试（475 passed）和改后的断言消息都没问题。我已经把对应线程全部标记为已解决。

### perotoolsbot[bot] — 10/20/2026 07:16:07 — Runtime/Log/StdIo/BaseStdIo.cs:179  (id 4322395729, reply_to 4322237425)

volatile 方案没问题，锁序理由也成立（`s_File2StdIo → m_Locker` 与 `m_Locker → s_File2StdIo` 确实会交叉死锁）。四个线程都已核实修复后全部关闭。我唯一留意的是 `CreateStreams` 里新加的 memo 重查：它把 `IsPathInLogMemo(m_LogFile)` 放进了 `try` 块，若 memo 命中后 `GetNextLogFilePath` 或 `UpdateLoggingFile` 抛异常，会落入 `catch` 只打一条 `Debug.LogError`，随后 `m_FileStream` 仍为 null 但实例已登记注册表、Log() 判空直接丢日志——和你「拆到一半静默丢日志」的设计一致，可以接受，仅提示一句。没有其他阻塞项。

### Maverick114514 — 10/20/2026 07:16:37 — Runtime/Log/StdIo/BaseStdIo.cs:179  (id 4322398992, reply_to 4322237425)

同意，这点是有意保留的：`CreateStreams` 里那个 `catch` 本来就承担「日志文件名非法也不让 PeroLog 初始化失败」的兜底（注释里写了线上遇到过非法命名），而 `GetNextLogFilePath` 是靠 `Insert` 拼后缀，遇到畸形基名确实可能抛。把 memo 重查挪出 `try` 会让这类畸形名直接冒泡成 Build 失败，属于行为回退，所以选择让它继续走同一条兜底路径——最坏情况是这一轮文件日志失效（`m_FileStream` 为 null，`Log()` 判空丢日志），但不会把宿主初始化搞挂。

如果以后要更严格，可以把 memo 重查单独包一层 `try`，抛异常时退回构造期选好的名字继续开流（宁可写进 memo 文件也不静默丢日志）。当前不动。

### perotoolsbot[bot] — 10/20/2026 07:17:52 — Runtime/Log/StdIo/BaseStdIo.cs:179  (id 4322407597, reply_to 4322237425)

用户（开发者 Maverick114514）回复了我之前在某条线程里留下的评论。我之前在 BaseStdIo.cs:185 那条线程里说过：「CreateStreams 里新加的 memo 重查把 IsPathInLogMemo(m_LogFile) 放进了 try 块…… 和『拆到一半静默丢日志』的设计一致，可以接受，仅提示一句。」

开发者现在解释了这是有意保留的：这个 catch 本来就是兜底路径，如果挪出 try 会让畸形基名冒泡成 Build 失败。并且提出以后可以更严格——单独包一层 try，退回构造期选好的名字。

我需要简洁直接地回复。这是对话的延续，不是在问新的 review 请求，而是对我在那条线程里提到的非阻塞提示的回应。我应该确认理解，表示同意/接受，不要假装说过没说过的话。

按照指示：要引用或转述具体那条评论并解释理由；不声称说过没说过的话；用简体中文；简洁。

我的回复应该是：确认这是合理的取舍，接受，没有阻塞项，可以继续。

注意：开发者说“当前不动”…… 我不需要坚持。可以简单说同意，接受这个取舍，感谢解释。也许简短提到如果以后要更严格，那个“单独 try 退回旧名”的方案也可以。

确保不编造内容。我确实在那条线程里说过“可以接受，仅提示一句”。

所以回复大概：

---

同意，这个取舍合理。我之前那条只是非阻塞提示，你解释的「挪出 try 会让畸形基名冒泡成 Build 失败」正好说明现状保留兜底是对的——文件日志静默失效比初始化挂掉好，而且失败路径已经被注释和测试覆盖过。以后若要做更严格版本，「单独 try + 退回构造期名字」也是个可行的方向，但不是本 PR 的阻塞项。没有其他遗留问题，可以继续。

### Maverick114514 — 10/20/2026 07:23:47 — Runtime/Log/StdIo/BaseStdIo.cs:263  (id 4322449589, reply_to 4322237589)

这条提醒是对的，我上一版注释里那句「不会再引发名字复用」写错了，已经补掉（8fdff7e）。

复现链条是这样的：同一个进程内重建时 `sessionId`（`s_SessionId` 是进程级 Guid）和 `initTime`（进程级毫秒戳）都不变，基名恒定 → 上一轮的 `_1.log`/`_2.log` 过了 `m_LogFileExpireTimeS` 被 `DeleteExpiredFiles` 删掉，memo 里的同名记录也会被 `RemoveNotExistSucceedFilesInMemo` 按「文件不存在」清掉 → 新实例的 `m_RotationSequence` 又从 0 开始数，`File.Exists` 和 memo 都判空闲 → 重新分配出 `_1`/`_2`。服务端于是收到同名但内容不同的两份日志，排查时分不清先后，也容易和 memo 记录互相误导。

也就是说「族保护」确实能挡住这条链（名字一直被占着），但代价是过期清理在进程存活期内失效——两个诉求没法靠「删不删」同时满足，所以我上一版只解决了堆积、把复用漏了。

修法是在 `GetNextLogFilePath` 里按基名维持进程内序号高水位（`s_BaseLogFile2HighestSequence` + `lock (s_HighestSequenceLocker)`）：新实例接着已用的最大序号往下分配，名字即使被删也不会再被分配一次。只做进程内高水位就够——基名由 `sessionId`（进程内 Guid）和 `initTime`（毫秒戳）拼成，跨进程不可能撞名，同名只可能出现在同进程的多次重建之间。不用 `s_File2StdIo` 当锁，是因为 `ReopenLogFileStream` 已持有 `m_Locker`，反向去拿会和构造流程的锁序交叉。

测试 `RebuildShouldNotReuseDeletedLogFileNameTest`（两个 fixture 都会跑）：构建 → 删光 `*.log` 模拟过期清理 → 重建，断言新文件是 `<基名>_2.log` 而不是 `_1.log`。这条用例有牙——把高水位临时关掉后它确实失败（实际得到 `_1.log`）。全量 PlayMode：**477 passed / 0 failed**。

### perotoolsbot[bot] — 10/20/2026 07:24:58 — Runtime/Log/StdIo/BaseStdIo.cs:263  (id 4322458234, reply_to 4322237589)

收到，这条复现链条把我当时的建议补完整了——我上一轮说「删掉旧文件、新编号照旧递增不会复用」其实漏了关键一环：新实例的 `m_RotationSequence` 会从 0 重新数，只要文件被删且 memo 清空，`_1` 确实会被重新分配。所以「缩窄保护」和「不复用编号」确实是两件事，不能用同一个开关解决。

进程内高水位方案我看是成立的：基名由进程级 `sessionId`/`initTime` 拼成，跨进程天然不撞名，同名只可能出现在同进程重建链里，`s_BaseLogFile2HighestSequence` 恰好覆盖这条链；用独立小锁而不是拿 `s_File2StdIo` 也避开了和 `m_Locker` 的锁序交叉。

测试有牙这点很关键（关掉高水位会实际失败），加上 477 passed 全绿，这个修复我这边没有异议。之前那条线程的遗留问题可以关闭了。

### Maverick114514 — 10/20/2026 07:34:40 — Runtime/Log/StdIo/BaseStdIo.cs:263  (id 4322531621, reply_to 4322237589)

补充更正：这一版最终**没有**采用「缩小到精确活跃路径」，已改回 ca4857b 里的原有实现。

结论还是遵从我最早在这条线程里说的那条（07:11）：**编号在进程存活期间不复用**。但实现手段不是加序号高水位，而是直接保留基名族——`<stem>.log` 与 `<stem>_N.log` 一律不删，名字根本不会变回空闲，也就谈不上被重新分配。

代价明说（是有意接受，不是遗漏）：同一基名族里已经冻结、甚至已经上传完成的文件，在进程存活期间不会被 `m_LogFileExpireTimeS` 清掉，长进程里磁盘占用会持续累积；只有重启后基名变化，才由新进程把这些旧文件当过期文件清掉。相比「服务端出现同名但内容不同的日志、排查时分不清先后」，这个代价值得付。

分支已强推（`8fdff7e` → `3ca18a5`），现在只剩两处改动：

- `CreateStreams` 里在 options 应用之后再查一次 memo，命中就重新轮转并 `UpdateLoggingFile` 同步上传器记录；
- `m_LogFile` 声明为 `volatile`（写者在 `m_Locker` 内、读者在 `s_File2StdIo` 内，两者之间没有 happens-before）。

之前提到的进程内序号高水位（`s_BaseLogFile2HighestSequence` / `s_HighestSequenceLocker`）一并撤掉了：名字既然不会被释放，高水位就没有存在意义。测试侧 `DeleteExpiredFilesProtectsAllLiveLogFilesTest` 也恢复成断言「族内过期文件保留」。

### perotoolsbot[bot] — 10/20/2026 07:35:59 — Runtime/Log/StdIo/BaseStdIo.cs:263  (id 4322541937, reply_to 4322237589)

收到，这个取舍我认可：确定性优先——宁可在进程存活期保留族文件，也不让服务端出现同名不同内容。这正好落回我之前在 244/268 线程里列的代价，你现在明说是「有意接受」，那就不算遗漏，我不再坚持缩窄保护。

两个技术点确认过：

1. 撤掉高水位是自洽的——既然族内文件在进程存活期内根本不会从磁盘消失，高水位确实没有存在意义。「族保护 + `GetNextLogFilePath` 跳过磁盘已存在/memo 已记录」这条链路足以保证不撞名。
2. 反过来，这个「不复用」保证完全依赖「族永不删」这一条。将来若有人恢复族内过期清理、或手工删文件，名字复用问题会立刻回来。

所以想问一下：早先 `RebuildShouldNotReuseDeletedLogFileNameTest`（删光模拟过期 → 断言重建后是 `_2` 而不是 `_1`）现在还在测试集里吗？族保护下它应该跑不通，但如果直接删掉，将来这层保证就没有回归测试兜底了。不在本 PR 留也行，只要是有意处理。

其余没有阻塞项。

### perotoolsbot[bot] — 10/20/2026 07:49:41 — Test/Runtime/PeroLogTests.cs:720  (id 4322648241, reply_to )

⚠️ **ReSharper**: The field is sometimes used inside synchronized block and sometimes used without synchronization

### perotoolsbot[bot] — 10/20/2026 07:49:43 — Test/Runtime/PeroLogTests.cs:  (id 4322648392, reply_to )

⚠️ **ReSharper**: Type argument specification is redundant

### perotoolsbot[bot] — 10/20/2026 07:49:44 — Test/Runtime/PeroLogTests.cs:  (id 4322648520, reply_to )

⚠️ **ReSharper**: Name 'IsDisposeAttempted' does not match rule 'Properties'. Suggested name is 'isDisposeAttempted'.

### perotoolsbot[bot] — 10/20/2026 07:49:45 — Test/Runtime/PeroLogTests.cs:  (id 4322648657, reply_to )

⚠️ **ReSharper**: Declaring new protected method 'bool PeroTools2.Log.Tests.PeroLogTests.ThrowingDisposeStdIo.TryFlushToCache(MemoryStream)' in sealed class is the same as declaring it as private

### perotoolsbot[bot] — 10/20/2026 07:49:46 — Test/Runtime/PeroLogTests.cs:  (id 4322648793, reply_to )

⚠️ **ReSharper**: Declaring new protected method 'bool PeroTools2.Log.Tests.PeroLogTests.ThrowingDisposeStdIo.TryStartWritingTask(FileStream)' in sealed class is the same as declaring it as private

### perotoolsbot[bot] — 10/20/2026 07:49:47 — Test/Runtime/PeroLogTests.cs:  (id 4322648916, reply_to )

⚠️ **ReSharper**: Declaring new protected method 'void PeroTools2.Log.Tests.PeroLogTests.ThrowingDisposeStdIo.CompleteFlush(FileStream)' in sealed class is the same as declaring it as private

### perotoolsbot[bot] — 10/20/2026 07:49:48 — Test/Runtime/PeroLogTests.cs:  (id 4322649041, reply_to )

⚠️ **ReSharper**: Declaring new protected method 'void PeroTools2.Log.Tests.PeroLogTests.ThrowingDisposeStdIo.DisposeImpl(bool)' in sealed class is the same as declaring it as private

### perotoolsbot[bot] — 10/21/2026 01:55:28 — Test/Runtime/PeroLogTests.cs:720  (id 4332243792, reply_to )

⚠️ **ReSharper**: The field is sometimes used inside synchronized block and sometimes used without synchronization

### perotoolsbot[bot] — 10/21/2026 01:55:29 — Test/Runtime/PeroLogTests.cs:  (id 4332243927, reply_to )

⚠️ **ReSharper**: Type argument specification is redundant

### perotoolsbot[bot] — 10/21/2026 01:55:31 — Test/Runtime/PeroLogTests.cs:  (id 4332244029, reply_to )

⚠️ **ReSharper**: Name 'IsDisposeAttempted' does not match rule 'Properties'. Suggested name is 'isDisposeAttempted'.

### perotoolsbot[bot] — 10/21/2026 01:55:32 — Test/Runtime/PeroLogTests.cs:  (id 4332244132, reply_to )

⚠️ **ReSharper**: Declaring new protected method 'bool PeroTools2.Log.Tests.PeroLogTests.ThrowingDisposeStdIo.TryFlushToCache(MemoryStream)' in sealed class is the same as declaring it as private

### perotoolsbot[bot] — 10/21/2026 01:55:33 — Test/Runtime/PeroLogTests.cs:  (id 4332244257, reply_to )

⚠️ **ReSharper**: Declaring new protected method 'bool PeroTools2.Log.Tests.PeroLogTests.ThrowingDisposeStdIo.TryStartWritingTask(FileStream)' in sealed class is the same as declaring it as private

### perotoolsbot[bot] — 10/21/2026 01:55:34 — Test/Runtime/PeroLogTests.cs:  (id 4332244355, reply_to )

⚠️ **ReSharper**: Declaring new protected method 'void PeroTools2.Log.Tests.PeroLogTests.ThrowingDisposeStdIo.CompleteFlush(FileStream)' in sealed class is the same as declaring it as private

### perotoolsbot[bot] — 10/21/2026 01:55:36 — Test/Runtime/PeroLogTests.cs:  (id 4332244430, reply_to )

⚠️ **ReSharper**: Declaring new protected method 'void PeroTools2.Log.Tests.PeroLogTests.ThrowingDisposeStdIo.DisposeImpl(bool)' in sealed class is the same as declaring it as private

### tanyyt — 10/21/2026 02:14:05 — Runtime/Log/StdIo/BaseStdIo.cs:228  (id 4332336793, reply_to )

这里为啥要做多一次判等？

### tanyyt — 10/21/2026 02:28:23 — Runtime/Log/PeroLog.cs:  (id 4332408431, reply_to )

这样写似乎就代表一次只会有一个stdio了，是不是放在s_StdIo中的value被替换的时候去Dispose比较好一点

### Maverick114514 — 10/21/2026 06:17:01 — Runtime/Log/StdIo/BaseStdIo.cs:228  (id 4333622374, reply_to 4332336793)



两个线程并发 `Build()` 时旧实例被 Dispose 两遍：A 卡在 `Flush()`，B 已注销它并登记了新实例，A 走到注销那一步删掉的就是新实例（此后它仍在写文件，却不再被 `GetFilesBeingWritten`、`GetLiveLogFileStems` 看见，也不会重新登记）。

| 时刻 | 线程 A：`Build()` | 线程 B：`Build()` |
|---|---|---|
| t1 | `DisposeCurrentStdIo()` 置空 `s_StdIo`，对 S1 `Dispose()`，卡在 `Flush()` | |
| t2 | | `s_StdIo` 已为 `null` 跳过；构造 S2 时按基名查重查到 S1，再 `Dispose()` 一次并注销 |
| t3 | | S2 登记到 `s_File2StdIo` |
| t4 | `Flush()` 返回，注销 —— 键上已是 S2 | |

### Maverick114514 — 10/21/2026 06:19:25 — Runtime/Log/PeroLog.cs:  (id 4333636837, reply_to 4332408431)

删除这个函数了，查重Dispose在BaseStdio的构造函数就有实现

### tanyyt — 10/21/2026 06:19:28 — Runtime/Log/StdIo/BaseStdIo.cs:228  (id 4333637148, reply_to 4332336793)

加个注释吧

### Maverick114514 — 10/21/2026 06:23:27 — Runtime/Log/StdIo/BaseStdIo.cs:228  (id 4333662324, reply_to 4332336793)

已经加上了

### Maverick114514 — 10/21/2026 06:26:51 — Runtime/Log/PeroLog.cs:  (id 4333683496, reply_to 4332408431)

删除了s_StdIo

### perotoolsbot[bot] — 10/21/2026 07:09:40 — Test/Runtime/PeroLogTests.cs:  (id 4333984273, reply_to )

**测试引用已删除的 `s_StdIo` 字段，运行时必然失败**：产品代码已删除 `s_StdIo` 字段与 `DisposeCurrentStdIo()`（PeroLog.cs 的 diff 已无这些改动），但这两个测试仍通过反射引用 `s_StdIo`。`TestHelper.GetStaticField` 对不存在的字段会执行 `Assert.IsNotNull(field, "Field s_StdIo not found")` 直接抛异常：`RebuildShouldDisposePreviousStdIoTest` 在第 733 行、`RebuildShouldResetIsBuildingWhenDisposeThrowsTest` 在第 761 行都会失败。这与 ⚠️「单元测试没有跑完，也就没有报告」的状态吻合。请删除这两个测试，或改写为验证当前的构造函数「按基名查重 → Dispose」路径（`ThrowingDisposeStdIo` 已具备验证能力：构建第二个同基名实例时断言旧实例被释放）。

### perotoolsbot[bot] — 10/21/2026 07:09:47 — Test/Runtime/PeroLogTests.cs:  (id 4333985101, reply_to )

**测试验证的产品逻辑（`DisposeCurrentStdIo` 抛异常时复位 `s_IsBuilding`）已被删除，测试失去意义**：产品代码删除了 `DisposeCurrentStdIo()`，重建时旧 StdIo 的释放完全交由下一个实例构造函数「按基名查重 → Dispose」路径处理，`s_IsBuilding` 不再有 Dispose 异常复位分支。因此「注入会抛的假 StdIo 到 `s_StdIo`」这个测试既无法注入（字段不存在），注入后也没有任何产品代码会调用它的 `Dispose`——`isDisposeAttempted` 断言永远不会成立。需与 `RebuildShouldDisposePreviousStdIoTest` 一并处理（删除或改写为验证构造查重路径）。

### perotoolsbot[bot] — 10/21/2026 07:09:54 — Runtime/Log/PeroLog.cs:467  (id 4333986109, reply_to )

**删除 `DisposeCurrentStdIo()` 后，重建路径的旧 StdIo 释放只依赖构造函数「按基名查重」，与 PR 目标出现偏差**：本 PR 的核心目标之一是「重建时显式释放上一个 StdIo」（原实现 `DisposeCurrentStdIo` 在 `BuildHelper` 里重建前调用）。现在它被删除后，重建时旧实例的释放只剩 `BaseStdIo` 构造函数里 `s_File2StdIo.TryGetValue(m_BaseLogFile, ...)` 查重这条路径——它**只在基名相同时才释放**。若业务用不同参数（如更换 deviceId 后重建）导致基名不同，旧 StdIo 的写句柄、`Application.quitting`/`wantsToQuit` 订阅与注册表条目会全部泄漏，PR 描述的问题 2 部分回退。tanyyt 建议的「在 `s_StdIo` 的 value 被替换时 Dispose」正是规避该问题的方向。请确认这是有意为之（如接受仅基名相同才释放），还是需要恢复一个不依赖基名相同的释放路径；并请同步补充对应测试覆盖（当前测试已无法通过，见下方两条 inline comment）。

### Maverick114514 — 10/21/2026 07:17:29 — Runtime/Log/PeroLog.cs:467  (id 4334044545, reply_to 4333986109)

这个显示释放上一个stdio是指对应基名的旧stdio，这里没有问题

### perotoolsbot[bot] — 10/21/2026 07:18:23 — Runtime/Log/StdIo/BaseStdIo.cs:179  (id 4334051182, reply_to 4322237425)

✔️ 开发者说明「显示释放上一个 stdio 是指对应基名的旧 stdio」，即释放目标是按基名关联的旧实例，当前「构造函数按基名查重 → Dispose」路径正是实现该目标的方式，无偏差。

### perotoolsbot[bot] — 10/21/2026 07:18:29 — Runtime/Log/PeroLog.cs:467  (id 4334051928, reply_to 4333986109)

理解了——「释放上一个 StdIo」的目标对象就是按基名关联的旧实例，构造函数查重路径正是这个语义的实现，不存在偏差，这条线程已关闭。

但仍有两个阻塞项需要处理（与这条线程无关）：
1. `RebuildShouldDisposePreviousStdIoTest` 和 `RebuildShouldResetIsBuildingWhenDisposeThrowsTest` 仍通过反射引用已删除的 `s_StdIo` 字段，`TestHelper.GetStaticField` 会因字段不存在直接抛异常，这两个测试当前必然失败；
2. ⚠️ 状态显示单元测试没有跑完、没有报告，不能算通过，需要先跑通测试确认这两个用例的处理方式（删除或改写为验证构造查重路径）。

### Maverick114514 — 10/21/2026 07:23:04 — Test/Runtime/PeroLogTests.cs:  (id 4334086880, reply_to 4333984273)

已删除

### Maverick114514 — 10/21/2026 07:23:09 — Test/Runtime/PeroLogTests.cs:  (id 4334087502, reply_to 4333985101)

已经删除

### perotoolsbot[bot] — 10/21/2026 07:24:18 — Test/Runtime/PeroLogTests.cs:  (id 4334096280, reply_to 4333985101)

收到，两个失效测试已删除，diff 干净，无未解决线程。三处阻塞项（`s_StdIo` 删除后的构造查重语义确认、两个引用已删字段的测试）均已闭环。PR 审查通过。

### perotoolsbot[bot] — 10/21/2026 07:24:20 — Test/Runtime/PeroLogTests.cs:  (id 4334096482, reply_to 4333984273)

两个失效测试都已删除（`RebuildShouldDisposePreviousStdIoTest` / `RebuildShouldResetIsBuildingWhenDisposeThrowsTest` 连同 `ThrowingDisposeStdIo` 一并移除），`s_StdIo` 相关引用已清干净，我这边无遗留阻塞项。请确保合并前 Unity 侧测试完整跑一遍（之前 ⚠️ 显示单元测试没跑完）再合并。
