# ADR-0016：Git 固定 Spec 为行为权威，Issue 只承载任务状态

状态：已接受

范围依据：[GitHub Issue #223](https://github.com/Notyet1307/Exposure-Agent/issues/223) 批准的治理迁移。本 ADR 只固定规格与任务表面的分工，以及独立验收的记录规则。不新增产品或架构决定，不修改已接受的业务边界。

## 决策

Git 中已批准且固定版本的 Spec 定义行为预期。GitHub Issue 是唯一任务状态、依赖与授权表面，必须引用该 Spec 的路径与 commit。Issue 可以细化验收操作，不得静默改变 Spec 的业务含义；改变预期须先更新并批准 Spec，注明替代关系，再复核受影响任务。

独立业务验收与 Standards/Spec 两轴代码审阅分开。代码审阅不代替业务验收，业务验收也不机械叠加同义代码审阅。每条结果只用 PASS / FAIL / BLOCKED / NOT_RUN。人工风险接受是另一项决策，不能把 FAIL 或 NOT_RUN 改写成 PASS。同一原因连续两轮且无新证据时转入诊断，不无界重试。

仓库 Standards 仍是 `AGENTS.md` 与相关已接受 ADR。历史 Issue/Spec 保留原语义；关闭不等于全部 PASS。

## 限制

本决策不恢复 Controller、Release Graph 或 ready-label 自动授权。`/to-spec` 与 `/to-tickets` 仍可作为方法使用。不授权停用正常 CI、ruleset、agent-compose 或 OctoBus。不把环境参数或价值假设升格为产品承诺。
