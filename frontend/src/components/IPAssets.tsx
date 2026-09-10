import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { useEffect } from "react"

import {
  type IPAssetDetailPublic,
  type IPAssetPublic,
  IpResultsService,
} from "@/client"
import { AiInvestigationPanel } from "@/components/AiInvestigationPanel"
import { ManualReviewPanel } from "@/components/ManualReviewPanel"
import { ResultPagination } from "@/components/ResultPagination"
import { Stage4ResultNotice } from "@/components/Stage4ResultNotice"
import { TechnicalValue } from "@/components/TechnicalValue"
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

import { useI18n } from "@/lib/i18n"
import { useWorkspaceNavigate, useWorkspaceSearch } from "@/lib/workspace"

const PAGE_SIZE = 25

function observationStatus(
  observed: boolean,
  t: ReturnType<typeof useI18n>["t"],
) {
  return (
    <Badge variant={observed ? "default" : "outline"}>
      {observed ? t("Present", "已观测") : t("Not observed", "未观测")}
    </Badge>
  )
}

function findingLabel(
  findingType: string | null,
  t: ReturnType<typeof useI18n>["t"],
) {
  if (findingType === "UNREPORTED_ASSET")
    return t("Unreported asset", "未申报资产")
  if (findingType === "UNOBSERVED_ASSET")
    return t("Unobserved asset", "未观测资产")
  return findingType ?? t("None", "无")
}

function ObservationRows({ detail }: { detail: IPAssetDetailPublic }) {
  const { t, translateValue } = useI18n()
  const observations = detail.observations ?? []
  if (observations.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t("No observations.", "暂无观测记录。")}
      </p>
    )
  }
  return (
    <div className="grid min-w-0 gap-3 md:grid-cols-2">
      {observations.map((observation) => (
        <div
          key={observation.id}
          className="min-w-0 space-y-2 rounded-md border p-3 text-sm"
        >
          <p className="break-all font-mono font-medium">
            {observation.canonical_ip}
          </p>
          <p>{translateValue(observation.source_type)}</p>
          <p className="break-all">
            {t("CloudAtlas status", "CloudAtlas 状态")}:{" "}
            {observation.cloudatlas_status ?? "—"}
          </p>
          <details className="min-w-0">
            <summary className="cursor-pointer font-medium focus-visible:outline-2">
              {t("View evidence", "查看依据")}
            </summary>
            <dl className="mt-2 min-w-0 space-y-2">
              <div>
                <dt>{t("Observation ID", "观测 ID")}</dt>
                <dd>
                  <TechnicalValue value={observation.id} />
                </dd>
              </div>
              <div>
                <dt>{t("Raw IP", "原始 IP")}</dt>
                <dd>
                  <TechnicalValue value={observation.raw_ip} />
                </dd>
              </div>
              <div>
                <dt>{t("Location", "位置")}</dt>
                <dd>
                  <TechnicalValue value={observation.source_record_key} />
                </dd>
              </div>
              <div>
                <dt>{t("CloudAtlas ID", "CloudAtlas ID")}</dt>
                <dd>
                  {observation.cloudatlas_asset_id === null ? (
                    "—"
                  ) : (
                    <TechnicalValue value={observation.cloudatlas_asset_id} />
                  )}
                </dd>
              </div>
              <div>
                <dt>{t("Snapshot", "快照")}</dt>
                <dd>
                  <TechnicalValue value={observation.source_snapshot_id} />
                </dd>
              </div>
            </dl>
          </details>
        </div>
      ))}
    </div>
  )
}

function AssetDetailDialog({
  projectId,
  resourceId,
  publishedRunId,
  onOpenChange,
}: {
  projectId: string
  resourceId: string | null
  publishedRunId: string | null
  onOpenChange: (open: boolean) => void
}) {
  const { t, formatDate } = useI18n()
  const search = useWorkspaceSearch()
  const navigate = useWorkspaceNavigate()
  const page = (search.asset_page ?? 1) - 1
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

  useEffect(() => {
    if (resourceId && publishedRunId && !search.investigation_run) {
      void navigate({
        search: (prev) => ({ ...prev, investigation_run: publishedRunId }),
        replace: true,
      })
    }
  }, [navigate, publishedRunId, resourceId, search.investigation_run])

  useEffect(() => {
    if (resourceId === null || !detailQuery.data) return
    const pageCount = Math.max(
      1,
      Math.ceil(detailQuery.data.observation_count / PAGE_SIZE),
    )
    if (page >= pageCount) {
      void navigate({
        search: (prev) => ({
          ...prev,
          asset_page: pageCount > 1 ? pageCount : undefined,
        }),
        replace: true,
      })
    }
  }, [detailQuery.data, navigate, page, resourceId])

  return (
    <Dialog
      open={resourceId !== null}
      onOpenChange={(open) => onOpenChange(open)}
    >
      <DialogContent className="max-h-[90vh] max-w-[calc(100%-2rem)] overflow-y-auto sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>{t("IP Asset details", "IP 资产详情")}</DialogTitle>
          <DialogDescription>
            {t(
              "Only confirmed source observations and Snapshot references are shown. Original artifacts are not exposed here.",
              "仅显示已确认的来源观测记录与快照引用。此处不展示原始产物。",
            )}
          </DialogDescription>
        </DialogHeader>
        {detailQuery.isPending && (
          <p role="status">
            {t("Loading Asset details…", "正在加载资产详情…")}
          </p>
        )}
        {detailQuery.isError && (
          <Alert variant="destructive">
            <AlertTitle>
              {t("Asset details could not be loaded", "无法加载资产详情")}
            </AlertTitle>
            <AlertDescription>
              {t("Please try again later.", "请稍后重试。")}
            </AlertDescription>
          </Alert>
        )}
        {detailQuery.isSuccess &&
          detailQuery.data.resource_id === resourceId && (
            <div className="min-w-0 space-y-4">
              <div className="grid min-w-0 gap-3 text-sm md:grid-cols-4">
                <div>
                  <p className="font-medium">
                    {t("Canonical IP", "规范化 IP")}
                  </p>
                  <p className="break-all font-mono">
                    {detailQuery.data.canonical_ip}
                  </p>
                </div>
                <div>
                  <p className="font-medium">{t("Customer side", "客户侧")}</p>
                  {observationStatus(detailQuery.data.customer_observed, t)}
                </div>
                <div>
                  <p className="font-medium">
                    {t("CloudAtlas side", "CloudAtlas 侧")}
                  </p>
                  {observationStatus(detailQuery.data.cloudatlas_observed, t)}
                </div>
                <div>
                  <p className="font-medium">
                    {t("Observation count", "观测数量")}
                  </p>
                  <p>{detailQuery.data.observation_count}</p>
                </div>
              </div>
              <p className="text-sm">
                {t("Open Finding", "未关闭的发现项")}:{" "}
                {findingLabel(detailQuery.data.open_finding_type, t)}
              </p>
              <p className="text-sm text-muted-foreground">
                {t("Published Run completed", "已发布运行完成于")}{" "}
                {detailQuery.data.latest_run_completed_at
                  ? formatDate(detailQuery.data.latest_run_completed_at)
                  : t("Not available", "不可用")}
              </p>
              {search.investigation_run && resourceId && (
                <AiInvestigationPanel
                  key={`${projectId}:${resourceId}:${search.investigation_run}`}
                  projectId={projectId}
                  resourceId={resourceId}
                  runId={search.investigation_run}
                />
              )}
              {search.investigation_run && resourceId && (
                <ManualReviewPanel
                  key={`manual:${projectId}:${resourceId}:${search.investigation_run}`}
                  projectId={projectId}
                  resourceId={resourceId}
                  runId={search.investigation_run}
                />
              )}
              <details className="min-w-0 rounded-md border p-3 text-sm">
                <summary className="cursor-pointer font-medium focus-visible:outline-2">
                  {t("View evidence", "查看依据")}
                </summary>
                <dl className="mt-3 min-w-0 space-y-2">
                  <div>
                    <dt>{t("Published Run", "已发布运行")}</dt>
                    <dd>
                      <TechnicalValue value={detailQuery.data.latest_run_id} />
                    </dd>
                  </div>
                  <div>
                    <dt>{t("Project ID", "项目 ID")}</dt>
                    <dd>
                      <TechnicalValue value={projectId} />
                    </dd>
                  </div>
                  <div>
                    <dt>{t("Resource ID", "资源 ID")}</dt>
                    <dd>
                      <TechnicalValue value={detailQuery.data.resource_id} />
                    </dd>
                  </div>
                  <div>
                    <dt>{t("Asset ID", "资产 ID")}</dt>
                    <dd>
                      <TechnicalValue value={detailQuery.data.id} />
                    </dd>
                  </div>
                  <div>
                    <dt>{t("Resource type", "资源类型")}</dt>
                    <dd>
                      <TechnicalValue value={detailQuery.data.resource_type} />
                    </dd>
                  </div>
                  <div>
                    <dt>{t("Canonical key", "规范化键")}</dt>
                    <dd>
                      <TechnicalValue value={detailQuery.data.canonical_key} />
                    </dd>
                  </div>
                  {detailQuery.data.open_finding_id && (
                    <div>
                      <dt>{t("Open Finding ID", "未关闭的发现项 ID")}</dt>
                      <dd>
                        <TechnicalValue
                          value={detailQuery.data.open_finding_id}
                        />
                      </dd>
                    </div>
                  )}
                  {detailQuery.data.open_finding_type && (
                    <div>
                      <dt>{t("Finding type", "发现类型")}</dt>
                      <dd>
                        <TechnicalValue
                          value={detailQuery.data.open_finding_type}
                        />
                      </dd>
                    </div>
                  )}
                </dl>
                <Link
                  className="mt-2 inline-block underline"
                  to="/projects/$projectId/runs/$runId/lineage"
                  params={{ projectId, runId: detailQuery.data.latest_run_id }}
                  search={{
                    project: projectId,
                    run: detailQuery.data.latest_run_id,
                    resource_id: detailQuery.data.resource_id,
                    view: "overview",
                  }}
                >
                  {t(
                    "View this resource's Run lineage",
                    "查看此资源在该运行中的血缘",
                  )}
                </Link>
              </details>
              <ObservationRows detail={detailQuery.data} />
              <ResultPagination
                label={t("Asset observations", "资产观测记录")}
                count={detailQuery.data.observation_count}
                page={page}
                pageSize={PAGE_SIZE}
                onPageChange={(nextPage) =>
                  navigate({
                    search: (prev) => ({
                      ...prev,
                      asset_page: nextPage > 0 ? nextPage + 1 : undefined,
                    }),
                  })
                }
              />
            </div>
          )}
      </DialogContent>
    </Dialog>
  )
}

function AssetRow({
  asset,
  projectId,
  runId,
  onDetails,
}: {
  asset: IPAssetPublic
  projectId: string
  runId: string | null
  onDetails: () => void
}) {
  const { t } = useI18n()
  return (
    <TableRow>
      <TableCell className="break-all font-mono font-medium">
        {asset.canonical_ip}
      </TableCell>
      <TableCell>{observationStatus(asset.customer_observed, t)}</TableCell>
      <TableCell>{observationStatus(asset.cloudatlas_observed, t)}</TableCell>
      <TableCell>
        <div>{asset.observation_count}</div>
        <div className="text-xs text-muted-foreground">
          {t(
            `Customer ${asset.customer_observation_count} · CloudAtlas ${asset.cloudatlas_observation_count}`,
            `客户 ${asset.customer_observation_count} · CloudAtlas ${asset.cloudatlas_observation_count}`,
          )}
        </div>
      </TableCell>
      <TableCell>
        {asset.open_finding_type ? (
          <div>{findingLabel(asset.open_finding_type, t)}</div>
        ) : (
          <span className="text-muted-foreground">{t("None", "无")}</span>
        )}
      </TableCell>
      <TableCell>
        <LoadingButton
          type="button"
          variant="outline"
          size="sm"
          onClick={onDetails}
        >
          {t("View details", "查看详情")}
        </LoadingButton>
        <details className="mt-2 min-w-0 max-w-64 whitespace-normal text-xs">
          <summary className="cursor-pointer font-medium focus-visible:outline-2">
            {t("View evidence", "查看依据")}
          </summary>
          <dl className="mt-2 min-w-0 space-y-2">
            <div>
              <dt>{t("Project ID", "项目 ID")}</dt>
              <dd>
                <TechnicalValue value={projectId} />
              </dd>
            </div>
            <div>
              <dt>{t("Resource ID", "资源 ID")}</dt>
              <dd>
                <TechnicalValue value={asset.resource_id} />
              </dd>
            </div>
            {runId && (
              <div>
                <dt>{t("Published Run", "已发布运行")}</dt>
                <dd>
                  <TechnicalValue value={runId} />
                </dd>
              </div>
            )}
          </dl>
          {runId && (
            <Link
              className="mt-2 inline-block underline"
              to="/projects/$projectId/runs/$runId/lineage"
              params={{ projectId, runId }}
              search={{
                project: projectId,
                run: runId,
                resource_id: asset.resource_id,
                view: "overview",
              }}
            >
              {t(
                "View this resource's Run lineage",
                "查看此资源在该运行中的血缘",
              )}
            </Link>
          )}
        </details>
      </TableCell>
    </TableRow>
  )
}

export default function IPAssets({ projectId }: { projectId: string }) {
  const { t, formatDate } = useI18n()
  const search = useWorkspaceSearch()
  const navigate = useWorkspaceNavigate()
  const page = (search.assets_page ?? 1) - 1
  const selectedResourceId = search.asset_id ?? null
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
    if (page >= pageCount) {
      void navigate({
        search: (prev) => ({
          ...prev,
          assets_page: pageCount > 1 ? pageCount : undefined,
        }),
        replace: true,
      })
    }
  }, [assetsQuery.data, navigate, page])

  if (assetsQuery.isPending)
    return <p role="status">{t("Loading IP Assets…", "正在加载 IP 资产…")}</p>
  if (assetsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>
          {t("IP Assets could not be loaded", "无法加载 IP 资产")}
        </AlertTitle>
        <AlertDescription>
          {t("Please try again later.", "请稍后重试。")}
        </AlertDescription>
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
          <CardTitle id="ip-assets-title">
            {t("IP Assets", "IP 资产")}
          </CardTitle>
          <CardDescription>
            {t(
              `Latest compatible completed Run · ${assets.count} IP Resource${assets.count === 1 ? "" : "s"}`,
              `最近完成的兼容运行 · ${assets.count} 个 IP 资源`,
            )}
            {assets.latest_run_completed_at && (
              <>
                {" "}
                · {t("completed", "完成于")}{" "}
                {formatDate(assets.latest_run_completed_at)}
              </>
            )}
          </CardDescription>
          <details className="min-w-0 text-sm">
            <summary className="cursor-pointer font-medium focus-visible:outline-2">
              {t("View evidence", "查看依据")}
            </summary>
            <dl className="mt-2 min-w-0 space-y-2">
              <div>
                <dt>{t("Project ID", "项目 ID")}</dt>
                <dd>
                  <TechnicalValue value={projectId} />
                </dd>
              </div>
              {assets.latest_run_id && (
                <div>
                  <dt>{t("Published Run", "已发布运行")}</dt>
                  <dd>
                    <TechnicalValue value={assets.latest_run_id} />
                  </dd>
                </div>
              )}
            </dl>
          </details>
        </CardHeader>
        <CardContent className="space-y-4">
          {assets.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t(
                "No IP Resources were observed in the latest compatible Run.",
                "最近一次兼容运行中未观测到 IP 资源。",
              )}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("Canonical IP", "规范化 IP")}</TableHead>
                  <TableHead>{t("Customer side", "客户侧")}</TableHead>
                  <TableHead>{t("CloudAtlas side", "CloudAtlas 侧")}</TableHead>
                  <TableHead>{t("Observations", "观测记录")}</TableHead>
                  <TableHead>{t("Open Finding", "未关闭的发现项")}</TableHead>
                  <TableHead>{t("Details", "详情")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {assets.data.map((asset) => (
                  <AssetRow
                    key={asset.id}
                    asset={asset}
                    projectId={projectId}
                    runId={assets.latest_run_id}
                    onDetails={() =>
                      navigate({
                        search: (prev) => ({
                          ...prev,
                          asset_id: asset.resource_id,
                          asset_page: undefined,
                          investigation_run: assets.latest_run_id ?? undefined,
                        }),
                      })
                    }
                  />
                ))}
              </TableBody>
            </Table>
          )}
          <ResultPagination
            label={t("Assets", "资产")}
            count={assets.count}
            page={page}
            pageSize={PAGE_SIZE}
            onPageChange={(nextPage) =>
              navigate({
                search: (prev) => ({
                  ...prev,
                  assets_page: nextPage > 0 ? nextPage + 1 : undefined,
                }),
              })
            }
          />
        </CardContent>
      </Card>
      <AssetDetailDialog
        projectId={projectId}
        resourceId={selectedResourceId}
        publishedRunId={
          assetsQuery.isSuccess && !assetsQuery.isFetching
            ? assets.latest_run_id
            : null
        }
        onOpenChange={(open) => {
          if (!open) {
            void navigate({
              search: (prev) => ({
                ...prev,
                asset_id: undefined,
                asset_page: undefined,
                investigation_run: undefined,
              }),
            })
          }
        }}
      />
    </section>
  )
}
