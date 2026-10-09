# V2真实模型报告兼容修复回执

2026-10-09，按同一V2交付会话维护者反馈修复管理/运营报告无可读稿的问题。规格仍为 docs/specs/v2-ai-interpretation.md / ADR-0025 @1c42406d6d4b83b8bad8d54a24ec2e40954abb98；跟进#298。源码PR[#302](https://github.com/Notyet1307/Exposure-Agent/pull/302)经四项必需CI及独立Standards/Spec审阅正常合并为`9e99d19601896456c9f6a72b4be82c7d074973b0`。

## 原因与修复

模型上限以token计，应用预算以UTF-8字节计，不能相互替代。实测旧Pi请求为16384输出token；样例正文约7.3KB、思考文本约19.5KB，SDK还在thinkingSignature中携带思考副本。旧计数把该副本计入累计输出，可能提前命中32/64KiB预算。现只去除预算副本中的该重复元数据，真实thinking/text/tool内容、最终stdout与原始请求/传输边界继续有界。

V2提示词现带完整Output JSON Schema、必需六章/四块、声明claim id、counts/address fact、fact/evidence引用闭包和样本约束。新增覆盖范围与禁止派生台账结论的提示。默认资格使用部署实际输出预算，保留旧V1报告检查，并追加固定非客户V2材料与真实V2 validator；V2失败不能记报告能力PASS。仅报告validation lease按两项有界检查调整，业务lease不变。

## 验证与正式运行

PASS：原代码重复预算/缺少完整Schema回归分别复现FAIL；本地1483项后端检查通过；lint/mypy/ty、context hygiene通过。最终head66804a3的backend/Playwright/Compose/lint-typecheck四项必需CI全通过，无admin bypass。独立两轴代码审阅及合成业务审阅分别记录。

PASS：从合并SHA独立archive构建后端与managed runner，OCI revision/build文件相符。8081后端运行新镜像；MODEL_CONNECTION_RUNNER_BUILD_VERSION为9e99d19。默认/旧治理runner与原controller项目仍固定7dadbbb，前端亦保持7dadbbb。无数据库迁移，不重标旧镜像/资格或改写历史。

PASS：配置前停止写入者，加密一致性备份55张表和四份文件存储，实际隔离恢复逐表/逐文件内容与权限归属匹配；恢复的两条认证密文用独立保管主密钥认证解密成功。新模型连接`19cb28ff-c383-4218-85d2-95d22b9a4469`沿产品原生保存/默认验证/启用；操作`34a48537-94b0-4b59-ac20-a2f0a5c144cf`的qualification/runtime/investigation/analysis_report/analysis_report_v2均PASS，未修改验证命令。模型deepseek-v4-flash、Responses、原Pi百智云Key加密读回匹配。

## 原生可读稿

只使用独立纯合成C+A项目`0634b7d2-b27a-4e1f-b5c4-34f7e1697db3`与固定result`10e037ee-98be-41b3-a862-10dc96958f3a`：3地址，三类各1，无NetFlow。管理/运营分别固定独立audience与material hash许可，不泛化公网或真实项目许可。

- 管理：`df23239a-1a0a-4c5f-9370-9403b27a8940`，原生生成约33.5s，六章DRAFT。AI原稿的一处单向分布矛盾及一处“两侧一致”歧义，经原生PATCH修订为revision3；原AI输出、fact/evidence refs及统计未变，修订作者/时间/历史保留。当前修订稿业务审阅PASS。
- 运营：`955f3863-00cc-4dc3-a226-309498a3e272`，约46.6s，六章DRAFT/revision1，原稿业务审阅PASS。

PASS：实际浏览器分别选择管理/运营、打开六章全文，包含确定性统计、解释/缺口/建议、来源及限制；读取/刷新未新建模型任务。两稿均保留待人工复核，未自动确认。三份旧失败版本原样可读；54张业务表的25680条原记录和20个原Session完整不变。既有真实项目仍因synthetic_material_denied不能向百智云发送材料。

当前报告预算64KiB、时限240s。所有成功为固定三地址纯合成输入的真实模型验收，不代表真实客户业务验收、全面语义正确、资产归属/漏洞/已处置。费用总额NOT_RUN，未调用真实来源、未扩大旧期限/清理历史。完整私有回执与截图在 /Users/yang/.codex/worktrees/exposure-v2-ai-evidence/v2-report-fix-20261009/；主密钥仍独立保管，私有配置/材料/凭据不入Git。
