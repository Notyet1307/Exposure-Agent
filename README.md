# Exposure-Agent

面向多源资产数据的资产一致性治理与风险发现处置平台。

当前仓库处于架构设计阶段。已经确认的商业版功能架构、数据流转、技术栈、运行边界和实施顺序见：

[功能架构与数据流转架构 v0.1](docs/architecture/commercial-function-and-data-architecture-v0.1.md)

## v0.1 定位

```text
客户系统与云图
→ OctoBus
→ 确定性资产和风险治理
→ Finding / Evidence
→ 受限 PI 报告 Agent
→ 审核、处置和复测
```

核心原则：

- PostgreSQL 是业务事实库；
- agent-compose 负责定时、触发和隔离执行；
- OctoBus 负责外部系统能力接入；
- Python、SQL 和 Polars 负责确定性数据处理；
- Agent 只基于有界 Evidence 生成结构化报告草稿；
- 真实动作必须经过审批、计划 Hash 和幂等控制。

## 当前内容

本仓库只包含商业版设计，不包含临时 Demo 代码、客户数据、运行产物或研究参考材料。

