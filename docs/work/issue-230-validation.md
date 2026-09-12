# EXP-UX-01 候选验证

任务：[Issue #230](https://github.com/Notyet1307/Exposure-Agent/issues/230)。行为依据：`docs/specs/asset-governance-release-1.md`，固定 commit `8a07554ef399339f0909544c4dbba8b180afc0a1`。实现候选由包含本记录的提交固定，远端 CI 以 PR 的实际 head SHA 为准。

## 开发检查与独立审阅

- PASS：后端完整数据库回归 1059 项，coverage 90%；后端 lint / mypy / ty。后端源码此后未变，未将先前执行伪称新的运行。
- PASS：最终前端组件 131 项；前端 build、非写入 Biome、上下文门禁。组件检查覆盖创建丢响应、存储失败、202 无 Run 恢复、输入漂移、账号/标签页切换、晚到响应和权限错误。
- PASS：Standards / Spec 两轴独立代码审阅无剩余 blocker，包括最终键盘焦点增量。该结论不代替业务验收。
- PASS：此前独立项目/Run API 85 项及完整隔离真实栈 4 项。最终增量只涉及焦点和显式无模型测试模式；旧执行按原代码范围保留。

## 最终候选独立复验

- PASS：最终键盘与无模型真实栈由未参与实现者独立执行，2 passed / 41.7s（登录准备与三模式综合场景），0 retry；真实读取 backend `{qualified:false}` 后完成 present/absent/empty 首轮及固定结果导航，覆盖原生文件选择、Tab/Enter/Space、关键焦点、双语/明暗/reduced-motion 和三个宽度。
- PASS：真实栈与性能复验前后 29/29 业务/测试文件 SHA-256 一致；私有环境原字节恢复，临时 Compose 项目已清理，原现场容器身份保持。
- PASS：最终 29 文件候选性能独立复验，测前/后文件哈希一致。M1 Pro / macOS 26.5.1，Chromium 149.0.7827.55 / Playwright 1.61.1，1366×768，合法分页与固定 v2 Run 身份的 2/400 资产样例，前后各 5 次 fresh page。
- 可比阅读切换：基线 `16e451d` 中位 229.6ms，候选 242.9ms，增加 5.79%（预算 20%）；动作窗口长任务最大分别 61ms / 64ms，无 >200ms。样例合同检查通过。
- 零项目新建的本地 pending 反馈：5 次中位 78.7ms（目标 ≤100ms），测量点击至真实提交按钮 disabled，mock POST 保持 pending。基线没有新建入口，不伪造同功能 before；不把后端响应耗时计作前端反馈。

## 验收解释

- AC01-1 至 AC01-3：创建幂等、权限、确认漂移与重放由数据库/API 检查覆盖；真实浏览器验证创建、准备、确认、发布。API 测试对外部边界使用原有 mock，不将其描述为全控制面故障注入。
- AC01-4：刷新与固定 Run 有真实栈证据；丢响应、202、账号隔离等由 API/组件检查覆盖。完整真实栈故障组合 NOT_RUN。
- AC01-5：隔离合成 present/v2 为两个资源、两个单来源分类各一、两端 ACTIVE；absent/v1 三源汇总不适用；合法零记录 NetFlow 为 UNKNOWN；坏表头拒绝。
- AC01-6：自动浏览器验证三个宽度、键盘/焦点、双语、主题和 reduced-motion。独立人工体验彩排 NOT_RUN，不将自动化等同于人工验收。
- AC01-7：仅声明受控浏览器层和规定样例的本地反馈/切换预算；真实服务端 SLA、其他硬件性能 NOT_RUN。原不符合资产样例合同的探索测量保留为历史记录，不作为本条判定依据。

## 复跑与边界

复用 `bash scripts/test-governance-run.sh` 跑默认真实栈；使用 `bash scripts/test-governance-run.sh --without-model tests/first-comparison.spec.ts` 验证未配置模型的 backend。脚本保留既有模型资格 fixture 检查，仅在独立测试 Compose 中清空 backend 模型 key/endpoint；执行器仍使用本地固定响应 fixture，未调用外部模型，不能称整个 runtime 没有模型配置。

测试使用独立数据库、Artifact、合成 CloudAtlas、随机凭据和候选镜像；不连接现场业务库。私有环境、原始日志、trace 和性能临时脚本不纳入提交。保留既有现场容器、B0/400 资产与其他工作树。

本记录支持候选提交、Draft PR 和 CI 核对，不代表已合并、已部署、客户/生产验收或 Issue 已关闭。旧失败、未运行项不回填为 PASS。
