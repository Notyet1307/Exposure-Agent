# Product
<!-- impeccable:product-schema 1 -->

## Platform
web

## Users
客户安全与运维人员查看结果并追溯证据；客户领导先看摘要再进入详情。

## Product Purpose
以客户资产表、CloudAtlas 与可选 NetFlow 的固定输入开展资产治理，提供可追溯的确定性结果。

## Capabilities and Constraints
PostgreSQL 是业务事实源。UNKNOWN 不是不存在或零风险。历史报告与已发布事实不可改写。默认简体中文，保留中英文切换；协议值、ID、Hash 保持原值。

## Product Principles
先读摘要，再进入差异与证据。减少页面长距离滚动。保留关键失败与完整性提示。

## Evidence on Hand
本地合成 Run becdfd4f-fdb4-47cb-90ad-2cf07fe0be8f 已发布 v2：22 IP，20双来源匹配、1仅客户、1仅CloudAtlas；2有NetFlow正向活动，其余未知。这不是客户生产验收。

## Open decisions
本原型仅验证概览、矩阵、血缘的信息布局；最终实现以待确认Issue为准。新报告语言持久化方式待规格明确。
