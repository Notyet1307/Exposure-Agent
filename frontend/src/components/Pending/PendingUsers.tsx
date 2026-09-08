import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useI18n } from "@/lib/i18n"

const PendingUsers = () => {
  const { t } = useI18n()
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("Full Name", "姓名")}</TableHead>
          <TableHead>{t("Email", "电子邮箱")}</TableHead>
          <TableHead>{t("Role", "角色")}</TableHead>
          <TableHead>{t("Status", "状态")}</TableHead>
          <TableHead>
            <span className="sr-only">{t("Actions", "操作")}</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {Array.from({ length: 5 }).map((_, index) => (
          <TableRow key={index}>
            <TableCell>
              <Skeleton className="h-4 w-32" />
            </TableCell>
            <TableCell>
              <Skeleton className="h-4 w-40" />
            </TableCell>
            <TableCell>
              <Skeleton className="h-5 w-20 rounded-full" />
            </TableCell>
            <TableCell>
              <div className="flex items-center gap-2">
                <Skeleton className="size-2 rounded-full" />
                <Skeleton className="h-4 w-12" />
              </div>
            </TableCell>
            <TableCell>
              <div className="flex justify-end">
                <Skeleton className="size-8 rounded-md" />
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

export default PendingUsers
