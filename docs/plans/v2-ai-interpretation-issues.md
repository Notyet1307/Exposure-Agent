# V2 AI 交付任务草稿

状态：本地候选，未发布 Issue。固定 Spec/ADR commit 须在文档正常发布后填入真实 SHA；不得以 HEAD、附件或占位 hash 冒称已批准。维护者已请求完成附件目标，远端建单及规格发布尚需独立许可。现有 #285/#292/#293/#295 已交付，不重新实施；#279/#281/#287 保持其独立归属。

## A：EXP-V2-READING-01

标题：V2 首次辅证失败、分域追溯与业务依据阅读。

批准行为：本候选 Spec §2，A-01–04；保留固定 V2 Spec `docs/specs/product-logic-convergence-v2.md@b603b45c853de764e47f99ccd1ed3ba98dec7c7e` 和 ADR-0024，以及旧来源/连接合同。

范围：F1/F2 先失败复现；最小状态优先级及显式 GET 重试；每域独立固定版本入口与往返上下文；既有业务字段投影/显示；AI设置独立导航和准确状态。A 不依赖模型或 B/C。

Allowed files：`frontend/src/components/CoreComparisonResults.tsx`、Sidebar/已有模型状态和来源字段组件、必要只读状态 DTO、`frontend/src/lib/comparisonReturn.ts` 和同项目返回消费者、相关路由/组件测试、本文档/current 和验证回执。需后端字段投影时仅现有 `comparison_results.py`/`source_correlations.py` 的 reader/public DTO及受影响测试；生成客户端只能用脚本。无 AI材料出域/调用、新配置存储、来源写操作或无关重构。

验收：三故障+显式恢复保留核心且零写；真实隔离 R1 IP-v1/port-v1 后发布 port-v2，往返仍R1及v1；业务字段/缺值/技术依据可读；设置及各状态真实且零自动模型调用；必要 lint/build/回归、Standards/Spec独立审阅。记录真实浏览器与组件 mock区别。

授权：固定规格/正式任务后本地实现、必要依赖、隔离非客户验证及分阶段本地提交。业务 push/PR/merge、部署/迁移、真实来源/模型、清理和关闭分别等待授权。不能借 A 偷渡 B 的新材料边界。

## B：EXP-V2-AI-REPORT-01

标题：固定 V2 结果的 AI 解读报告及同报告摘要。

批准行为：本候选 Spec §3–7、B-01–09 与同版 ADR-0025；旧 `asset-governance-release-1.md` 报告、ADR-0015/0017兼容边界保留。Issue 发布时引用真实固定 commit，不在票中重定义合同。

依赖：A 交付；采用 GitHub 原生 blocked_by/sub-issue 表达。无 NetFlow/GovernanceRun 不是前置；#287/Durable/真实模型许可不作为本地 C+A 切片依赖。含辅证 transcript失效无法证明时仅阻断该扩展并记录，不能降级。

Allowed files：现有 AnalysisReport domain/models/routes、Pi integration及分析报告 runner/受限model proxy和既有材料许可、comparison_results/source_correlations reader最小适配、必要追加迁移、受影响后端测试、AnalysisReportsPanel及V2结果/报告路由和相关UI/缓存/打印/组件与业务测试、生成客户端/routeTree、Spec/ADR/current和验证回执。禁止改旧业务事实算法、来源同步、扫描、Finding写入、控制面调度边界或不相关模块。

验收：固定 subject/null或确切binding/连接版本/hash；单个白名单材料工具；严格V2结构和确定性fact refs；结果→显式生成→摘要/全文→编辑→确认→引用/打印；旧Run兼容；真实隔离PG/API/浏览器及Pi+本地响应Provider分别记账；权限/期限/缓存/会话失效与幂等/CAS/失败/注入/负例；独立业务审阅与双轴代码审阅分开。

授权和停止：仅本地独立合成环境、临时凭据、本地固定响应目的地，不加载生产Secret，不调用真实模型或来源。批准材料合同不等于现场调用许可，测试通过不等于模型语义/客户业务验收。业务远端发布/merge、部署/生产迁移、真实调用、清理/关闭另需明确授权。

## C：EXP-V2-AI-ADDRESS-01

标题：固定 V2 地址的差异解释。

批准行为：本候选 Spec §1/3/4/7、C-01与同版ADR-0025。原生依赖 B；A/B 的交付不等待 C。

Allowed files：B中相同材料 adapter/请求 subject scope/受限 runner及V2地址详情，相关测试、生成客户端和验证回执；不新增单资产自由工具、历史/实时查询、模型目的地或调度器。

验收：只有当前 result+address_key+明确binding/null，分事实/可能解释/缺口/建议；解释NAT/漏登记等不变事实；显式发起、scope隔离、旧版本/期限/撤权/失败及零额外调用。本地合成验证/提交；远端、真实调用及关闭边界与B一致。
