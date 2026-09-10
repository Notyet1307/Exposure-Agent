# 接管回执

给新会话定位当前基线、能力分级、已测/未测和证据取得方式。不是第二份 Issue 账本。秘密、原始日志、固定 Run 快照、真实 canary 路径和个人安装路径不入 Git。

## 非敏感索引

- 代码身份：main `fbdb06ae5c8a5395f2d55ce13f03bdf35687e272`；已部署功能提交 `afd204dd7f088ba9206a2aca7e50c6a0fd0806a6`；二者 Git tree 相同。
- 镜像身份：运行中 frontend/backend 镜像 tag 为上述功能提交 SHA。用 Compose 标签发现，不是产品承诺。
- 启动组合：[compose.yml](../compose.yml) 加维护者提供的受限 override；不是通用安装路径。运行时路径与启动核对应 [Runtime path](../deployment.md#runtime-path) / [Start and verify](../deployment.md#start-and-verify)。
- 受限配置：向维护者索取受控包或访问；内容不入 Git。
- 测试来源生命周期：本地合成 + [ADR-0014](adr/0014-allow-local-baizhi-synthetic-qualification.md) / [ADR-0015](adr/0015-allow-bounded-synthetic-ai-business-tasks.md) 白名单。样例留在关闭 Issue 记录中，不把 fixture 拷进 Git。
- 备份：见 [Persistent state](../deployment.md#persistent-state)、[Coordinated backup](../deployment.md#coordinated-backup)、[Restore and verification](../deployment.md#restore-and-verification)。恢复点标识与保留策略由维护者持有，不入 Git。完整恢复演练 NOT_RUN。
- 最近验收：[#208 收尾](https://github.com/Notyet1307/Exposure-Agent/issues/208#issuecomment-5616760776)、[#214 收尾](https://github.com/Notyet1307/Exposure-Agent/issues/214#issuecomment-5615721173)、[#221](https://github.com/Notyet1307/Exposure-Agent/issues/221)。

交付等级：本地合成、已知限制。不是生产、真实客户或商业价值验证。

适用至下列任一变化即失效，须按受影响面复验：代码 tree 变化；compose/image 身份变化；秘密或运行配置变化；验收样本变化。

## 能力分级

实现入口默认 [current-state.md](architecture/current-state.md)。无 planned-only 项。

### implemented-with-evidence

**确定性治理（登录、Project、上传、对账、Finding、确定性报告）**
- 动作：Admin/Operator 登录并完成一轮对账与报告阅读
- 输入与预期：授权项目内可见持久事实；权威在 PostgreSQL
- 入口：[current-state.md](architecture/current-state.md)；启动 [Start and verify](../deployment.md#start-and-verify)
- 证据：关闭 Issue 沿用既有产品面，本回执不重验
- 局限：本回执不把历史产品面重报为新验收

**业务优先阅读与长 ID**
- 动作：治理人员按 IP/发现类型阅读；按需展开完整 ID
- 输入与预期：主视图不被长 UUID 撑开；完整值可复制
- 入口：[current-state.md](architecture/current-state.md)
- 证据：[#208](https://github.com/Notyet1307/Exposure-Agent/issues/208)、[#214 收尾](https://github.com/Notyet1307/Exposure-Agent/issues/214#issuecomment-5615721173)
- 局限：本地合成

**单资产 AI 核查与追问**
- 动作：Operator 在资产或发现详情手动发起核查并追问
- 输入与预期：固定 Project/Resource/已发布 Run；真实 Pi 调用白名单工具；引用可定位；失败保留
- 入口：[current-state.md](architecture/current-state.md)；运行 [Local synthetic single-asset investigation](../deployment.md#local-synthetic-single-asset-investigation)
- 证据：[#214 收尾](https://github.com/Notyet1307/Exposure-Agent/issues/214#issuecomment-5615721173)、[#208 收尾](https://github.com/Notyet1307/Exposure-Agent/issues/208#issuecomment-5616760776)
- 局限：120s 超时与必需工具未调用失败保留；追问轮数/工具/材料/输出预算极限 NOT_RUN

**人工记录与后续验证**
- 动作：Operator 保存结论；后续对账显示已解决/未解决/证据不足
- 输入与预期：记录不关闭 Finding；新失败不抹去旧成功验证
- 入口：[current-state.md](architecture/current-state.md)
- 证据：[#214 收尾](https://github.com/Notyet1307/Exposure-Agent/issues/214#issuecomment-5615721173)
- 局限：验证不证明人工解释全文正确

**分析报告生成/编辑/确认（含 #220 可读性、#221 样例归属）**
- 动作：Operator 手动生成、编辑、确认；新材料只提示
- 输入与预期：原稿与确认版保留；新草稿不自动确认；正文按资产区分历史
- 入口：[current-state.md](architecture/current-state.md)；运行 [Fixed-Run AI analysis reports](../deployment.md#fixed-run-ai-analysis-reports)
- 证据：[#214 收尾](https://github.com/Notyet1307/Exposure-Agent/issues/214#issuecomment-5615721173)、[#221](https://github.com/Notyet1307/Exposure-Agent/issues/221)、[#208 收尾](https://github.com/Notyet1307/Exposure-Agent/issues/208#issuecomment-5616760776)
- 局限：#221 为该复现样例+提示词；草稿须人工复核

### partial

**Viewer / 隔离 / 空失败 / 长 ID / 窄屏 / 键盘 / 双语**
- 动作：Viewer 只读；窄屏与键盘阅读；空/失败/超长输入
- 输入与预期：无模型触发、无写入；基础空失败与中英界面可用
- 入口：[current-state.md](architecture/current-state.md)
- 证据：[#214](https://github.com/Notyet1307/Exposure-Agent/issues/214) 正文 AC7 未勾选及收尾评论
- 局限：部分 UI 已测；真实 AI 极限场景 NOT_RUN

**完整备份恢复演练**
- 动作：按 Runbook 从同一恢复点恢复四处持久状态
- 输入与预期：恢复后契约复核通过，数据仍在
- 入口：[Persistent state](../deployment.md#persistent-state)、[Coordinated backup](../deployment.md#coordinated-backup)、[Restore and verification](../deployment.md#restore-and-verification)
- 证据：[#214 收尾](https://github.com/Notyet1307/Exposure-Agent/issues/214#issuecomment-5615721173) 记录已有恢复点
- 局限：演练 NOT_RUN；恢复点标识由维护者持有

### behavior-exists-correctness-unconfirmed

**AI 草稿语义**
- 动作：阅读生成正文并对照权威事实
- 输入与预期：引用合法且按资产归属历史
- 入口：[Fixed-Run AI analysis reports](../deployment.md#fixed-run-ai-analysis-reports)
- 证据：[#221](https://github.com/Notyet1307/Exposure-Agent/issues/221) 该样例通过；引用检查见 #214
- 局限：有引用 ≠ 语义普遍正确；非未来模型机械保证

## 明确非目标

生产验收、真实客户数据、自动处置、既有 XLSX 兼容缺陷修复：未批准、不在范围内，不是 planned-only。

## 已测 / 未测

已测指针见上列关闭评论。口径：本地合成完成，保留限制，不得改写为全部 PASS。

NOT_RUN：部分 AI 追问轮数/工具/材料/输出预算极限；完整恢复演练。未测不得计通过。

环境事实（Grok、300 秒、300 个合成 IP）见 [Spec](specs/asset-governance-release-1.md)，不是能力承诺。

## 设计三状态

- 已批准：当前 Spec 与 [current-scope](product/current-scope.md) 的已批准栏。
- 推荐：产品定位讨论，未批准。
- 待验证：价值假设（能否降低重复对账成本、人员是否持续使用）。
