# ADR-0025：受限 AI 报告的固定 V2 材料

状态：候选，未接受。批准前不得用本文件扩大现有模型材料权限。准确行为与验收见 [V2 AI Spec 候选](../specs/v2-ai-interpretation.md)。

## 问题与现有边界

ADR-0015 的分析报告固定 GovernanceRun；现有 AnalysisReport 外键、材料读取与许可 manifest 均带 run_id。V2 CoreComparisonResult 是独立发布身份，其 NetFlow 是具有独立截止/撤权的可选绑定。伪造 Run 或只在旧 material JSON 填 result_id 会绕过范围约束；把辅证解释复制到长寿命 AI 摘要会绕过 ADR-0024 的读取期限。

## 拟议窄决定

1. 只为显式 V2 解读报告及随后当前地址解释增加 `core_comparison_v2` subject；同一 AnalysisReport 生命周期可通过判别列/排他约束/同范围外键扩展，旧 run_id 请求与历史不变。PostgreSQL 仍是唯一业务事实库，agent-compose 仍负责隔离/Session，Pi 仍是既有受限执行器。

   现有 `protect_analysis_report()`按subject分支：governance_run保留完全相同的已发布GovernanceRun检查；V2分支以同tenant/project的已发布CoreComparisonResult及确切绑定关系检查承接，并由应用reader逐次复核权限、期限、完整性。不删除/放宽旧检查、不可变材料、状态/预算/确认保护，不回写旧材料。
2. 新材料固定 core result、明确 binding ID 或 null、可选确切 address_key、audience/language、合同/模板、连接版本、内容 hash 与预算。服务端使用现有 reader 验证固定材料，模型只能读有界投影及程序统计/受控引用，不接触原始 Artifact、数据库、自由 SQL/文件/URL 或当前最新资料。
3. 默认生产仅沿 ADR-0006/0007/0017 的既有私网目标与资格、代理、安全版本绑定保护；新增的是 V2 业务材料 subject，不增加目标/Provider、自动重试或 fallback。V2 合成许可 manifest 必须区分 subject 与精确 hash/来源/绑定，旧 Run 项不能匹配 V2。ADR-0015 的公网合成例外不自动扩展至新 subject，当前远端模型调用未获授权。
4. 控制面、模型代理、工具、保存、恢复及所有报告消费均重新鉴权、期限和完整性。含辅证报告在绑定到期/撤权时整份 AI 原稿/修订/摘要/打印拒读；C+A 核心继续。新仅 C+A 报告需新显式请求，不静默删辅证或改确认版；旧 transcript 不得延长读取范围，无法证明安全失效则阻断含辅证执行。
5. V2 新输出结构化 sections/分类型 claims/priority cases。权威数值/分类/版本/时间由固定 fact refs 确定性渲染，模型提供非权威解释与核实建议。引用校验不等于语义证明；高影响断言须人工核实，原稿/修订/确认留存且不修改 Finding/核心结果。

## 保留与非目标

ADR-0015 的旧 Run 材料与公网合成许可、ADR-0017 连接版本、ADR-0024 核心/辅证独立读取、旧 V1 失败封闭继续。没有第二调度器、事实库、通用工具、多 Agent、浏览器/shell Agent、Durable、新外部能力、来源同步、扫描、写回、90天TTL/清理、期限延长或历史迁移。

本轮隔离验证仅使用非客户合成数据、本地固定响应 Provider 和临时凭据；本地真实 Pi/控制面执行证明路径和身份，不证明真实模型语义。保存/配置能力、代码发布、上线与客户材料调用各自验收，不因本 ADR 批准而自动授权。

## 取舍

复用报告生命周期和单表可保留模型绑定、幂等、编辑/确认及审计；代价是必须更新全部以 run_id 查询/鉴权/恢复的调用方和新增受约束迁移。选择混合报告整体拒读降低依赖分离复杂度，但辅证失效后需明确重生成仅 C+A 版本。未经证明的段落依赖拆分和 transcript 缓存复用不实施。

批准须固定本 ADR 与 Spec 的真实 commit，并由新 Issue 记录任务、授权及依赖；不得借已关闭 #292 扩大新 AI 功能。
