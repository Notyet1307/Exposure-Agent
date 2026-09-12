import { useQuery } from "@tanstack/react-query"
import { Link, useRouterState } from "@tanstack/react-router"
import {
  ArrowRight,
  CheckCircle2,
  FileSpreadsheet,
  Network,
  Radio,
} from "lucide-react"
import { useEffect, useRef } from "react"
import { CloudatlasSourceInstancesService, ProjectsService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"
import { useWorkspaceSearch } from "@/lib/workspace"

export default function ProjectPreparation({
  projectId,
  archived,
}: {
  projectId: string
  archived: boolean
}) {
  const { t, formatDate } = useI18n()
  const heading = useRef<HTMLHeadingElement>(null)
  const view = useWorkspaceSearch().view
  const hash = useRouterState({ select: (state) => state.location.hash })
  useEffect(() => {
    const id = hash.replace(/^#/, "")
    const target =
      view === "inputs" && ["customer-inputs", "netflow-inputs"].includes(id)
        ? document.getElementById(id)
        : heading.current
    target?.focus()
  }, [view, hash])
  const customer = useQuery({
    queryKey: ["customer-uploads", projectId, 0],
    queryFn: () =>
      ProjectsService.readCustomerUploads({ projectId, skip: 0, limit: 10 }),
  })
  const sources = useQuery({
    queryKey: ["cloudatlas-source-instances", projectId],
    queryFn: () =>
      CloudatlasSourceInstancesService.readCloudatlasSources({ projectId }),
  })
  const netflow = useQuery({
    queryKey: ["netflow-datasets", projectId, 0],
    queryFn: () =>
      ProjectsService.readNetflowDatasets({ projectId, skip: 0, limit: 10 }),
  })
  const selected = customer.data?.data.find(
    (item) => item.id === customer.data.current_customer_upload_id,
  )
  const source =
    sources.data?.data.find((item) => item.enabled) ?? sources.data?.data[0]
  const sourceReady =
    !!source?.enabled &&
    source.validation_status === "validated" &&
    !!source.validated_fingerprint
  const flow = netflow.data?.current_netflow_dataset
  const cards = [
    {
      label: t("Asset register", "资产台账"),
      icon: FileSpreadsheet,
      loading: customer.isPending,
      failed: customer.isError,
      ready: !!customer.data?.current_customer_upload_id,
      state: customer.data?.current_customer_upload_id
        ? t("Selected", "已选中")
        : customer.data?.count
          ? t("Accepted, select a version", "已接受，待选中")
          : t("Upload required", "待上传"),
      detail: selected
        ? `${selected.display_filename} · ${selected.record_count} ${t("records", "条")} · ${formatDate(selected.created_at)}`
        : t(
            "XLSX · accept the file, then select its version",
            "XLSX · 接受文件后，显式选择本轮版本",
          ),
      view: "inputs" as const,
      hash: "customer-inputs",
      canEdit: !archived && !!customer.data?.can_select,
    },
    {
      label: t("External observations", "外部观测"),
      icon: Radio,
      loading: sources.isPending,
      failed: sources.isError,
      ready: sourceReady,
      state: sourceReady
        ? t("Validated and enabled", "已验证并启用")
        : source?.validation_status === "unavailable"
          ? t("Connection unavailable", "来源连接不可用")
          : source?.validation_status === "invalid" ||
              source?.validation_status === "failed"
            ? t("Validation required", "验证失效，需重新验证")
            : source
              ? t("Validate and enable", "待验证或启用")
              : t("Connection required", "待绑定来源"),
      detail:
        source?.instance_id ??
        t(
          "CloudAtlas via OctoBus · no file upload",
          "通过 OctoBus 连接 CloudAtlas · 不支持文件上传",
        ),
      view: "cloudatlas" as const,
      hash: undefined,
      canEdit: !archived && !!sources.data?.can_manage,
    },
    {
      label: t("NetFlow activity", "NetFlow 活动"),
      icon: Network,
      loading: netflow.isPending,
      failed: netflow.isError,
      ready: !!flow,
      state: flow
        ? t("Selected", "已选中")
        : t("Optional · not selected", "可选 · 未选择"),
      detail: flow
        ? `${flow.display_filename} · ${flow.raw_record_count} ${t("records", "条")} · ${formatDate(flow.created_at)}`
        : t(
            "CSV / TXT · continue with two sources if omitted",
            "CSV / TXT · 未选择时使用两来源比对",
          ),
      view: "inputs" as const,
      hash: "netflow-inputs",
      canEdit: !archived && !!netflow.data?.can_select,
    },
  ]
  return (
    <section aria-labelledby="preparation-title" className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h2
            ref={heading}
            tabIndex={-1}
            id="preparation-title"
            className="text-2xl font-semibold"
          >
            {t("Prepare this comparison", "准备本轮比对")}
          </h2>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t(
              "Choose the input versions, then confirm and start. Accepted files stay available when another step fails.",
              "选好输入版本，再确认并开始。某一步失败不会清空其他已接受的输入。",
            )}
          </p>
        </div>
        <Button asChild className="text-black">
          <Link to="/" search={{ project: projectId, view: "runs" }}>
            {t("Review inputs and start", "确认输入并开始")}
            <ArrowRight aria-hidden="true" />
          </Link>
        </Button>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        {cards.map((card) => (
          <article
            key={card.label}
            className="flex min-w-0 flex-col gap-4 rounded-xl border bg-card p-5 transition-colors duration-150"
          >
            <div className="flex items-center justify-between gap-3">
              <card.icon aria-hidden="true" className="size-5 text-primary" />
              <Badge
                className={
                  card.ready && !card.failed && !card.loading
                    ? "text-black"
                    : undefined
                }
                variant={
                  card.ready && !card.failed && !card.loading
                    ? "default"
                    : "secondary"
                }
              >
                {card.loading
                  ? t("Loading…", "读取中…")
                  : card.failed
                    ? t("Unavailable", "读取失败")
                    : card.state}
              </Badge>
            </div>
            <h3 className="text-lg font-semibold">{card.label}</h3>
            <p
              className="min-h-10 break-words text-sm text-muted-foreground"
              role={card.loading ? "status" : undefined}
            >
              {card.failed
                ? t(
                    "Could not read this source. Open its management page to retry.",
                    "无法读取该来源，请打开管理页重试。",
                  )
                : card.detail}
            </p>
            <div className="mt-auto flex flex-wrap items-center justify-between gap-2">
              {card.ready && !card.failed && !card.loading && (
                <CheckCircle2
                  className="size-4 text-primary"
                  aria-label={t("Selected input available", "当前输入可读")}
                />
              )}
              <Button variant="outline" asChild>
                <Link
                  to="/"
                  search={{ project: projectId, view: card.view }}
                  hash={card.hash}
                >
                  {card.canEdit
                    ? t("Manage input", "准备或更换输入")
                    : t("View input", "查看输入")}
                </Link>
              </Button>
            </div>
          </article>
        ))}
      </div>
      <p className="text-sm text-muted-foreground">
        {archived
          ? t(
              "This project is archived and read-only.",
              "此项目已归档，只能阅读。",
            )
          : t(
              "The server checks connection identity and deployment credentials again at launch. No AI call is needed for comparison.",
              "启动时服务端会再次核对来源身份和部署凭据。确定性比对无需调用 AI。",
            )}
      </p>
    </section>
  )
}
