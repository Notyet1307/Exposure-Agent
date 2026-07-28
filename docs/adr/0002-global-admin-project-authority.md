# ADR-0002：全局 Admin 跨 Project 权限

状态：已接受

Admin 不写入 ProjectMembership，却自动拥有所有 Project 的 Viewer、Operator、Approver 与管理权限；这是对普通 Project 隔离的显式全局例外。该选择降低私有化部署的管理成本，但 Admin 仍不能审批自己创建的 Plan，且其操作必须产生脱敏的 AuditEvent。
