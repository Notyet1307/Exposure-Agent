# ADR-0005：IPv4-mapped IPv6 折叠为 IPv4 Resource 身份

状态：已接受

IP Resource 的 Canonical IP 只把标准 `::ffff:0:0/96` IPv4-mapped IPv6 折叠为其中承载的 IPv4；其他 IPv4 与 IPv6 地址保持各自的规范地址语义。这样可以避免客户来源和 CloudAtlas 用两种表示描述同一 IPv4 时产生两条相反 Finding；代价是 mapped 表示不能成为独立 Resource，但原始来源文本仍由 Observation 和 SourceSnapshot Artifact 保留。该身份规则一旦形成跨 Run Resource 与 Finding 去重键便难以迁移，因此在首次 Resource Resolution 前固定。
