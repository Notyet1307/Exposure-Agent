# 工作区样式与比对依据验收

2026-10-13，本任务跟踪于 [#306](https://github.com/Notyet1307/Exposure-Agent/issues/306)。维护者已批准本地视觉方向，要求同步其他页面，并明确授权提交、push/PR、必要 CI/Review 后正常 merge；部署仍为独立阶段，本次不执行。

## 固定范围

- 整合基线为 main `4e61fb41ca33dc784d44da4b09cff1a89506b528`（PR #305）；前端候选为 `494c3ec`。
- 行为沿用 [产品收敛 V2 @b603b45](https://github.com/Notyet1307/Exposure-Agent/blob/b603b45c853de764e47f99ccd1ed3ba98dec7c7e/docs/specs/product-logic-convergence-v2.md)、[V2 阅读/AI @1c42406](https://github.com/Notyet1307/Exposure-Agent/blob/1c42406d6d4b83b8bad8d54a24ec2e40954abb98/docs/specs/v2-ai-interpretation.md) 和 [NetFlow bulk @ee61c8c](https://github.com/Notyet1307/Exposure-Agent/blob/ee61c8ce4249a2390d38a065c8cbbbec2be90e1d/docs/specs/netflow-bulk-v1.md)。
- 统一工作区导航、标题、表格、卡片和控件样式；比对优先展示记录表，固定地址依据使用非模态右侧面板。云图、客户台账、NetFlow、数据接入、AI 设置、用户管理与历史运行使用同一套基础样式。
- 不变更后端、API、权威统计、权限、固定版本、期限、配置、调度或模型调用。保留 WIP、历史结果及其他工作树。

## 验证

| 检查 | 结果与边界 |
| --- | --- |
| 前端类型检查与生产构建 | PASS：`cd frontend && bun run build` |
| 本次文件 Biome / patch whitespace | PASS；未对无关文件执行自动修复 |
| 上下文检查 | PASS：`python3 scripts/check-context-hygiene.py` |
| 整合后的组件回归 | PASS：生产预览、单 worker，285 passed / 0 failed，4.9 分钟；使用合成 API fixture |
| 新增阅读检查 | PASS：右侧面板、列表交互、关闭/深链焦点恢复、长 IPv6、1440/1024/390 宽度、筛选空态恢复、服务端排序及固定 URL |
| 其他页面视觉/可访问性 | PASS：数据接入和 AI 设置的中英文、明暗主题、390/1366/1920 布局及键盘；现有组件用例覆盖其余阅读路径 |
| main 兼容检查 | PASS：比对和 NetFlow 的渲染前业务逻辑与新 main 一致（仅新增表格焦点 ref）；保留 access 身份核验、拒读清缓存、游标、原始记录及两处去重记录口径 |
| Standards 独立审阅 | PASS：无代码 blocker；按钮行高与链接可辨识性问题已修复，重审通过 |
| Spec 独立审阅 | PASS：固定材料、核心/辅证边界、AI 显式入口与 PR #305 行为保持；审阅时的 rebase 索引待解决状态已通过正常 add/continue 关闭 |
| 远端 CI / merge | 以 #306 及关联 PR 的实时结果为准，不由本地通过替代 |
| 部署、真实来源/模型与客户验收 | NOT_RUN：本轮源码发布范围不包含这些阶段 |

初始旧基线开发服务全量组件检查为 280/284，通过生产构建串行复测解决其余 4 项；未删失败证据、降低阈值或改变产品行为换取通过。上表 285 项是整合 PR #305 后的全量新运行。

本地实现和检查均在独立 `codex/comparison-attio` 工作树完成。原 8081 实例、后端服务和数据不因源码合并而更新。
