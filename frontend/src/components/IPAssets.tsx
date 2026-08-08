import { useQuery } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import {
  type IPAssetDetailPublic,
  type IPAssetPublic,
  IpResultsService,
} from "@/client"
import { ResultPagination } from "@/components/ResultPagination"
import { Stage4ResultNotice } from "@/components/Stage4ResultNotice"
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

function observationStatus(observed: boolean) {
  return (
    <Badge variant={observed ? "default" : "outline"}>
      {observed ? "Present" : "Not observed"}
    </Badge>
  )
}

function findingLabel(findingType: string | null) {
  if (findingType === "UNREPORTED_ASSET") return "Unreported asset"
  if (findingType === "UNOBSERVED_ASSET") return "Unobserved asset"
  return findingType ?? "None"
}

function ObservationRows({ detail }: { detail: IPAssetDetailPublic }) {
  const observations = detail.observations ?? []
  if (observations.length === 0) {
    return <p className="text-sm text-muted-foreground">No observations.</p>
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Raw IP</TableHead>
          <TableHead>Canonical IP</TableHead>
          <TableHead>Source</TableHead>
          <TableHead>Location</TableHead>
          <TableHead>CloudAtlas ID</TableHead>
          <TableHead>CloudAtlas status</TableHead>
          <TableHead>Snapshot</TableHead>
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
  const [page, setPage] = useState(0)
  useEffect(() => {
    if (resourceId !== null) setPage(0)
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
          <DialogTitle>IP Asset details</DialogTitle>
          <DialogDescription>
            Only confirmed source observations and Snapshot references are
            shown. Original artifacts are not exposed here.
          </DialogDescription>
        </DialogHeader>
        {detailQuery.isPending && <p role="status">Loading Asset details…</p>}
        {detailQuery.isError && (
          <Alert variant="destructive">
            <AlertTitle>Asset details could not be loaded</AlertTitle>
            <AlertDescription>Please try again later.</AlertDescription>
          </Alert>
        )}
        {detailQuery.data && (
          <div className="space-y-4">
            <div className="grid gap-3 text-sm md:grid-cols-4">
              <div>
                <p className="font-medium">Canonical IP</p>
                <p className="font-mono">{detailQuery.data.canonical_ip}</p>
              </div>
              <div>
                <p className="font-medium">Customer side</p>
                {observationStatus(detailQuery.data.customer_observed)}
              </div>
              <div>
                <p className="font-medium">CloudAtlas side</p>
                {observationStatus(detailQuery.data.cloudatlas_observed)}
              </div>
              <div>
                <p className="font-medium">Observation count</p>
                <p>{detailQuery.data.observation_count}</p>
              </div>
            </div>
            <ObservationRows detail={detailQuery.data} />
            <ResultPagination
              label="Asset observations"
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
}: {
  asset: IPAssetPublic
  onDetails: () => void
}) {
  return (
    <TableRow>
      <TableCell className="font-mono font-medium">
        {asset.canonical_ip}
      </TableCell>
      <TableCell>{observationStatus(asset.customer_observed)}</TableCell>
      <TableCell>{observationStatus(asset.cloudatlas_observed)}</TableCell>
      <TableCell>
        <div>{asset.observation_count}</div>
        <div className="text-xs text-muted-foreground">
          Customer {asset.customer_observation_count} · CloudAtlas{" "}
          {asset.cloudatlas_observation_count}
        </div>
      </TableCell>
      <TableCell>
        {asset.open_finding_type ? (
          <div>
            <div>{findingLabel(asset.open_finding_type)}</div>
            <div className="font-mono text-xs text-muted-foreground">
              {asset.open_finding_type}
            </div>
          </div>
        ) : (
          <span className="text-muted-foreground">None</span>
        )}
      </TableCell>
      <TableCell>
        <LoadingButton
          type="button"
          variant="outline"
          size="sm"
          onClick={onDetails}
        >
          View details
        </LoadingButton>
      </TableCell>
    </TableRow>
  )
}

export default function IPAssets({ projectId }: { projectId: string }) {
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

  if (assetsQuery.isPending) return <p role="status">Loading IP Assets…</p>
  if (assetsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>IP Assets could not be loaded</AlertTitle>
        <AlertDescription>Please try again later.</AlertDescription>
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
          <CardTitle id="ip-assets-title">IP Assets</CardTitle>
          <CardDescription>
            Latest compatible completed Run · {assets.count} IP Resource
            {assets.count === 1 ? "" : "s"}
            {assets.latest_run_id && (
              <span className="block break-all font-mono text-xs">
                Published Run {assets.latest_run_id}
              </span>
            )}
            {assets.latest_run_completed_at && (
              <>
                {" "}
                · completed{" "}
                {new Date(assets.latest_run_completed_at).toLocaleString()}
              </>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {assets.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No IP Resources were observed in the latest compatible Run.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Canonical IP</TableHead>
                  <TableHead>Customer side</TableHead>
                  <TableHead>CloudAtlas side</TableHead>
                  <TableHead>Observations</TableHead>
                  <TableHead>Open Finding</TableHead>
                  <TableHead>Details</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {assets.data.map((asset) => (
                  <AssetRow
                    key={asset.id}
                    asset={asset}
                    onDetails={() => setSelectedResourceId(asset.resource_id)}
                  />
                ))}
              </TableBody>
            </Table>
          )}
          <ResultPagination
            label="Assets"
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
