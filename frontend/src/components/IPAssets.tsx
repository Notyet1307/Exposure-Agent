import { useQuery } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import {
  type IPAssetDetailPublic,
  type IPAssetPublic,
  IpResultsService,
} from "@/client"
import { ResultPagination } from "@/components/ResultPagination"
import { Stage4ResultNotice } from "@/components/Stage4ResultNotice"
import { useLocale } from "@/components/LocaleProvider"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

const PAGE_SIZE = 25
type Localize = (chinese: string, english: string) => string

function observationStatus(observed: boolean, text: Localize) {
  return (
    <Badge variant={observed ? "default" : "outline"}>
      {observed ? text("已观测", "Present") : text("未观测", "Not observed")}
    </Badge>
  )
}

function findingLabel(findingType: string | null, text: Localize) {
  if (findingType === "UNREPORTED_ASSET") {
    return text("未报备资产", "Unreported asset")
  }
  if (findingType === "UNOBSERVED_ASSET") {
    return text("未观测资产", "Unobserved asset")
  }
  return findingType ?? text("无", "None")
}

function ObservationRows({
  detail,
  text,
}: {
  detail: IPAssetDetailPublic
  text: Localize
}) {
  const observations = detail.observations ?? []
  if (observations.length === 0) {
    return <p className="text-sm text-muted-foreground">{text("暂无观测记录。", "No observations.")}</p>
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{text("原始 IP", "Raw IP")}</TableHead>
          <TableHead>{text("规范 IP", "Canonical IP")}</TableHead>
          <TableHead>{text("来源", "Source")}</TableHead>
          <TableHead>{text("位置", "Location")}</TableHead>
          <TableHead>{text("CloudAtlas ID", "CloudAtlas ID")}</TableHead>
          <TableHead>{text("CloudAtlas 状态", "CloudAtlas status")}</TableHead>
          <TableHead>{text("快照", "Snapshot")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {observations.map((observation) => (
          <TableRow key={observation.id}>
            <TableCell className="font-mono text-xs">
              {observation.raw_ip}
            </TableCell>
            <TableCell className="font-mono text-xs">
              {observation.canonical_ip}
            </TableCell>
            <TableCell>{observation.source_type}</TableCell>
            <TableCell className="font-mono text-xs">
              {observation.source_record_key}
            </TableCell>
            <TableCell className="font-mono text-xs">
              {observation.cloudatlas_asset_id ?? "—"}
            </TableCell>
            <TableCell>{observation.cloudatlas_status ?? "—"}</TableCell>
            <TableCell className="font-mono text-xs">
              {observation.source_snapshot_id}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function AssetDetailDialog({
  projectId,
  resourceId,
  onOpenChange,
}: {
  projectId: string
  resourceId: string | null
  onOpenChange: (open: boolean) => void
}) {
  const { text } = useLocale()
  const [page, setPage] = useState(0)
  useEffect(() => {
    if (resourceId === null) setPage(0)
  }, [resourceId])
  const detailQuery = useQuery({
    queryKey: ["ip-asset", projectId, resourceId, page],
    queryFn: () =>
      IpResultsService.readIpAsset({
        projectId,
        resourceId: resourceId as string,
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
    enabled: resourceId !== null,
  })

  return (
    <Dialog
      open={resourceId !== null}
      onOpenChange={(open) => onOpenChange(open)}
    >
      <DialogContent className="max-w-[calc(100%-2rem)] sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>{text("IP 资产详情", "IP Asset details")}</DialogTitle>
          <DialogDescription>
            {text(
              "此处仅展示已确认的来源观测和快照引用，不展示原始制品。",
              "Only confirmed source observations and Snapshot references are shown. Original artifacts are not exposed here.",
            )}
          </DialogDescription>
        </DialogHeader>
        {detailQuery.isPending && <p role="status">{text("正在加载资产详情…", "Loading Asset details…")}</p>}
        {detailQuery.isError && (
          <Alert variant="destructive">
            <AlertTitle>{text("无法加载资产详情", "Asset details could not be loaded")}</AlertTitle>
            <AlertDescription>{text("请稍后重试。", "Please try again later.")}</AlertDescription>
          </Alert>
        )}
        {detailQuery.data && (
          <div className="space-y-4">
            <div className="grid gap-3 text-sm md:grid-cols-4">
              <div>
                <p className="font-medium">{text("规范 IP", "Canonical IP")}</p>
                <p className="font-mono">{detailQuery.data.canonical_ip}</p>
              </div>
              <div>
                <p className="font-medium">{text("客户侧", "Customer side")}</p>
                {observationStatus(detailQuery.data.customer_observed, text)}
              </div>
              <div>
                <p className="font-medium">{text("CloudAtlas 侧", "CloudAtlas side")}</p>
                {observationStatus(detailQuery.data.cloudatlas_observed, text)}
              </div>
              <div>
                <p className="font-medium">{text("观测数量", "Observation count")}</p>
                <p>{detailQuery.data.observation_count}</p>
              </div>
            </div>
            <ObservationRows detail={detailQuery.data} text={text} />
            <ResultPagination
              label={text("资产观测记录", "Asset observations")}
              count={detailQuery.data.observation_count}
              page={page}
              pageSize={PAGE_SIZE}
              onPageChange={setPage}
            />
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function AssetRow({
  asset,
  onDetails,
  text,
}: {
  asset: IPAssetPublic
  onDetails: () => void
  text: Localize
}) {
  return (
    <TableRow>
      <TableCell className="font-mono font-medium">
        {asset.canonical_ip}
      </TableCell>
      <TableCell>{observationStatus(asset.customer_observed, text)}</TableCell>
      <TableCell>{observationStatus(asset.cloudatlas_observed, text)}</TableCell>
      <TableCell>
        <div>{asset.observation_count}</div>
        <div className="text-xs text-muted-foreground">
          {text(
            `客户侧 ${asset.customer_observation_count} · CloudAtlas ${asset.cloudatlas_observation_count}`,
            `Customer ${asset.customer_observation_count} · CloudAtlas ${asset.cloudatlas_observation_count}`,
          )}
        </div>
      </TableCell>
      <TableCell>
        {asset.open_finding_type ? (
          <div>
            <div>{findingLabel(asset.open_finding_type, text)}</div>
            <div className="font-mono text-xs text-muted-foreground">
              {asset.open_finding_type}
            </div>
          </div>
        ) : (
          <span className="text-muted-foreground">{text("无", "None")}</span>
        )}
      </TableCell>
      <TableCell>
        <LoadingButton
          type="button"
          variant="outline"
          size="sm"
          onClick={onDetails}
        >
          {text("查看详情", "View details")}
        </LoadingButton>
      </TableCell>
    </TableRow>
  )
}

export default function IPAssets({ projectId }: { projectId: string }) {
  const { locale, text } = useLocale()
  const [page, setPage] = useState(0)
  const [selectedResourceId, setSelectedResourceId] = useState<string | null>(
    null,
  )
  const assetsQuery = useQuery({
    queryKey: ["ip-assets", projectId, page],
    queryFn: () =>
      IpResultsService.readIpAssets({
        projectId,
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
  })

  useEffect(() => {
    if (!assetsQuery.data) return
    const pageCount = Math.max(1, Math.ceil(assetsQuery.data.count / PAGE_SIZE))
    if (page >= pageCount) setPage(pageCount - 1)
  }, [assetsQuery.data, page])

  if (assetsQuery.isPending) return <p role="status">{text("正在加载 IP 资产…", "Loading IP Assets…")}</p>
  if (assetsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>{text("无法加载 IP 资产", "IP Assets could not be loaded")}</AlertTitle>
        <AlertDescription>{text("请稍后重试。", "Please try again later.")}</AlertDescription>
      </Alert>
    )
  }

  const assets = assetsQuery.data
  if (!assets.compatible) {
    return (
      <Stage4ResultNotice
        latestRunId={assets.latest_run_id}
        latestRunCompletedAt={assets.latest_run_completed_at}
      />
    )
  }

  return (
    <section className="space-y-4" aria-labelledby="ip-assets-title">
      <Card>
        <CardHeader>
          <CardTitle id="ip-assets-title">{text("IP 资产", "IP Assets")}</CardTitle>
          <CardDescription>
            {text(
              `最近一次兼容且已完成的治理运行 · ${assets.count} 个 IP 资源`,
              `Latest compatible completed Run · ${assets.count} IP Resource${assets.count === 1 ? "" : "s"}`,
            )}
            {assets.latest_run_id && (
              <span className="block break-all font-mono text-xs">
                {text("已发布治理运行 ", "Published Run ")}{assets.latest_run_id}
              </span>
            )}
            {assets.latest_run_completed_at && (
              <>
                {" "}
                {text("· 完成于 ", "· completed ")}
                {new Date(assets.latest_run_completed_at).toLocaleString(locale)}
              </>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {assets.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {text("最近一次兼容治理运行中未观测到 IP 资源。", "No IP Resources were observed in the latest compatible Run.")}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{text("规范 IP", "Canonical IP")}</TableHead>
                  <TableHead>{text("客户侧", "Customer side")}</TableHead>
                  <TableHead>{text("CloudAtlas 侧", "CloudAtlas side")}</TableHead>
                  <TableHead>{text("观测记录", "Observations")}</TableHead>
                  <TableHead>{text("开放发现项", "Open Finding")}</TableHead>
                  <TableHead>{text("详情", "Details")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {assets.data.map((asset) => (
                  <AssetRow
                    key={asset.id}
                    asset={asset}
                    text={text}
                    onDetails={() => setSelectedResourceId(asset.resource_id)}
                  />
                ))}
              </TableBody>
            </Table>
          )}
          <ResultPagination
            label={text("资产", "Assets")}
            count={assets.count}
            page={page}
            pageSize={PAGE_SIZE}
            onPageChange={setPage}
          />
        </CardContent>
      </Card>
      <AssetDetailDialog
        projectId={projectId}
        resourceId={selectedResourceId}
        onOpenChange={(open) => {
          if (!open) setSelectedResourceId(null)
        }}
      />
    </section>
  )
}
