import { Skeleton } from "@/components/ui/skeleton"
import { useLocale } from "@/components/LocaleProvider"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

const PendingUsers = () => {
  const { text } = useLocale()
  return (
  <Table>
    <TableHeader>
      <TableRow>
        <TableHead>{text("姓名", "Full Name")}</TableHead>
        <TableHead>{text("邮箱", "Email")}</TableHead>
        <TableHead>{text("角色", "Role")}</TableHead>
        <TableHead>{text("状态", "Status")}</TableHead>
        <TableHead>
          <span className="sr-only">{text("操作", "Actions")}</span>
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
