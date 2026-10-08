# 待发布 Issue：产品使用逻辑收敛——两源核心结果、当前数据与统一接入

状态：待发布，尚无 Issue 编号。维护者已于2026-10-08批准候选合同及规格发布/建单；正常合并文档后用真实 commit 替换下述占位并发布，再衔接本地实施。本草稿不替代正式 Issue。

## 批准规格（发布前必填）

- `docs/specs/product-logic-convergence-v2.md@<APPROVED_SPEC_COMMIT>`。
- 同版 `docs/adr/0024-core-comparison-and-optional-netflow-evidence.md`。
- 客户全量替换继续由 #285 与 `docs/specs/three-source-workbench-v1.md@c15be890eac8bf5044b891c9feccfa3ce7da6f68` U3负责。

## 结果行为

普通入口读同作用域最新已发布可读的C+A核心结果，并固定结果身份；NetFlow独立默认读当前成功封存结果，仅作为独立可失效的辅证。数据接入统一配置/操作记录，普通阅读无需先选技术版本或启动旧Run。详细行为以固定Spec为准，不在Issue重定义。

实现须具备可判定的常规用途/发布状态/发布时间；NetFlow跨Dataset定位依据明确的采集范围确认，不能由current Dataset推断。实际观测窗口缺失时如实未知。新辅助绑定固定显式有效截止，绑定到期与底层Analysis原规则分开；不伪造#287尚未实现的Analysis TTL。

## 阶段与验收归属

- B：核心三分类、完整全集、服务端默认解析、更新/历史身份；AC-01–05、08–09、12–13。
- C：NetFlow当前列表、独立辅证与旧V1失败封闭；AC-02–03、06–07、10–12。
- D：统一接入与表单、正常准备不进入runs、固定证据返回、#285衔接；AC-14–16。
- E：隔离真实前后端/PostgreSQL/浏览器、双轴独立审阅与交付；全部20项，特别AC-17–20。

#285为客户替换的唯一实现任务，本Issue只集成其当前版本/预览/应用服务并复验AC-15，不重复建相同任务。发布后用GitHub原生依赖表达D/最终验收依赖#285；该依赖不应阻止B/C中可独立验证的固定合法C/A核心工作。#284/#286/#289为已交付复用来源，#290为当前基线；#287不作为依赖或顺手范围。

## Allowed files

现有`backend/app/domain/source_correlations.py`、`netflow_processing.py`、`netflow_reviews.py`、对应API routes/models、必要新增迁移及受影响测试；前端NetflowCorrelation/NetflowResults/ProjectPreparation/Sidebar/WorkspaceSelector/Logo/ExternalAssets、根页/相应路由、共用表单及受影响测试；仓库生成工具产出的client/routeTree；本Spec/ADR/current与必要交付记录。#285客户preview/apply模块与测试只以#285归属修改。扩散到无关模块前重新界定范围。

## 验证和停止线

真实隔离合成主线＋逐项PASS/FAIL/BLOCKED/NOT_RUN，明确失败与复测；组件mock、历史回执不能代替本轮业务验收。完整保留旧V1拒读测试和旧Run/报告/Hash/引用。生成文件只用仓库工具；迁移只追加；同树一个写入者，保留用户WIP。

本票拟授予本地实现、必要依赖安装、隔离合成验证及本地提交。未授予业务源码push/PR/merge、部署/生产迁移、真实来源或模型调用、清理和关闭Issue；不得继承旧任务许可。不新增调度器、扫描/纳管/外部写回/AI功能，不实施#287。批准固定合同、Issue授权或必要外部权限缺失时，仅暂停受影响工作并说明具体门禁。
