# 模型连接隔离验收

从仓库根目录运行，先构建当前源码对应的同 tag `backend:<tag>` 与 `governance-runner:<tag>`；Runner 的 build version 必须等于 tag。`MODEL_BACKEND_IMAGE_CONTEXT` 指向本地 JSON（至少包含 `{"tag":"<tag>"}`），冻结清单和构建日志留在仓库外。

```sh
MODEL_BACKEND_IMAGE_CONTEXT=/absolute/path/image-context.json \
EXPUX02_PROBE_ROOT=/absolute/path/private-evidence \
EXPUX02_FAULTS=1 python3 tests/model_connection_backend/run.py
```

默认路径验证真实 PostgreSQL、agent-compose、Pi 与固定本地 Provider 的 A/B 切换；`EXPUX02_FAULTS=1` 增加专属控制面 relay，并验证：

- Key 缺失时接管无写入；重启后按原 key 查询/重放接管；验证 UNKNOWN 的 GET 不启动，显式同 key POST 恢复。
- 已标记合成的历史资格 FAIL：原生 Run 未知时阻止首次启用，确认原生终态后才允许启用，FAIL 记录不改写。该原生命令只验证 Session 生命周期，不执行 legacy 模型。
- relay 在真实 StartAgentRun 成功后丢掉回执，业务同 key 重放仍只有一次 Start。
- 在首个 Provider 请求完成后，以 `docker pause/unpause` 固定专属任务的时序；B 启用、backend 重启后 A 核查仍以原 Run/Sandbox/版本完成。它不是新增产品 ResumeSandbox API。
- A 报告恢复前显式撤销 A，A 的后续调用被拦截，Provider 计数不再增长，B 报告继续成功。
- 主密钥移除后新报告保留 FAILED 且无模型外发；恢复正确密钥后新报告成功，原 FAILED 不改写，生效指针不变。

可选 `MODEL_CONNECTION_BROWSER_URL` 指向本机已启动的生产前端 preview，增加真实 browser→backend 的保存/验证/启用/禁用。浏览器测试只转发 API origin，业务响应未 mock；此项不证明生产 CORS。

所有凭据随机生成，Provider 仅本地固定响应。独立容器/网络/卷/Key 与 Artifact 目录按本次随机前缀创建；异常也只清理本次资源，原容器清单须保持不变。不得把现场凭据、客户材料或共享 runtime 配置用于此脚本。原始日志、快照和环境文件不提交。每次失败保留自己的目录，不覆写为 PASS。

未覆盖：真正外部模型语义；首次 Start 未被接受时的产品重启入口（现有业务 GET/同 key POST 仍只观察）；生产部署/用户体验认可。不能从本测试推断这些通过。
