# EXP-3SRC-UX-01A 本地验证记录

任务：[GitHub #284](https://github.com/Notyet1307/Exposure-Agent/issues/284)。行为依据：[三源工作台 U1/U2/U6 @c15be89](https://github.com/Notyet1307/Exposure-Agent/blob/c15be890eac8bf5044b891c9feccfa3ce7da6f68/docs/specs/three-source-workbench-v1.md)。本记录不替代 Issue 的任务状态、依赖或授权。

## 候选范围

从本地集成基线 `57a6cc0d408ffed1b8e085bc123a0d1da89ffdf0` 实现结论优先的结果页、服务端固定批次共同/差异统计与分页筛选，以及逐条三源状态、端口材料、依据和已有复核任务入口。保留应用壳层、固定 URL、权限、输入与历史结果。没有 Schema 迁移、模型或新来源调用。

完整封存 NetFlow 的网络覆盖未知不抹去本批 IP 记录。读取失败、部分覆盖、单源或未确认空间的共同/差异数为不可用；旧交集字段也受同一门禁保护。合法空与未提供分别保留。

## 当前证据

以下为候选提交前的本地结果；全栈验收必须引用随后固定的干净提交。

| 检查 | 结果 | 说明 |
|---|---|---|
| 相关后端 API | PASS | 30 项，覆盖七种来源组合、38 地址/37 差异的 25+12 分页、共同记录、正常两源、单源、合法空、失败、覆盖不足、固定输入及其他协议编号 |
| 后端 lint/typecheck | PASS | Ruff、Mypy 219 个文件、ty；未降低门禁 |
| 前端 lint/正式 build | PASS | 使用仓库 `bun run build` 的正式 TypeScript 配置 |
| 比对页组件 | PASS | 37 项；另复验依据按钮的键盘焦点 |
| 全量前端组件 | PASS | 正式构建预览、单 worker：244 项通过 |
| 全量后端 | 执行中 | 已在本任务隔离 PostgreSQL 中启动，完整结果待回收，尚未据此宣称通过 |
| Standards 独立审阅 | PASS | 无 blocker；大部分页面 diff 为把既有输入区移到结果之后 |
| Spec 独立审阅 | PASS | 修复“受限来源仍有旧交集数字”问题后复审通过 |
| 隔离真实 API/worker/浏览器主线 | NOT_RUN | 已扩展既有 harness，等待干净候选提交 |
| 真实客户三源业务复验 | NOT_RUN | 当前真实项目仍无客户上传；合成资料不能代替客户验收 |

开发服务器并行全量前端首跑为 242 通过、2 失败（一项交互耗时、一项导航详情未出现）。两个失败项在正式构建上单独复验通过，随后正式构建完整 244 项通过。保留首跑失败记录，不把它改写为通过。

额外执行的裸 `tsc --noEmit` 会把既有测试目录纳入旧语言库配置，报出 `Promise.withResolvers`、`at` 及已有测试类型问题；此命令不是仓库正式 build。没有为本任务修改无关测试或 TypeScript 配置。Biome 的已有配置版本提示仅为 informational。

本机证据目录：`/Users/yang/.local/share/exposure-agent/three-source-workbench-20261004/`。测试使用任务专属 loopback PostgreSQL 与 Artifact 根；未接入真实数据。该目录的环境文件含测试凭据，不提交或转发。

## 完成边界

本任务当前仅本地实现与验证。业务源码 push/PR/merge、真实迁移部署、清理、新增真实来源/模型调用以及 Issue 关闭均未执行。#285/#287 的依赖状态以 GitHub 为准；#286 为独立实施任务，不由本记录宣布完成。
