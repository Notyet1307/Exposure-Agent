import type { NetflowCorrelationSearch } from "@/components/NetflowCorrelation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useI18n } from "@/lib/i18n"

export function NetflowFilters({
  search,
  onApply,
}: {
  search: NetflowCorrelationSearch
  onApply: (patch: Partial<NetflowCorrelationSearch>) => void
}) {
  const { t } = useI18n()
  const tab = search.tab
  if (tab !== "addresses" && tab !== "peers" && tab !== "tasks") return null
  const selectClass = "block rounded border bg-background p-2"
  return (
    <form
      key={JSON.stringify([
        tab,
        search.positiveSources,
        search.unmatchedNetflow,
        search.hasReviewTask,
        search.sort,
        search.peerIp,
        search.peerProtocol,
        search.peerPort,
        search.taskScope,
        search.taskKind,
        search.objectKey,
      ])}
      className="flex flex-wrap items-end gap-3"
      onSubmit={(event) => {
        event.preventDefault()
        const data = new FormData(event.currentTarget)
        const text = (name: string) =>
          String(data.get(name) ?? "").trim() || undefined
        const boolean = (name: string) =>
          text(name) === undefined ? undefined : text(name) === "true"
        const number = (name: string) =>
          text(name) === undefined ? undefined : Number(text(name))
        onApply({
          ...(tab === "addresses"
            ? {
                positiveSources: text("positiveSources"),
                unmatchedNetflow: boolean("unmatchedNetflow"),
                hasReviewTask: boolean("hasReviewTask"),
              }
            : {}),
          ...(tab === "peers"
            ? {
                peerIp: text("peerIp"),
                peerProtocol: number("peerProtocol"),
                peerPort: number("peerPort"),
              }
            : {}),
          ...(tab === "tasks"
            ? {
                taskScope: text(
                  "taskScope",
                ) as NetflowCorrelationSearch["taskScope"],
                taskKind: text("taskKind"),
                objectKey: text("objectKey"),
              }
            : { sort: text("sort") === "ip_desc" ? "ip_desc" : "ip_asc" }),
          addressPage: 0,
          servicePage: 0,
          comparisonPage: 0,
          evidencePage: 0,
          peerPage: 0,
          taskPage: 0,
          taskId: undefined,
          addressKey: undefined,
        })
      }}
    >
      {tab === "addresses" && (
        <>
          <Label>
            {t("Exact positive sources", "精确正向来源集合")}
            <select
              name="positiveSources"
              defaultValue={search.positiveSources ?? ""}
              className={selectClass}
            >
              <option value="">{t("All", "全部")}</option>
              {[
                "CUSTOMER",
                "CLOUD",
                "NETFLOW",
                "CUSTOMER,CLOUD",
                "CUSTOMER,NETFLOW",
                "CLOUD,NETFLOW",
                "CUSTOMER,CLOUD,NETFLOW",
              ].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </Label>
          <Label>
            {t("NetFlow-only clue", "NetFlow-only 线索")}
            <select
              name="unmatchedNetflow"
              defaultValue={String(search.unmatchedNetflow ?? "")}
              className={selectClass}
            >
              <option value="">{t("All", "全部")}</option>
              <option value="true">{t("Yes", "是")}</option>
              <option value="false">{t("No", "否")}</option>
            </select>
          </Label>
          <Label>
            {t("Has review task", "有关联复核任务")}
            <select
              name="hasReviewTask"
              defaultValue={String(search.hasReviewTask ?? "")}
              className={selectClass}
            >
              <option value="">{t("All", "全部")}</option>
              <option value="true">{t("Yes", "是")}</option>
              <option value="false">{t("No", "否")}</option>
            </select>
          </Label>
        </>
      )}
      {tab === "peers" && (
        <>
          <Label>
            {t("Peer IP", "对端 IP")}
            <Input name="peerIp" defaultValue={search.peerIp} />
          </Label>
          <Label>
            {t("Protocol number", "协议号")}
            <Input
              name="peerProtocol"
              type="number"
              min={0}
              max={255}
              defaultValue={search.peerProtocol}
            />
          </Label>
          <Label>
            {t("Peer port", "对端端口")}
            <Input
              name="peerPort"
              type="number"
              min={0}
              max={65535}
              defaultValue={search.peerPort}
            />
          </Label>
        </>
      )}
      {tab === "tasks" ? (
        <>
          <Label>
            {t("Task scope", "任务范围")}
            <select
              name="taskScope"
              defaultValue={search.taskScope ?? ""}
              className={selectClass}
            >
              <option value="">{t("All", "全部")}</option>
              <option value="dataset">{t("Batch", "批次")}</option>
              <option value="object">{t("Object", "对象")}</option>
            </select>
          </Label>
          <Label>
            {t("Task kind", "任务类型")}
            <Input name="taskKind" defaultValue={search.taskKind} />
          </Label>
          <Label>
            {t("Object key", "对象键")}
            <Input name="objectKey" defaultValue={search.objectKey} />
          </Label>
        </>
      ) : (
        <Label>
          {t(
            tab === "peers" ? "Peer order" : "Address order",
            tab === "peers" ? "对端排序" : "地址排序",
          )}
          <select
            name="sort"
            defaultValue={search.sort ?? "ip_asc"}
            className={selectClass}
          >
            <option value="ip_asc">{t("Ascending", "升序")}</option>
            <option value="ip_desc">{t("Descending", "降序")}</option>
          </select>
        </Label>
      )}
      <Button type="submit">{t("Apply filters", "应用筛选")}</Button>
    </form>
  )
}
