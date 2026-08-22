# ADR-0006：允许部署内模型资格检查直连客户内部推理端点

状态：已接受

范围依据：GitHub Issue #141 已确认的部署模型资格检查端点范围（父 Delivery Spec #140，REL-003/r1）。本 ADR 只记录该范围的架构边界，不独立扩大授权。

OctoBus 继续作为客户业务系统、资产系统与 CloudAtlas 的外部能力边界。固定非客户样本的模型资格检查是唯一部署内例外：agent-compose 启动的 Pi `model-qualifier` 可以经无重定向本地代理直连客户部署内、地址固定的私网 OpenAI-compatible 推理端点；该端点不作为 SourceInstance、CloudAtlas 或客户业务数据能力。

此例外仅覆盖当前固定四样本资格检查。调用必须绑定单一端点和模型身份，保持 Secret 注入隔离、响应大小上限、禁用工具和自动 retry，并且不得发送客户数据、调用客户环境外 Provider 或 fallback。它不授权绕过 OctoBus 读取或写入客户系统，也不授权产品报告草稿生成。若以后需要扩大模型调用范围，必须由后续已接受 Spec 和 ADR 重新明确数据、网络与授权边界；不得为本例外虚构 OctoBus 模型代理。
