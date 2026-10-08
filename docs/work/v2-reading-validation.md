# V2 阅读修复：本地阶段 A 回执

日期2026-10-08，任务[#297](https://github.com/Notyet1307/Exposure-Agent/issues/297)，固定[Spec@1c42406](https://github.com/Notyet1307/Exposure-Agent/blob/1c42406d6d4b83b8bad8d54a24ec2e40954abb98/docs/specs/v2-ai-interpretation.md)。独立工作树`exposure-v2-ai`，分支`codex/v2-interpretation-implementation`。本地候选提交由本文件所在Git提交固定；不宣称已远端发布或部署。

## 改动与结果

| 项 | 结果与证据 |
| --- | --- |
| A-01 | PASS：辅证错误优先于无binding，403明确拒读，500/超时明确失败；错误停止自动轮询，显式GET重读原身份，成功才固定ID/none；核心继续可读。组件及真实PG/API/浏览器三故障注入/恢复均通过，浏览写请求0 |
| A-02 | PASS：IP/port各自固定入口，真实R1使用IP-v1/port-v1，随后port-v2发布但入口仍v1；往返保留result/binding/分类/页码/IP/排序/地址/依据页，共用同项目返回合同 |
| A-03 | PASS：复用客户字段/值和云图RecordFields，原始JSON保留在技术详情；0、缺失、HTML文本不变成执行内容；客户声明/云图观测/NetFlow/限制来源分组。深链地址不在当前页时仍读取自身固定N，不误称无匹配。1366/1920/390、明暗、双语、键盘详情开关/焦点和无整页溢出通过 |
| A-04 | PASS：既有部署级AI设置移至系统管理入口，原Admin管理/普通用户状态读取保持；固定V2页复用AiModelStatus，未配置仍可读事实且0模型POST。报告按钮/材料就绪细分按B合同后续验收，A不引入必失败按钮 |

受影响文件：CoreComparisonResults、ExternalAssets的RecordFields导出/窄字段prop、Sidebar、抽取旧客户FIELDS/值展示的CustomerRecordFields及客户台账消费者；新增组件回归和真实只读业务回归。无后端/API/Schema、生成客户端、来源同步、模型调用或旧Run/报告改动。

## 验证

- PASS：`bun run build`、受影响七文件Biome检查、`git diff --check`、`python3 scripts/check-context-hygiene.py`。
- PASS：`bunx playwright test tests/core-reading.component.spec.ts --project=component`，6项；既有netflow-correlation组件48项也通过。
- PASS：独立PostgreSQL18初始化迁移至cp2920000001；`uv run pytest tests/api/routes/test_core_comparisons.py -q`，7项。
- PASS：`tests/core-reading.spec.ts` 在隔离真实API和生产前端build preview上，认证setup及4项业务检查，共5 passed；最后增加1920和键盘的单项复测（含setup）2 passed。真实读取与元数据故障注入区别记录，不冒称实际现场403/500。
- PASS：独立Standards/Spec两轴源码审阅及annotationIps增量复核，无blocker；Impeccable机械检查为空，桌面/移动截图已观察。

隔离环境：仅新`exposure-v2-ai-20261008-db`、主browser库`product_browser_v2_ai_20261008`和单独可丢弃测试库；API127.0.0.1:8026，生产build preview127.0.0.1:5177。临时随机凭据仅0600且Git忽略的环境文件；OctoBus/agent-compose均指向不可用测试目的地，不接触现场Secret/8080/8081。后续B测试不使用browser库的fixture做pytest清理。

受限本地证据：`/Users/yang/.codex/worktrees/exposure-v2-ai-evidence/stage-a-production-browser`三宽度截图、`stage-a-final-browser-output`及构建/设计检查日志；fixture明确标synthetic，R1全集3/共同1/C独有1/A独有1，port-v2不改R1。

## 失败与纠正

首次F1组件测试误拦截`/supplements/current`，实际GET为`/supplements`；先前3次FAIL实际是无有效DTO导致的读取失败，不能作为500/403/超时复现。原记录保留在`first-reading-baseline`，纠正测试路径/真实NOT_PROVIDED状态并断言故障handler确已执行后，在未改5c46d44的git archive重跑4项FAIL，再在修复候选通过。纠正基线及原FAIL文件hash保存在`corrected-reading-baseline/manifest.json`。

另保留实施期失败：基线archive首次node_modules链接指向workspace中不存在的frontend层，改为根workspace的已安装依赖；隔离初始化使用保留域`.test`邮箱被EmailStr拒绝，改合成`example.com`且未改校验；实时浏览器测试使用不存在的语言值`zh`超时，改真实`zh-CN`后通过。均未降低原断言/边界，也不是产品缺陷已修复的额外宣称。

NOT_RUN：完整后端全仓测试（A未改后端）、真实模型/来源、业务源码远端CI/PR/merge、正式部署、客户业务验收。Issue保持OPEN，A本地验收使B可继续，不表示发布或关闭已授权。
