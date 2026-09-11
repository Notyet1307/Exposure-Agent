# 当前工作

- 批准 Spec：[asset-governance-release-1.md](../specs/asset-governance-release-1.md)
- 正式任务：[Notyet1307/Exposure-Agent#228](https://github.com/Notyet1307/Exposure-Agent/issues/228) — S1 概览核查入口与固定批次资产阅读优化
- 固定 Spec：远端 #228 仍引用 [5ec88115742fca722b7de788520c8eeb482cc29e](https://github.com/Notyet1307/Exposure-Agent/blob/5ec88115742fca722b7de788520c8eeb482cc29e/docs/specs/asset-governance-release-1.md)；维护者在修正会话另行批准的新核查中文业务表述补充，以本地候选 commit 中的同路径 Spec 为准，尚未获准更新远端指针。
- 范围：[current-scope.md](../product/current-scope.md)
- 接管：以 #228 的候选 PR、逐 AC 记录及下一会话独立验收入口为准
- 权威：[ADR-0016](../adr/0016-pin-approved-spec-and-issue-status.md)
- 最近验收：[#225 B0](https://github.com/Notyet1307/Exposure-Agent/issues/225)，不代替 S1 独立业务验收
- 当前：原候选 `68a54279c2e355a541ee0cd8f62182d1cec66c3e` 的独立验收发现 NetFlow 默认身份、报告原始材料/哈希、隐藏文件输入溢出及图滚动检查问题；已在 #228 范围修正。四 worker 组件检查 120 项及图滚动重复 20 次通过，不代替业务验收。
- 补充阻断：候选 `88f576a5a0476f8f52766aa7fa204c6bd3553160` 独立验收 AC1/2/3/5/6 通过、AC4 未通过；来源管理 API 仅返回短指纹，且空 CloudAtlas 查询结果中的完整 `fingerprint` 未折叠。两项已在 #228 修正，旧候选结果不回填为 PASS。
- 验收口径：固定修正候选 SHA，由未参与实现的验收者逐项复验 AC1–AC6，结果以该 SHA 的独立证据为准；新核查中文指令使用真实新结果验证，历史原文不得回写或正则删改。两轴代码审阅与独立业务验收分别记录。
- 本轮授权例外：维护者明确批准隔离 Viewer、隔离人工记录/新报告、B0 两资产核查与固定追问、临时精确合成材料及两个固定资产的合成只读查询 Hash 许可、仅新核查指令和 build 身份变化的本地执行器验证，并另行批准来源完整指纹读取合同的临时后端验证。模型、预算、认证、DNS/出域与引用校验保持不变；不安装依赖、不改数据库 Schema，验收后恢复原白名单、执行器绑定及后端镜像，不覆盖 B0 历史事实、人工记录或确认报告。
- 停止：只准备本地候选与证据，不 push、不 merge、不作正式部署、不关闭 Issue、不改远端验收勾选；临时验证外不替换后端/前端应用镜像，不扩为 S2/S3 或整站重构。未通过或未运行的业务验收不得因开发检查通过而改记 PASS。
