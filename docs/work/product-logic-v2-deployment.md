# 产品使用逻辑 V2：8081 上线回执

2026-10-08，维护者在交付会话明确要求“继续 合并 部署 关闭issue 上线”，更新此前仅 push/PR/CI 的边界。本回执覆盖源码 PR #293、客户替换 #285 与产品逻辑收敛 #292；任务状态和关闭回执以对应 GitHub Issue 为准。#279、#281、#287 不纳入。

## 发布身份

- 源码 [PR #293](https://github.com/Notyet1307/Exposure-Agent/pull/293) 正常合并，合并提交 `6f0d5eaa3c7b9746141bdeff9ec8420768401d94`，未绕过分支保护。其树与通过检查的 head `6d19112b594e0026df6561952667888292715006` 一致。
- 四项必需 CI 全部通过。远端后端 1457 passed、coverage 90%；浏览器 307 passed、8 项按配置跳过；Compose、lint/typecheck 均通过。独立 Standards/Spec 审阅及20项隔离合成业务验收见 [实施验证](product-logic-v2-validation.md)。
- 构建来自合并提交的独立 `git archive`，不使用原主工作树 WIP。8081 对应现有 Compose 项目 `exposure-real-280`；8080 的独立环境未改动。
- 前端、后端和治理/CloudSync/NetFlow Runner 均采用该合并提交。镜像 ID 如下，均带同一 OCI revision；Runner 内 `/app/runner-build-version` 亦为该提交。

| 镜像 | Image ID |
|---|---|
| `exposure-product-logic-backend:6f0d5eaa3c7b9746141bdeff9ec8420768401d94` | `sha256:9b1b954d5978fa9379a7322b70733a021698c24a72e1a255f469652bc980cd1e` |
| `exposure-product-logic-frontend:6f0d5eaa3c7b9746141bdeff9ec8420768401d94` | `sha256:4fd0cfce48c130329d04087d0065c84a103c08d30231cf50b92be3e373802ea4` |
| `exposure-local-280-runner:6f0d5eaa3c7b9746141bdeff9ec8420768401d94` | `sha256:fabd3cf9c673c1caa5244d84dc3b1b784397c8e5150c495cd76d4cf12fc6f647` |

## 备份、迁移和运行时

**PASS**：先暂停8081入口、确认无在途任务及 launch reservation，再停止 backend、OctoBus、agent-compose 写入者。现存20个 Session 全为 stopped；该实例没有历史 GovernanceRun，因而没有旧失败 Run 的 Retry 版本冲突。

恢复集 `before-product-logic-20261008T0845Z` 位于现有运行目录 `backups/` 下，以 AES-256-GCM 加密；密钥分开保存且权限600。备份包括一致性 PostgreSQL dump、Artifact 目录、OctoBus 卷、controller 卷及 host 数据、部署配置。数据库逻辑备份期间保持在线，所有应用写入者已停止。

**PASS**：在无外部网络的隔离恢复容器中实际恢复51张表，逐表行数与全部原字段内容哈希一致；四份文件存储恢复后逐项核对文件哈希、mode、uid/gid。恢复出的 OctoBus 实际启动，5个 service、17个 instance、17个 capset 的完整库存与正式实例一致。不是仅检查备份目录或 `pg_restore --list`。

**PASS**：先在恢复库演练，再对正式库运行原生 prestart。迁移从 `ca2810000001` 追加 `f1a2b3c4d5e6`、`cb2920000001`、`cp2920000001`。50张历史业务表的原字段内容哈希保持不变；18份 Artifact 的文件字节数与SHA256在切换后再次匹配。没有回填或改写旧V1结果、Analysis、发布版本及保留期限。

**PASS**：同一 controller project、20个历史 Session 保持；仅治理、CloudSync、NetFlow 三个 agent 镜像更新。四个模型 agent 保持原 `f246b361d92fa298a1f9ac35b7a11db085b69c2c` 镜像，模型 endpoint/identity/config、runtime digest 及全部模型开关未改。模板和渲染器与上一运行版本字节一致，仅治理 build version 通过 overlay 更新。

**PASS**：现有 `start.sh`/`stop.sh` 持久化追加本次 release overlay；实际重新执行持久化 start 命令成功。backend、DB、OctoBus、controller healthy；前端正常运行；prestart、package/project init、runner image init 正常退出0。Named volumes、Artifact host path、project identity、8081 loopback ingress及原显式生产 overlays 保留。

## 上线后的阅读验收

2026-10-08 16:51 CST，使用正式8081实例及现有数据完成：

- **PASS**：登录页、live/ready health，以及用户、项目、核心 current/readiness/history、客户台账、云图来源、NetFlow current/固定 Analysis，共12项HTTP读取检查；另验证实际登录成功。
- **PASS**：真实浏览器访问比对结果、客户资产台账、云图资产、NetFlow观测、统一数据接入5个页面；无页面异常、失败API或整页横向溢出；浏览过程业务写请求为0。
- **PASS**：NetFlow裸入口由服务端定位原成功Analysis并固定URL，显示原964条观测、946个不同来源IP。999条原始行、未知观测窗口及原warning语义保持。
- **PASS**：17个已启用 SourceInstance 的实例和capset均存在，数据库SourceInstance指纹保持不变。没有借部署触发新的云图读取或同步。
- **预期状态**：正式项目尚无新合同 C+A publication，current 返回 `NO_RESULT`，readiness 返回 `SCOPE_REQUIRED`。页面要求管理员确认网络空间及可比范围后明确生成；部署没有代替业务范围确认，也没有把旧V1结果静默迁为V2。

冒烟脚本首次按英文默认值和固定等待时间断言，遇到默认中文、实际云图标题以及NetFlow正文尚未返回；依据实际界面设置语言、匹配标题并等待固定Analysis URL后重跑通过。未为此修改产品代码或放宽身份断言。

运行主目录：`/Users/yang/.local/share/exposure-agent/real-280-f246b36/`。受限证据目录：`/Users/yang/.codex/worktrees/product-logic-convergence/evidence/`，包括 `deployed-browser-smoke.json`、5张正式页面截图、`final-container-inventory.json`、`final-historical-table-verification.json`、`controller-identity-verification.json`、`octobus-restore-runtime.json` 和迁移/启动日志。真实数据截图与私有配置不进入Git。

## 边界与恢复

本次未发起新的真实来源同步、NetFlow处理或模型调用；模型资格配置未变，未重跑模型资格请求。客户替换和新C+A生成/辅证操作的完整写入主线由隔离真实PG/API/浏览器验收覆盖，正式实例仅做阅读验收。已有客户登记仍是此前授权的模拟登记，不作为真实客户业务验收。

恢复集及隔离恢复资源保留，不清理原卷、旧镜像、历史输入、结果或用户WIP。出现上线问题时先冻结入口、排空任务；优先修复前滚。不得对已写入新事实的schema直接降级。需要还原时，须停写并按同一恢复集整体恢复数据库、文件、OctoBus、controller及对应部署配置，不能只换旧镜像或只恢复单库。
