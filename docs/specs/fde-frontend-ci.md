# FDE 前端 CI 接入

本规格对应维护者 2026-10-30 已批准的 CI 接入开发及 Draft PR。只交付接入，不合并、不部署、不修改已有 TaskGrant，也不实现错误页重试功能。任务状态以引用本文件固定 commit 的 GitHub Issue 为准。

## 行为与范围

- 复用锁定的 Bun、Playwright、现有 `component` 项目及生产构建，不接触业务数据库或来源服务。
- 增加一个静态单 job workflow、无新增运行依赖的 TypeScript 报告适配及针对性测试。
- 保留 `test-backend`、`test-docker-compose`、`test-playwright`、`lint-and-typecheck`，不修改规则集、凭据、执行权限或部署配置。
- 实际测试 checkout 固定为 PR head；CI 程序、测试选择配置和其测试固定在来源 checkout。执行前、报告前校验完整 SHA、普通文件 mode、Git blob OID 及原始 SHA256。
- 最后一个声明步骤独立生成一条 `FDE_CI_REPORT_V1`。报告绑定 run、attempt、job、tested SHA、source SHA、workflow SHA 和完整来源清单，不能用绿色检查、日志文本或 FDE 自身测试数代替业务结果。
- 从真实 Playwright JSON 逐项核对计数、退出状态和项目；失败不能成功，skip、预期失败、flaky/retry、零测试、缺失或损坏结果、来源或 SHA 漂移均不能放行。

## 首次接入与固定基线

本 PR 的基线没有该 CI 程序。CI 来源文件新增或修改时，只执行明确标识的普通 CI 自检，来源为本次 head；这不代表通过 FDE 的批准基线 Gate。后续功能 PR 若 CI 来源与 base 完全相同，必须从 base 执行适配。

FDE v2 的 `ci.source_sha == task.base_sha`、固定文件摘要及来源不得与任务 scope/create_files 重叠等要求保持不变。不能把普通自检的 head 来源报告冒充 base 来源报告。首次接入仍由普通开发、实际测试、独立 Standards/Spec 审阅及现有必需 CI 验收；合并另行批准。

## 验收

1. 使用 `CI=true bunx playwright test --project=component --workers=1 --retries=0 --fail-on-flaky-tests --reporter=json` 取得真实非零、零跳过基线；2026-10-30 在 `3a14aae0` 独立工作区实跑为 286 passed、0 skipped、0 flaky，耗时约 198 秒，最低门槛固定为 286。后续增加测试后，仍核对完整实测计数及新增用例被收集。
2. 报告解析与来源绑定测试覆盖成功、失败、跳过、预期失败、flaky/retry、零测试、缺失/损坏报告及 SHA/文件漂移。
3. 新适配通过 TypeScript 检查、单元测试和完整 component 回归；现有前端生产构建、上下文检查通过。
4. 同一最终 PR head 的原四项必需 CI 与新 CI 实际结果通过，独立 Standards/Spec 审阅无 blocker。

## 合并后接回功能任务

取得本 PR 合并授权并确认新 main 后，由 coordinator 为原功能重新准备 v2 intake：固定新 base、使用 `ci.schema_version: 1`，绑定本 workflow、适配及测试选择配置的真实摘要、精确步骤和实测门槛。新增错误页组件测试应命名为 `frontend/tests/error-component.component.spec.ts`，同步核对 scope/create_files，使其被 component 项目收集；不得改写原 Grant 或复用旧 digest。

项目 CI 报告只覆盖其声明的检查；原四项必需 CI 仍须核对同一当前 PR head。接入未合并前，不宣称原功能已具备批准基线 Gate。

只在已合并且核对远端的新 main checkout 中，可用下列只读命令生成 `contract.ci`；它不创建 Issue、Grant 或批准。生成后须按实际任务核对 `source_sha == task.base_sha`，并将完整 ci 纳入新批准内容：

```bash
node --experimental-strip-types --input-type=module <<'JS'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { minimumTests, sources } from './scripts/fde-frontend-ci.mts'
const repo = process.cwd()
const sha = execFileSync('git', ['rev-parse', 'HEAD'], {encoding: 'utf8'}).trim()
const files = sources(repo, repo, sha, sha).map(({path, sha256}) => ({path, sha256}))
const steps = [...readFileSync(files[0].path, 'utf8').matchAll(/^ {6}- name: (.+)$/gm)].map(m => m[1])
console.log(JSON.stringify({schema_version: 1, source_sha: sha, base_branch: 'main',
  workflow: files[0], helpers: files.slice(1), jobs: [{name: 'FDE frontend', required_steps: steps,
    report: {format: 'fde-json-v1', checks: [
      ...['adapter-tests', 'adapter-types', 'whitespace', 'frontend-build'].map(name => ({name, kind: 'check'})),
      {name: 'component', kind: 'tests', minimum_tests: minimumTests}
    ]}}]}, null, 2))
JS
```
