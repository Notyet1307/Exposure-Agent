# V2 AI 解读本地验证回执

固定 Spec：`docs/specs/v2-ai-interpretation.md` @ `1c42406`。候选提交：B `9df637e`，C `cbabdd2`。

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| B/C DTO、固定 subject、版本、CAS、引用和输出拒绝 | PASS | `cd backend && uv run pytest tests/domain/test_v2_analysis_reports.py -q`：12 passed；包含缺失固定计数/确切地址 fact 的拒绝。 |
| B/C 浏览器交互 | PASS | 以临时合成环境运行 `frontend/tests/v2-reports.component.spec.ts`：9 passed；覆盖零自动 POST、同 key 恢复、地址解释、失效打印拒绝。 |
| 前端构建 | PASS | `cd frontend && bun run build`。 |
| 前端 lint | PASS_WITH_INFO | `bun run lint` 完成；Biome 提示配置 schema 为 2.3.14、CLI 为 2.4.16。 |
| V2 runner 固定材料重鉴权 | FAIL | 独立探针 `exposure-v2-runtime-3f725egz`：后端 direct core reader PASS；同 guest 因客户工件未挂载返回 `netflow_artifact_integrity_failed`，runner 映射为 `v2_report_material_unavailable`，未到 Provider。不得通过向模型 runner 挂载原始工件修复。 |
| 后端完整回归 | NOT_RUN | 本轮局部 pytest 未显式隔离测试库，可能触发共享库清理；最终候选稳定后必须在隔离库重新运行。 |
| 真实模型语义/客户出域 | NOT_RUN | 不在本轮授权范围。 |

运行时失败需要受控的后端侧重鉴权/固定 DTO bridge：模型 guest 只能读取已封存 DTO，不能获得 Artifact、文件系统或任意读取能力。
