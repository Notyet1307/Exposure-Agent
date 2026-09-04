# ADR-0010：冻结完全合成的 NetFlow fixture 与回归 oracle

状态：提议

日期：2026-09-04

## 研究依据

Issue #167 要求产出永久可执行、不可还原客户数据的候选 NetFlow fixture 合同。本提议沿用仓库已有的永久 fixture 形态：`tests/cloudatlas_fixture/verify.py`、`tests/model_qualification_fixture/verify.py` 由 `scripts/test-*-fixture.sh` 提供稳定入口；它不使用 `evidence/` 中的 Issue 临时快照。

合成地址仅取自以下 primary sources 保留的文档空间：

- [RFC 5737](https://www.rfc-editor.org/rfc/rfc5737.html)：`192.0.2.0/24`、`198.51.100.0/24`、`203.0.113.0/24`；
- [RFC 3849](https://www.rfc-editor.org/rfc/rfc3849.html)：`2001:db8::/32`；
- [RFC 2606](https://www.rfc-editor.org/rfc/rfc2606.html) 与 [RFC 6761](https://www.rfc-editor.org/rfc/rfc6761.html)：测试和明确无效名称使用的保留域，包括 `.invalid`。

ADR-0009 仍是提议；本记录只据其候选 normalized CSV 与质量规则冻结研究 oracle，不把它或 #167 解释为 accepted decision、独立 Admission 或 R1 实现授权。

## 提议

`tests/netflow_fixture/oracle-v1.json` 是 fixture bytes、预期 normalized bytes、质量事实、聚合、未知项和禁止外推的唯一 oracle 事实源。所有 `input_utf8` 都从零人工合成，不复制、Hash、掩码、置换或变换任何客户记录，没有映射或 seed。JSON 直接冻结可读输入字符串及其 SHA-256；BOM、NUL、CRLF 和零字节场景用 JSON 转义表示，不依赖仓库外文件。

`tests/netflow_fixture/verify.py` 只使用 Python 标准库，独立解析并重算候选规范化、warning、重复、排序、聚合和 Hash，然后与 JSON 精确比较。它对 top-level、case、accept/reject expected、objects、warnings、aggregates、unknowns 和 defensive-run 递归拒绝未知键与错误 JSON 类型；隐私门禁拒绝敏感 credential 键和常见真实凭据形态，识别嵌入式 IP、host:port、CIDR、bracketed IPv6 与 IPv6 CIDR，并仅允许文档网段和精确 `bad.example.invalid`。accepted CSV header 只允许候选 required/optional 列及唯一合成 ignored 列 `FLOW_SAMPLER_ID`，后者每个值只可为空或文档网段 IP。verifier 内置额外 credential 键、AWS key、公共 host:port、私网 CIDR、外部 IPv6 和 ignored 自由文本的回归探针，任一被放行都会令命令失败。`scripts/test-netflow-fixture.sh` 与 root `test:netflow-fixture` 仅提供同一可执行入口。

该 verifier 是有界研究 oracle，不导入 `backend`，不访问网络或数据库，不实现生产 API，也不会自动成为未来生产 parser 的事实源。只有后续 Delivery Spec 通过独立 Admission 后，生产实现测试才可消费同一 fixture 与 expected oracle；届时不得复制一份会漂移的新 fixture。

## 后果

fixture 与 oracle 作为普通版本化测试资产永久保留，不进入 `evidence/`，不依赖 Issue 附件或本地下载目录。它当前只证明候选合同内部一致、可重复执行且完全合成，不证明任何尚未实现的生产行为已经交付。
