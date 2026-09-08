import type { ColumnDef } from "@tanstack/react-table"

import type { UserPublic } from "@/client"
import { Badge } from "@/components/ui/badge"
import { useI18n } from "@/lib/i18n"
import { cn } from "@/lib/utils"
import { UserActionsMenu } from "./UserActionsMenu"

export type UserTableData = UserPublic & {
  isCurrentUser: boolean
}

export const columns: ColumnDef<UserTableData>[] = [
  {
    accessorKey: "full_name",
    header: function FullNameHeader() {
      const { t } = useI18n()
      return t("Full Name", "姓名")
    },
    cell: function FullNameCell({ row }) {
      const { t } = useI18n()
      const fullName = row.original.full_name
      return (
        <div className="flex items-center gap-2">
          <span
            className={cn("font-medium", !fullName && "text-muted-foreground")}
          >
            {fullName || t("N/A", "不适用")}
          </span>
          {row.original.isCurrentUser && (
            <Badge variant="outline" className="text-xs">
              {t("You", "您")}
            </Badge>
          )}
        </div>
      )
    },
  },
  {
    accessorKey: "email",
    header: function EmailHeader() {
      const { t } = useI18n()
      return t("Email", "电子邮箱")
    },
    cell: ({ row }) => (
      <span className="text-muted-foreground">{row.original.email}</span>
    ),
  },
  {
    accessorKey: "is_superuser",
    header: function RoleHeader() {
      const { t } = useI18n()
      return t("Role", "角色")
    },
    cell: function RoleCell({ row }) {
      const { t } = useI18n()
      return (
        <Badge variant={row.original.is_superuser ? "default" : "secondary"}>
          {row.original.is_superuser
            ? t("Superuser", "超级用户")
            : t("User", "普通用户")}
        </Badge>
      )
    },
  },
  {
    accessorKey: "is_active",
    header: function StatusHeader() {
      const { t } = useI18n()
      return t("Status", "状态")
    },
    cell: function StatusCell({ row }) {
      const { t } = useI18n()
      return (
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "size-2 rounded-full",
              row.original.is_active ? "bg-green-500" : "bg-gray-400",
            )}
          />
          <span
            className={row.original.is_active ? "" : "text-muted-foreground"}
          >
            {row.original.is_active
              ? t("Active", "已启用")
              : t("Inactive", "已停用")}
          </span>
        </div>
      )
    },
  },
  {
    id: "actions",
    header: function ActionsHeader() {
      const { t } = useI18n()
      return <span className="sr-only">{t("Actions", "操作")}</span>
    },
    cell: ({ row }) => (
      <div className="flex justify-end">
        <UserActionsMenu user={row.original} />
      </div>
    ),
  },
]
