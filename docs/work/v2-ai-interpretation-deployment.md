# V2 AI 解读：8081 交付回执

2026-10-09，按维护者已明确授权完成正常源码发布、必需CI/独立审阅后合并、既有8081备份/实际恢复/追加迁移/上线验收。固定行为仍为 `docs/specs/v2-ai-interpretation.md` / ADR-0025 @ `1c42406`；本轮只关闭 #297/#298/#299，不改变 #279/#281/#287 的范围或状态。

## 发布与运行身份

源码 [PR #300](https://github.com/Notyet1307/Exposure-Agent/pull/300) 正常合并为 `7dadbbb12dd254eb80ef5f1487930463242dec55`，树与经检查head `2c40710` 一致。原生Ruleset四项必需CI（backend、Playwright、Compose、lint/typecheck）全通过，无admin bypass；Standards/批准Spec与黄金集业务审阅见[验证回执](v2-ai-interpretation-validation.md)。

| 正式镜像 | Image ID |
| --- | --- |
| `exposure-v2-ai-backend:7dadbbb12dd254eb80ef5f1487930463242dec55` | `sha256:7e2f979ef161ee16c7879b3ad27e504dcc258964ad359cb695f2c1f9f776e0b7` |
| `exposure-v2-ai-frontend:7dadbbb12dd254eb80ef5f1487930463242dec55` | `sha256:fd8001b1e30c021758931e441ebc64cffb11a3c09a3c6c2fc7056a6818455e69` |
| `exposure-local-280-runner:7dadbbb12dd254eb80ef5f1487930463242dec55` | `sha256:4a85dfdf6341d54b37b57f14540e53751765d676d5376d95a81410a72081b4bf` |

三镜像从合并提交独立git archive构建，OCI revision同该SHA；实际backend/frontend容器ID对应镜像，runner内build文件同SHA。正式Compose项目仍为 `exposure-real-280`，loopback8081；8080独立实例与其他容器保持。

## 数据保护与恢复

**PASS**：暂停入口，确认业务任务终态、launch reservation零和20个原Session stopped，再停止backend/OctoBus/controller写入者；DB保持在线进行一致性逻辑dump。恢复集 `before-v2-ai-20261009` 保存在原运行目录 `backups/`，AES-256-GCM加密，密钥独立目录且600。捕获DB、Artifact、OctoBus、controller volume/host以及部署配置。

**PASS**：实际恢复54张表及四份文件存储；逐表原字段行数/内容hash、逐文件字节hash/mode/uid/gid完全一致。恢复出的OctoBus在network none实际启动，5个service、17个instance、17个capset完整库存一致，未执行真实上游方法。

**PASS**：先在恢复库演练，再通过正式原生prestart从 `cp2920000001` 追加 `ai2980000001`；53张原业务表原字段行/内容hash不变，正式阅读验收后再次核对仍一致。全部原Artifact文件内容及权限/归属不变，无回填、重算、旧Run/报告修改、期限扩展或清理。

**PASS**：原controller project和20个历史Session完整身份/状态不变；7个现有agent的当前镜像更新为本次SHA，模型identity仍原值。endpoint/Secret/config与全部模型/来源例外开关保持原值，仅三项runner build version更新。原镜像和历史version不删除。

原 `start.sh` / `stop.sh` 持久化追加本次release overlay，并已实际执行start；DB/backend/OctoBus/controller/frontend healthy，prestart、package/project init、runner image init均退出0。正式OctoBus的instance/capset与service定义保持；原生package import仅刷新5个service的UpdatedAt元数据，不等于来源同步。

## 正式阅读验收

**PASS**：live/ready health、登录及12项HTTP读取；实际浏览器读取比对、客户台账、云图、NetFlow、统一接入5页，无页面异常/失败API/整页横向溢出，浏览业务写请求0。正式固定V2就绪与报告列表额外只读核对通过。

**真实状态**：当前正式模型连接 `NOT_CONFIGURED`、`can_create=false`，当前范围报告数0。界面准确禁用生成，并提供既有系统模型设置入口；未把隔离Provider/黄金稿写入正式项目，也未代管理员保存/验证/启用模型。接入获准的合格模型后才能在正式实例实际生成报告。

本地真实PG/API/浏览器写主线、Pi/本地Provider、N撤销/到期与cache清除已独立PASS；不将正式只读冒烟当作真实模型或客户业务写入验收。既有客户登记保留原模拟属性，真实外部模型语义/token/费用、客户材料出域、来源同步/扫描/写回均NOT_RUN。

运行根：`/Users/yang/.local/share/exposure-agent/real-280-f246b36/`；受限部署证据：`/Users/yang/.codex/worktrees/exposure-v2-ai-evidence/deployment/`。包含backup manifest、恢复/迁移证明、historical/artifact/session/source/config核对、正式browser与模型就绪回执。私有配置、源数据和截图不进Git。

## 恢复与关闭边界

恢复集、独立验证库/卷及旧镜像保留；不直接schema downgrade或单独更换旧镜像。出问题先冻结写入，优先前滚；确需恢复时按同一恢复集整体恢复DB、文件、OctoBus/controller和匹配配置。

#297/#298/#299 已满足源码合并与要求的部署验收，维护者已授权关闭；实际关闭状态及回执以GitHub Issue为准。文档回执后续main SHA与业务运行SHA分开，不把docs-only更新说成再次部署。
