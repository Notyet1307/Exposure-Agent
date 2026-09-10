# Skill 与方法

复用现有入口：领域阅读见 [domain.md](domain.md)；任务状态与 GitHub 关系见 [issue-tracker.md](issue-tracker.md)。

## 方法

默认使用当前 OMP 原生工具与 GitHub 原生 Issue/PR/CI。`/to-spec` 与 `/to-tickets` 仍可作为方法使用。[delivery-gate.md](delivery-gate.md) 是历史说明，不是当前入口，也不自动授权实施。不要恢复 Controller、Release Graph 或 ready-label 自动授权。

## 默认动作

当前会话覆盖已确认 Issue 的修改与验证。远端 push、PR、merge、关闭须用户明确授权。同一候选同一时间只有一个源码写入者；只读核对可并行。

## 记忆

仓库正式文档优先于 OMP 记忆。记忆可作线索，不恢复授权、不覆盖批准 Spec，也不证明运行结果。`memory.backend` 数据策略未决定。项目 `.omp/config.yml` 请求 `autolearn.enabled: false` 与 `autoContinue: false`；相对全局配置的实际优先级尚未用 OMP 18.1.15 原生读取核验，不把该文件当作已生效策略，也不把某次会话的 CLI 覆盖写成项目策略。
