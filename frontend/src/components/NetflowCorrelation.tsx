import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  type AddressPublic,
  type AnalysisPublic,
  ApiError,
  CloudatlasLedgerService,
  CloudatlasSourceInstancesService,
  type ContextPublic,
  ExternalAssetsService,
  type FeedbackPublic,
  type NetFlowDatasetPublic,
  NetflowProcessingService,
  NetflowReviewsService,
  type Selection as NetflowSelection,
  ProjectsService,
  type ServicePublic,
  SourceCorrelationsService,
  type SourceState,
  type TaskMaterial,
} from "@/client"
import { NetflowAnalysisActions } from "@/components/NetflowAnalysisActions"
import { NetflowContextForm } from "@/components/NetflowContextForm"
import { NetflowFilters } from "@/components/NetflowFilters"
import { NetflowScopeControl } from "@/components/NetflowScopeControl"
import { NetflowTaskAnswers } from "@/components/NetflowTaskAnswers"
import { ResultPagination } from "@/components/ResultPagination"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import useAuth from "@/hooks/useAuth"
import { useI18n } from "@/lib/i18n"
import {
  netflowErrorCode as errorCode,
  netflowRequestRejected as isClientError,
} from "@/lib/netflow-errors"
import { netflowProtocol, netflowText } from "@/lib/netflow-labels"

function pinnedString(pin: unknown, key: string) {
  if (!pin || typeof pin !== "object" || !(key in pin)) return undefined
  const value = (pin as Record<string, unknown>)[key]
  return typeof value === "string" ? value : undefined
}

function fixedInputSearch(
  selection: NetflowSelection,
  pins: Record<string, unknown>,
): Partial<NetflowCorrelationSearch> {
  const cloud = selection.cloud
  const cloudPin = pins.CLOUD
  return {
    dataset: pinnedString(pins.NETFLOW, "dataset_id"),
    context: pinnedString(pins.NETFLOW, "context_revision_id"),
    analysis: selection.netflow?.analysis_id,
    namespace: selection.network_namespace,
    customerUpload: selection.customer?.upload_id,
    customerRevision: selection.customer?.revision_id ?? undefined,
    customerOriginal:
      selection.customer?.revision_id === null ? true : undefined,
    historyRun: selection.history_run_id ?? undefined,
    cloudMode:
      cloud?.kind === "legacy_snapshot"
        ? "legacy"
        : cloud?.kind === "external_versions"
          ? "external"
          : "none",
    cloudSnapshot:
      cloud?.kind === "legacy_snapshot" ? cloud.source_snapshot_id : undefined,
    cloudLedgerRevision:
      cloud?.kind === "legacy_snapshot" ? cloud.ledger_revision : undefined,
    cloudScopeRevision:
      cloud?.kind === "legacy_snapshot" ? cloud.scope_revision : undefined,
    cloudSource:
      cloud?.kind === "external_versions"
        ? cloud.source_instance_id
        : pinnedString(cloudPin, "source_instance_id"),
    cloudIpVersion:
      cloud?.kind === "external_versions"
        ? (cloud.ip_version_id ?? undefined)
        : undefined,
    cloudPortVersion:
      cloud?.kind === "external_versions"
        ? (cloud.port_version_id ?? undefined)
        : undefined,
  }
}

const PAGE_SIZE = 25
const COMPARISON_SIZE = 25
const TABS = ["summary", "addresses", "peers", "tasks"] as const
type Tab = (typeof TABS)[number]
export type NetflowCorrelationSearch = {
  dataset?: string
  context?: string
  analysis?: string
  revision?: string
  namespace?: string
  customerUpload?: string
  customerRevision?: string
  customerOriginal?: boolean
  historyRun?: string
  cloudMode?: "none" | "legacy" | "external"
  cloudSnapshot?: string
  cloudLedgerRevision?: number
  cloudScopeRevision?: number
  cloudSource?: string
  cloudIpVersion?: string
  cloudPortVersion?: string
  tab?: Tab
  taskId?: string
  addressKey?: string
  addressIp?: string
  addressPage?: number
  servicePage?: number
  peerPage?: number
  taskPage?: number
  taskStatus?: TaskMaterial["material_status"]
  feedbackRevision?: string
  evidencePage?: number
  evidenceSource?: "customer" | "cloud" | "netflow"
  comparisonPage?: number
  comparison?: "all" | "differences" | "common"
  positiveSources?: string
  unmatchedNetflow?: boolean
  hasReviewTask?: boolean
  sort?: "ip_asc" | "ip_desc"
  peerIp?: string
  peerProtocol?: number
  peerPort?: number
  taskScope?: "object" | "dataset"
  taskKind?: string
  objectKey?: string
  identityErrors?: string[]
}

type Navigate = (options: {
  search: (previous: NetflowCorrelationSearch) => NetflowCorrelationSearch
  replace?: boolean
}) => Promise<void>

const count = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : String(value)

function servicePortText(
  service: ServicePublic,
  t: (en: string, zh: string) => string,
) {
  if (service.source === "CUSTOMER") {
    const fields = service.original.fields
    const start =
      fields && typeof fields === "object" && "start_port" in fields
        ? fields.start_port
        : undefined
    const end =
      fields && typeof fields === "object" && "end_port" in fields
        ? fields.end_port
        : undefined
    return `${t("Customer declared range", "客户声明端口区间")}: ${count(typeof start === "number" ? start : null)}–${count(typeof end === "number" ? end : null)}`
  }
  return `${service.source === "NETFLOW" ? t("Flow source-side port", "流量源侧观测端口") : t("CloudAtlas recorded port", "云图端口记录")}: ${count(service.local_port)}`
}

const COMBINED_READS = [
  "summary",
  "addresses",
  "address",
  "services",
  "evidence",
]

function SelectorPage({
  label,
  page,
  hasNext,
  onPage,
}: {
  label: string
  page: number
  hasNext: boolean
  onPage: (page: number) => void
}) {
  return (
    <span className="flex items-center gap-1 text-xs text-muted-foreground">
      {label} {page + 1}
      <Button
        variant="outline"
        size="sm"
        aria-label={`${label} previous page`}
        disabled={!page}
        onClick={() => onPage(page - 1)}
      >
        ←
      </Button>
      <Button
        variant="outline"
        size="sm"
        aria-label={`${label} next page`}
        disabled={!hasNext}
        onClick={() => onPage(page + 1)}
      >
        →
      </Button>
    </span>
  )
}

function useScopeCleanup(scope: string) {
  const cache = useQueryClient()
  const previous = useRef(scope)
  const [denied, setDenied] = useState<{
    scope: string
    errors: Record<string, ApiError>
  }>()
  useEffect(
    () =>
      cache.getQueryCache().subscribe((event) => {
        const query = event.query
        const error = query.state.error
        if (
          event.type !== "updated" ||
          event.action.type !== "error" ||
          query.queryKey[0] !== "netflow-correlation" ||
          query.queryKey[1] !== scope ||
          !(error instanceof ApiError) ||
          ![401, 403, 404, 410].includes(error.status)
        )
          return
        const kind = String(query.queryKey[2])
        const wholeScope =
          error.status === 401 ||
          (kind === "summary" && error.status === 404) ||
          (kind === "external-sources" && [403, 404].includes(error.status))
        const affected = COMBINED_READS.includes(kind) ? COMBINED_READS : [kind]
        setDenied((previous) => ({
          scope,
          errors: {
            ...(previous?.scope === scope ? previous.errors : {}),
            ...Object.fromEntries(
              (wholeScope ? ["scopeAccess"] : affected).map((name) => [
                name,
                error,
              ]),
            ),
          },
        }))
        const filters = {
          predicate: (item: typeof query) =>
            item.queryKey[0] === "netflow-correlation" &&
            item.queryKey[1] === scope &&
            (wholeScope || affected.includes(String(item.queryKey[2]))),
        }
        void cache.cancelQueries(filters)
        cache.removeQueries(filters)
      }),
    [cache, scope],
  )
  useEffect(() => {
    const oldScope = previous.current
    if (oldScope !== scope) {
      void cache.cancelQueries({
        predicate: (query) =>
          query.queryKey[0] === "netflow-correlation" &&
          query.queryKey[1] === oldScope,
      })
      cache.removeQueries({
        predicate: (query) =>
          query.queryKey[0] === "netflow-correlation" &&
          query.queryKey[1] === oldScope,
      })
      previous.current = scope
    }
    return () => {
      void cache.cancelQueries({
        predicate: (query) =>
          query.queryKey[0] === "netflow-correlation" &&
          query.queryKey[1] === scope,
      })
      cache.removeQueries({
        predicate: (query) =>
          query.queryKey[0] === "netflow-correlation" &&
          query.queryKey[1] === scope,
      })
    }
  }, [cache, scope])
  return denied?.scope === scope ? denied.errors : {}
}

function StateText({ state }: { state: string | undefined }) {
  const { t } = useI18n()
  return (
    <span>{state ? netflowText(state, t) : t("Not selected", "未选择")}</span>
  )
}

function Technical({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === undefined || value === "") return null
  return (
    <details className="min-w-0">
      <summary className="cursor-pointer text-sm text-muted-foreground">
        {label}
      </summary>
      <code className="mt-1 block max-w-full whitespace-pre-wrap break-all text-xs">
        {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
      </code>
    </details>
  )
}

export default function NetflowCorrelation({
  actor,
  projectId,
  search,
  navigate,
}: {
  actor: string
  projectId: string
  search: NetflowCorrelationSearch
  navigate: Navigate
}) {
  const { t, formatDate } = useI18n()
  const { user } = useAuth()
  const scope = JSON.stringify([
    actor,
    projectId,
    search.dataset,
    search.context,
    search.analysis,
    search.revision,
    search.namespace,
    search.customerUpload,
    search.customerRevision,
    search.customerOriginal,
    search.historyRun,
    search.cloudMode,
    search.cloudSnapshot,
    search.cloudLedgerRevision,
    search.cloudScopeRevision,
    search.cloudSource,
    search.cloudIpVersion,
    search.cloudPortVersion,
  ])
  const readErrors = useScopeCleanup(scope)
  const accessError = readErrors.scopeAccess ?? readErrors.summary
  const identityError = Boolean(search.identityErrors?.length)
  const readable = (kind: string) => !accessError && !readErrors[kind]
  const independentInput = useRef<
    Partial<NetflowCorrelationSearch> | undefined
  >(
    search.dataset && search.context && search.analysis && search.namespace
      ? {
          dataset: search.dataset,
          context: search.context,
          analysis: search.analysis,
          namespace: search.namespace,
        }
      : undefined,
  )
  const scopeRef = useRef(scope)
  scopeRef.current = accessError ? "denied" : scope
  useEffect(() => {
    scopeRef.current = scope
    return () => {
      scopeRef.current = "unmounted"
    }
  }, [scope])
  const tab = search.tab ?? "summary"
  const [notice, setNotice] = useState<[string, string]>()
  const [datasetPage, setDatasetPage] = useState(0)
  const [contextPage, setContextPage] = useState(0)
  const [analysisPage, setAnalysisPage] = useState(0)
  const [uploadPage, setUploadPage] = useState(0)
  const [snapshotPage, setSnapshotPage] = useState(0)
  const [versionPage, setVersionPage] = useState(0)
  const [correlationPage, setCorrelationPage] = useState(0)
  const [addressQuery, setAddressQuery] = useState(search.addressIp ?? "")
  const [namespace, setNamespace] = useState(search.namespace ?? "")
  const [pendingKey, setPendingKey] = useState<string>()
  const correlationStore = `exposure:netflow-correlation:${scope}`

  const datasets = useQuery({
    queryKey: ["netflow-correlation", scope, "datasets", datasetPage],
    enabled: readable("datasets") && !identityError,
    queryFn: () =>
      ProjectsService.readNetflowDatasets({
        projectId,
        skip: datasetPage * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
    retry: false,
    staleTime: 0,
  })
  const contexts = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "contexts",
      search.dataset,
      contextPage,
    ],
    enabled: readable("contexts") && Boolean(search.dataset) && !identityError,
    queryFn: () =>
      NetflowProcessingService.readContexts({
        projectId,
        datasetId: search.dataset!,
        skip: contextPage * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
    retry: false,
    staleTime: 0,
  })
  const currentContextId = contexts.data?.data[0]?.current_context_revision_id
  const currentContext = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "current-context",
      search.dataset,
      currentContextId,
    ],
    enabled:
      readable("current-context") &&
      Boolean(search.dataset && currentContextId) &&
      !identityError,
    queryFn: () =>
      NetflowProcessingService.readContexts({
        projectId,
        datasetId: search.dataset!,
        contextRevisionId: currentContextId!,
        limit: 1,
      }),
    retry: false,
    staleTime: 0,
  })
  const analyses = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "analyses",
      search.dataset,
      analysisPage,
    ],
    enabled: readable("analyses") && Boolean(search.dataset) && !identityError,
    queryFn: () =>
      NetflowProcessingService.readAnalyses({
        projectId,
        datasetId: search.dataset!,
        skip: analysisPage * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
    retry: false,
    staleTime: 0,
    refetchInterval: (query) =>
      readable("analyses") &&
      query.state.data?.data.some(
        (item) =>
          item.analysis_id === search.analysis &&
          ["PENDING", "RUNNING", "UNKNOWN"].includes(item.status),
      )
        ? 5000
        : false,
  })
  const uploads = useQuery({
    queryKey: ["netflow-correlation", scope, "customer-uploads", uploadPage],
    enabled: readable("customer-uploads") && !identityError,
    queryFn: () =>
      ProjectsService.readCustomerUploads({
        projectId,
        skip: uploadPage * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
    retry: false,
    staleTime: 0,
  })
  const legacySources = useQuery({
    queryKey: ["netflow-correlation", scope, "legacy-sources"],
    enabled: readable("legacy-sources") && !identityError,
    queryFn: () =>
      CloudatlasSourceInstancesService.readCloudatlasSources({ projectId }),
    retry: false,
    staleTime: 0,
  })
  const legacySourceId =
    search.cloudMode === "legacy" && search.cloudSource
      ? search.cloudSource
      : legacySources.data?.data.filter(
            (source) => source.source_type === "cloudatlas",
          ).length === 1
        ? legacySources.data.data.find(
            (source) => source.source_type === "cloudatlas",
          )?.id
        : undefined
  const snapshots = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "legacy-snapshots",
      legacySourceId,
      snapshotPage,
    ],
    enabled:
      readable("legacy-snapshots") && Boolean(legacySourceId) && !identityError,
    queryFn: () =>
      CloudatlasLedgerService.readCloudatlasLedgerSnapshots({
        projectId,
        sourceId: legacySourceId!,
        skip: snapshotPage * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
    retry: false,
    staleTime: 0,
  })
  const sources = useQuery({
    queryKey: ["netflow-correlation", scope, "external-sources"],
    enabled: readable("external-sources") && !identityError,
    queryFn: () => ExternalAssetsService.readExternalSources({ projectId }),
    retry: false,
    staleTime: 0,
    refetchInterval: readable("external-sources") ? 5000 : false,
  })
  const assetSource = sources.data?.data.find(
    (source) =>
      source.id === search.cloudSource &&
      source.capability_profile === "assets-v1",
  )
  const canWrite =
    sources.isSuccess && !sources.isError && sources.data.can_manage
  const externalVersions = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "external-versions",
      assetSource?.id,
      versionPage,
    ],
    enabled:
      readable("external-versions") && Boolean(assetSource) && !identityError,
    queryFn: async () => {
      const [ip, port] = await Promise.all([
        ExternalAssetsService.readExternalVersions({
          projectId,
          sourceId: assetSource!.id,
          domain: "ip",
          skip: versionPage * PAGE_SIZE,
          limit: PAGE_SIZE,
        }),
        ExternalAssetsService.readExternalVersions({
          projectId,
          sourceId: assetSource!.id,
          domain: "port",
          skip: versionPage * PAGE_SIZE,
          limit: PAGE_SIZE,
        }),
      ])
      return { ip, port }
    },
    retry: false,
    staleTime: 0,
  })
  const correlations = useQuery({
    enabled: readable("correlations") && !search.revision && !identityError,
    queryKey: [
      "netflow-correlation",
      scope,
      "correlations",
      search.dataset,
      search.namespace,
      correlationPage,
    ],
    queryFn: () =>
      SourceCorrelationsService.listCorrelations({
        projectId,
        datasetId: search.dataset,
        networkNamespace: search.namespace,
        skip: correlationPage * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
    retry: false,
    staleTime: 0,
  })
  const fixedDataset = useQuery({
    queryKey: ["netflow-correlation", scope, "fixed-dataset", search.dataset],
    enabled:
      readable("fixed-dataset") && Boolean(search.dataset) && !identityError,
    queryFn: () =>
      ProjectsService.readNetflowDatasets({
        projectId,
        datasetId: search.dataset!,
        limit: 1,
      }),
    retry: false,
  })
  const fixedContext = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "fixed-context",
      search.dataset,
      search.context,
    ],
    enabled:
      readable("fixed-context") &&
      Boolean(search.dataset && search.context) &&
      !identityError,
    queryFn: () =>
      NetflowProcessingService.readContexts({
        projectId,
        datasetId: search.dataset!,
        contextRevisionId: search.context!,
        limit: 1,
      }),
    retry: false,
  })
  const fixedAnalysis = useQuery({
    queryKey: ["netflow-correlation", scope, "fixed-analysis", search.analysis],
    enabled:
      readable("fixed-analysis") && Boolean(search.analysis) && !identityError,
    queryFn: () =>
      NetflowProcessingService.readAnalysis({
        projectId,
        analysisId: search.analysis!,
      }),
    retry: false,
    refetchInterval: (query) =>
      readable("fixed-analysis") &&
      query.state.data &&
      ["PENDING", "RUNNING", "UNKNOWN"].includes(query.state.data.status)
        ? 5000
        : false,
  })
  const fixedUpload = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "fixed-upload",
      search.customerUpload,
    ],
    enabled:
      readable("fixed-upload") &&
      Boolean(search.customerUpload) &&
      !identityError,
    queryFn: () =>
      ProjectsService.readCustomerUploads({
        projectId,
        uploadId: search.customerUpload!,
        limit: 1,
      }),
    retry: false,
  })
  const fixedSnapshot = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "fixed-snapshot",
      legacySourceId,
      search.cloudSnapshot,
    ],
    enabled:
      readable("fixed-snapshot") &&
      Boolean(legacySourceId && search.cloudSnapshot) &&
      !identityError,
    queryFn: () =>
      CloudatlasLedgerService.readCloudatlasLedgerSnapshots({
        projectId,
        sourceId: legacySourceId!,
        snapshotId: search.cloudSnapshot!,
        limit: 1,
      }),
    retry: false,
  })
  const fixedExternalVersions = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "fixed-external-versions",
      search.cloudSource,
      search.cloudIpVersion,
      search.cloudPortVersion,
    ],
    enabled:
      readable("fixed-external-versions") &&
      Boolean(
        search.cloudSource &&
          (search.cloudIpVersion || search.cloudPortVersion),
      ) &&
      !identityError,
    queryFn: async () => {
      const read = (domain: "ip" | "port", versionId?: string) =>
        versionId
          ? ExternalAssetsService.readExternalVersions({
              projectId,
              sourceId: search.cloudSource!,
              domain,
              versionId,
              limit: 1,
            })
          : Promise.resolve(undefined)
      const [ip, port] = await Promise.all([
        read("ip", search.cloudIpVersion),
        read("port", search.cloudPortVersion),
      ])
      return { ip, port }
    },
    retry: false,
  })
  const selectedDataset =
    fixedDataset.data?.data[0] ??
    datasets.data?.data.find((dataset) => dataset.id === search.dataset)
  const selectedContext =
    fixedContext.data?.data[0] ??
    contexts.data?.data.find(
      (context) => context.context_revision_id === search.context,
    )
  const authoritativeCurrentContext =
    currentContext.data?.data[0] ??
    (selectedContext?.current_context_revision_id ===
    selectedContext?.context_revision_id
      ? selectedContext
      : undefined)
  const selectedAnalysis =
    fixedAnalysis.data ??
    analyses.data?.data.find(
      (analysis) => analysis.analysis_id === search.analysis,
    )
  const selectedUpload =
    fixedUpload.data?.data[0] ??
    uploads.data?.data.find((upload) => upload.id === search.customerUpload)
  const summary = useQuery({
    queryKey: ["netflow-correlation", scope, "summary", search.revision],
    enabled: Boolean(search.revision) && !accessError && !identityError,
    queryFn: () =>
      SourceCorrelationsService.summary({
        projectId,
        revisionId: search.revision!,
      }),
    retry: false,
    staleTime: 0,
    refetchInterval: accessError ? false : 5000,
  })
  const netflowPin = summary.data?.pins.NETFLOW
  const pinnedCloudMode =
    summary.data?.selection.cloud?.kind === "legacy_snapshot"
      ? "legacy"
      : summary.data?.selection.cloud?.kind === "external_versions"
        ? "external"
        : "none"
  const pinnedCustomer = summary.data?.selection.customer
  const pinnedCloud = summary.data?.selection.cloud
  const identityMatches = Boolean(
    summary.data &&
      summary.data.project_id === projectId &&
      summary.data.correlation_revision_id === search.revision &&
      (!search.namespace ||
        summary.data.network_namespace === search.namespace) &&
      (!search.analysis ||
        summary.data.selection.netflow?.analysis_id === search.analysis) &&
      (!search.dataset ||
        (netflowPin &&
          typeof netflowPin === "object" &&
          "dataset_id" in netflowPin &&
          netflowPin.dataset_id === search.dataset)) &&
      (!search.context ||
        (netflowPin &&
          typeof netflowPin === "object" &&
          "context_revision_id" in netflowPin &&
          netflowPin.context_revision_id === search.context)) &&
      (!search.customerUpload ||
        pinnedCustomer?.upload_id === search.customerUpload) &&
      (!search.customerRevision ||
        pinnedCustomer?.revision_id === search.customerRevision) &&
      (search.customerOriginal === undefined ||
        (search.customerOriginal === true &&
          pinnedCustomer?.revision_id === null)) &&
      (!search.historyRun ||
        summary.data.selection.history_run_id === search.historyRun) &&
      (!search.cloudMode || pinnedCloudMode === search.cloudMode) &&
      (!search.cloudSnapshot ||
        (pinnedCloud?.kind === "legacy_snapshot" &&
          pinnedCloud.source_snapshot_id === search.cloudSnapshot)) &&
      (search.cloudLedgerRevision === undefined ||
        (pinnedCloud?.kind === "legacy_snapshot" &&
          pinnedCloud.ledger_revision === search.cloudLedgerRevision)) &&
      (search.cloudScopeRevision === undefined ||
        (pinnedCloud?.kind === "legacy_snapshot" &&
          pinnedCloud.scope_revision === search.cloudScopeRevision)) &&
      (!search.cloudSource ||
        (pinnedCloud?.kind === "external_versions"
          ? pinnedCloud.source_instance_id === search.cloudSource
          : pinnedString(summary.data?.pins.CLOUD, "source_instance_id") ===
            search.cloudSource)) &&
      (!search.cloudIpVersion ||
        (pinnedCloud?.kind === "external_versions" &&
          pinnedCloud.ip_version_id === search.cloudIpVersion)) &&
      (!search.cloudPortVersion ||
        (pinnedCloud?.kind === "external_versions" &&
          pinnedCloud.port_version_id === search.cloudPortVersion)),
  )
  const revisionIdentity =
    identityMatches && !summary.isError && !accessError
      ? summary.data
      : undefined
  const pinnedInputSearch = useMemo(
    () =>
      revisionIdentity
        ? fixedInputSearch(revisionIdentity.selection, revisionIdentity.pins)
        : undefined,
    [revisionIdentity],
  )
  useEffect(() => {
    if (!search.revision || !pinnedInputSearch || identityError) return
    const changed = Object.entries(pinnedInputSearch).some(
      ([key, value]) => search[key as keyof NetflowCorrelationSearch] !== value,
    )
    if (changed) {
      void navigate({
        replace: true,
        search: (previous) => ({ ...previous, ...pinnedInputSearch }),
      })
    }
  }, [identityError, navigate, pinnedInputSearch, search, search.revision])
  const revisionId = revisionIdentity?.correlation_revision_id
  const independentAnalysis =
    !search.revision &&
    selectedAnalysis &&
    selectedContext &&
    selectedAnalysis.dataset_id === search.dataset &&
    selectedAnalysis.context_revision_id ===
      selectedContext.context_revision_id &&
    selectedAnalysis.network_namespace === search.namespace
      ? selectedAnalysis
      : undefined
  const selectedAnalysisId =
    revisionIdentity?.selection.netflow?.analysis_id ??
    independentAnalysis?.analysis_id
  const analysisIdentity = {
    dataset:
      revisionIdentity && netflowPin
        ? pinnedString(netflowPin, "dataset_id")
        : search.dataset,
    context:
      revisionIdentity && netflowPin
        ? pinnedString(netflowPin, "context_revision_id")
        : search.context,
    namespace: revisionIdentity?.network_namespace ?? search.namespace,
  }
  const matchesAnalysisIdentity = useCallback(
    (value: {
      project_id: string
      analysis_id: string
      dataset_id: string
      context_revision_id: string
      network_namespace: string
    }) =>
      value.project_id === projectId &&
      value.analysis_id === selectedAnalysisId &&
      value.dataset_id === analysisIdentity.dataset &&
      value.context_revision_id === analysisIdentity.context &&
      value.network_namespace === analysisIdentity.namespace,
    [
      analysisIdentity.context,
      analysisIdentity.dataset,
      analysisIdentity.namespace,
      projectId,
      selectedAnalysisId,
    ],
  )
  if (
    revisionIdentity?.selection.netflow &&
    netflowPin &&
    typeof netflowPin === "object" &&
    "dataset_id" in netflowPin &&
    typeof netflowPin.dataset_id === "string" &&
    "context_revision_id" in netflowPin &&
    typeof netflowPin.context_revision_id === "string"
  ) {
    independentInput.current = {
      dataset: netflowPin.dataset_id,
      context: netflowPin.context_revision_id,
      analysis: revisionIdentity.selection.netflow.analysis_id,
      namespace: revisionIdentity.network_namespace,
    }
  }
  const addresses = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "addresses",
      revisionId,
      search.addressIp,
      search.addressPage,
      search.positiveSources,
      search.comparison,
      search.unmatchedNetflow,
      search.hasReviewTask,
      search.sort,
      summary.data?.current_scope_state,
    ],
    enabled: Boolean(revisionId) && tab === "addresses",
    queryFn: () =>
      SourceCorrelationsService.listAddresses({
        projectId,
        revisionId: revisionId!,
        ip: search.addressIp,
        positiveSources: search.positiveSources,
        comparison: search.comparison ?? "all",
        unmatchedNetflow: search.unmatchedNetflow,
        hasReviewTask: search.hasReviewTask,
        skip: (search.addressPage ?? 0) * PAGE_SIZE,
        limit: PAGE_SIZE,
        sort: search.sort ?? "ip_asc",
      }),
    retry: false,
    staleTime: 0,
  })
  const addressDetail = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "address",
      revisionId,
      search.addressKey,
    ],
    enabled: Boolean(revisionId && search.addressKey && tab === "addresses"),
    queryFn: () =>
      SourceCorrelationsService.addressDetail({
        projectId,
        revisionId: revisionId!,
        addressKey: search.addressKey!,
      }),
    retry: false,
    staleTime: 0,
  })
  const services = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "services",
      revisionId,
      search.addressKey,
      search.servicePage,
      search.comparisonPage,
    ],
    enabled: Boolean(revisionId && search.addressKey && tab === "addresses"),
    queryFn: () =>
      SourceCorrelationsService.addressServices({
        projectId,
        revisionId: revisionId!,
        addressKey: search.addressKey!,
        skip: (search.servicePage ?? 0) * PAGE_SIZE,
        limit: PAGE_SIZE,
        comparisonSkip: (search.comparisonPage ?? 0) * COMPARISON_SIZE,
        comparisonLimit: COMPARISON_SIZE,
      }),
    retry: false,
    staleTime: 0,
  })
  const evidence = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "evidence",
      revisionId,
      search.addressKey,
      search.evidenceSource,
      search.evidencePage,
    ],
    enabled: Boolean(
      revisionId &&
        search.addressKey &&
        tab === "addresses" &&
        search.evidenceSource,
    ),
    queryFn: () =>
      SourceCorrelationsService.addressEvidence({
        projectId,
        revisionId: revisionId!,
        addressKey: search.addressKey!,
        source: search.evidenceSource!,
        skip: (search.evidencePage ?? 0) * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
    retry: false,
    staleTime: 0,
  })
  const peers = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "peers",
      selectedAnalysisId,
      search.peerPage,
      search.peerIp,
      search.peerProtocol,
      search.peerPort,
      search.sort,
    ],
    enabled:
      readable("peers") && Boolean(selectedAnalysisId && tab === "peers"),
    queryFn: () =>
      NetflowReviewsService.readPeers({
        projectId,
        analysisId: selectedAnalysisId!,
        ip: search.peerIp,
        protocol: search.peerProtocol,
        peerPort: search.peerPort,
        skip: (search.peerPage ?? 0) * PAGE_SIZE,
        limit: PAGE_SIZE,
        sort: search.sort ?? "ip_asc",
      }),
    retry: false,
    staleTime: 0,
  })
  const latestFeedback = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "current-feedback",
      selectedAnalysisId,
    ],
    enabled:
      readable("current-feedback") &&
      Boolean(selectedAnalysisId && tab === "tasks"),
    queryFn: () =>
      NetflowReviewsService.readFeedback({
        projectId,
        analysisId: selectedAnalysisId!,
      }),
    retry: false,
    staleTime: 0,
    refetchInterval: readable("current-feedback") ? 5000 : false,
  })
  const feedbackValidation = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "feedback-validation",
      selectedAnalysisId,
      search.feedbackRevision,
    ],
    enabled:
      readable("feedback-validation") &&
      Boolean(selectedAnalysisId && search.feedbackRevision),
    queryFn: () =>
      NetflowReviewsService.readFeedback({
        projectId,
        analysisId: selectedAnalysisId!,
        feedbackRevisionId: search.feedbackRevision!,
      }),
    retry: false,
    staleTime: 0,
  })
  const feedback = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "feedback",
      selectedAnalysisId,
      search.feedbackRevision,
    ],
    enabled:
      readable("feedback") &&
      Boolean(selectedAnalysisId && search.feedbackRevision && tab === "tasks"),
    queryFn: () =>
      NetflowReviewsService.readFeedback({
        projectId,
        analysisId: selectedAnalysisId!,
        feedbackRevisionId: search.feedbackRevision,
      }),
    retry: false,
    staleTime: 0,
  })
  useEffect(() => {
    if (
      latestFeedback.data?.feedback_revision_id &&
      matchesAnalysisIdentity(latestFeedback.data) &&
      !search.feedbackRevision
    ) {
      void navigate({
        replace: true,
        search: (previous) => ({
          ...previous,
          feedbackRevision: latestFeedback.data!.feedback_revision_id,
          taskPage: 0,
        }),
      })
    }
  }, [
    latestFeedback.data,
    matchesAnalysisIdentity,
    navigate,
    search.feedbackRevision,
  ])
  const tasks = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "tasks",
      selectedAnalysisId,
      search.feedbackRevision,
      search.taskPage,
      search.taskStatus,
      search.taskScope,
      search.taskKind,
      search.objectKey,
    ],
    enabled:
      readable("tasks") &&
      Boolean(selectedAnalysisId && search.feedbackRevision && tab === "tasks"),
    queryFn: () =>
      NetflowReviewsService.readTasks({
        projectId,
        analysisId: selectedAnalysisId!,
        feedbackRevisionId: search.feedbackRevision!,
        skip: (search.taskPage ?? 0) * PAGE_SIZE,
        limit: PAGE_SIZE,
        materialStatus: search.taskStatus,
        taskScope: search.taskScope,
        taskKind: search.taskKind,
        objectKey: search.objectKey,
      }),
    retry: false,
    staleTime: 0,
  })
  const task = useQuery({
    queryKey: [
      "netflow-correlation",
      scope,
      "task",
      selectedAnalysisId,
      search.feedbackRevision,
      search.taskId,
    ],
    enabled:
      readable("task") &&
      Boolean(
        selectedAnalysisId &&
          search.feedbackRevision &&
          search.taskId &&
          tab === "tasks",
      ),
    queryFn: () =>
      NetflowReviewsService.readTask({
        projectId,
        analysisId: selectedAnalysisId!,
        feedbackRevisionId: search.feedbackRevision!,
        taskId: search.taskId!,
      }),
    retry: false,
    staleTime: 0,
  })
  const feedbackMatches =
    !feedback.data ||
    (matchesAnalysisIdentity(feedback.data) &&
      feedback.data.feedback_revision_id === search.feedbackRevision)
  const latestFeedbackMatches =
    !latestFeedback.data || matchesAnalysisIdentity(latestFeedback.data)
  const tasksMatch =
    !tasks.data ||
    (matchesAnalysisIdentity(tasks.data) &&
      tasks.data.feedback_revision_id === search.feedbackRevision)
  const taskMatches =
    !task.data ||
    (matchesAnalysisIdentity(task.data) &&
      task.data.feedback_revision_id === search.feedbackRevision)
  const feedbackIdentityError =
    feedbackMatches && latestFeedbackMatches && tasksMatch && taskMatches
      ? undefined
      : new Error("fixed_analysis_identity_mismatch")
  const explicitFeedbackMismatch =
    Boolean(search.feedbackRevision) &&
    (!feedbackValidation.data ||
      !matchesAnalysisIdentity(feedbackValidation.data) ||
      feedbackValidation.data.feedback_revision_id !== search.feedbackRevision)
  const identityReady = Boolean(
    (!search.dataset && !search.analysis && namespace.trim()) ||
      (selectedContext &&
        selectedAnalysis &&
        selectedAnalysis.context_revision_id ===
          selectedContext.context_revision_id &&
        namespace.trim() === selectedContext.network_namespace),
  )
  const selectedCloud = useMemo(() => {
    if (
      search.cloudMode === "legacy" &&
      search.cloudSnapshot &&
      search.cloudLedgerRevision !== undefined &&
      search.cloudScopeRevision !== undefined
    ) {
      const snapshot =
        fixedSnapshot.isSuccess && !fixedSnapshot.isError
          ? fixedSnapshot.data?.[0]
          : undefined
      return snapshot?.id === search.cloudSnapshot &&
        (!search.cloudSource ||
          snapshot.source_instance_id === search.cloudSource)
        ? {
            kind: "legacy_snapshot" as const,
            source_snapshot_id: snapshot.id,
            ledger_revision: search.cloudLedgerRevision,
            scope_revision: search.cloudScopeRevision,
          }
        : null
    }
    if (
      search.cloudMode === "external" &&
      search.cloudSource &&
      (search.cloudIpVersion || search.cloudPortVersion)
    ) {
      const ipReady =
        !search.cloudIpVersion ||
        (fixedExternalVersions.isSuccess &&
          !fixedExternalVersions.isError &&
          fixedExternalVersions.data?.ip?.data[0]?.status !== "EXPIRED" &&
          fixedExternalVersions.data?.ip?.data[0]?.id ===
            search.cloudIpVersion &&
          fixedExternalVersions.data.ip.data[0]?.source_id ===
            search.cloudSource)
      const portReady =
        !search.cloudPortVersion ||
        (fixedExternalVersions.isSuccess &&
          !fixedExternalVersions.isError &&
          fixedExternalVersions.data?.port?.data[0]?.status !== "EXPIRED" &&
          fixedExternalVersions.data?.port?.data[0]?.id ===
            search.cloudPortVersion &&
          fixedExternalVersions.data.port.data[0]?.source_id ===
            search.cloudSource)
      if (!ipReady || !portReady) return null
      return {
        kind: "external_versions" as const,
        source_instance_id: search.cloudSource,
        ip_version_id: search.cloudIpVersion ?? null,
        port_version_id: search.cloudPortVersion ?? null,
      }
    }
    return null
  }, [
    search.cloudIpVersion,
    search.cloudLedgerRevision,
    search.cloudMode,
    search.cloudPortVersion,
    search.cloudScopeRevision,
    search.cloudSnapshot,
    search.cloudSource,
    fixedSnapshot.data,
    fixedSnapshot.isSuccess,
    fixedSnapshot.isError,
    fixedExternalVersions.data,
    fixedExternalVersions.isSuccess,
    fixedExternalVersions.isError,
  ])
  const hasExplicitCloudIdentity = Boolean(
    search.cloudSnapshot ||
      search.cloudLedgerRevision !== undefined ||
      search.cloudScopeRevision !== undefined ||
      search.cloudSource ||
      search.cloudIpVersion ||
      search.cloudPortVersion,
  )
  const cloudSelectionReady =
    search.cloudMode === undefined ||
    search.cloudMode === "none" ||
    (search.cloudMode === "legacy" && Boolean(selectedCloud)) ||
    (search.cloudMode === "external" && Boolean(selectedCloud))
  const hasSource = Boolean(
    search.analysis || search.customerUpload || selectedCloud,
  )
  const creationIdentityInvalid =
    (!search.customerUpload &&
      (search.customerRevision !== undefined ||
        search.customerOriginal !== undefined)) ||
    (search.customerOriginal === true &&
      search.customerRevision !== undefined) ||
    (!search.cloudMode && hasExplicitCloudIdentity) ||
    (search.cloudMode === "none" && hasExplicitCloudIdentity) ||
    (search.cloudMode !== "legacy" &&
      Boolean(
        search.cloudSnapshot ||
          search.cloudLedgerRevision !== undefined ||
          search.cloudScopeRevision !== undefined,
      )) ||
    (search.cloudMode !== "external" &&
      Boolean(search.cloudIpVersion || search.cloudPortVersion))
  const createSelection = async () => {
    setNotice(undefined)
    if (
      search.revision ||
      creationIdentityInvalid ||
      !canWrite ||
      pendingKey ||
      !hasSource ||
      !identityReady ||
      !cloudSelectionReady
    ) {
      if (creationIdentityInvalid) {
        setNotice([
          "The explicit source identity is incomplete or conflicts with its mode.",
          "明确来源身份不完整或与其模式冲突。",
        ])
      }
      return
    }
    const capturedScope = scope
    const body = {
      network_namespace: namespace.trim(),
      customer: search.customerUpload
        ? {
            upload_id: search.customerUpload,
            revision_id: search.customerOriginal
              ? null
              : (search.customerRevision ?? null),
          }
        : null,
      cloud: selectedCloud,
      netflow: search.analysis ? { analysis_id: search.analysis } : null,
      history_run_id: search.historyRun ?? null,
    }
    const key = crypto.randomUUID()
    try {
      sessionStorage.setItem(correlationStore, JSON.stringify({ key, body }))
    } catch {
      setNotice(["Recovery storage is unavailable.", "恢复存储不可用。"])
      return
    }
    setPendingKey(key)
    try {
      const revision = await SourceCorrelationsService.createCorrelation({
        projectId,
        idempotencyKey: key,
        requestBody: body,
      })
      if (scopeRef.current !== capturedScope) return
      sessionStorage.removeItem(correlationStore)
      setPendingKey(undefined)
      await navigate({
        search: (previous) => ({
          ...previous,
          namespace: body.network_namespace,
          revision: revision.correlation_revision_id,
          feedbackRevision: undefined,
          taskId: undefined,
          addressKey: undefined,
        }),
      })
    } catch (error) {
      if (scopeRef.current !== capturedScope) return
      if (isClientError(error)) {
        sessionStorage.removeItem(correlationStore)
        setPendingKey(undefined)
        setNotice(["The source selection was rejected.", "来源选择被拒绝。"])
      } else {
        setNotice([
          "The result is unknown. Query the original operation; do not submit again.",
          "结果未知；请查询原操作，不要重新提交。",
        ])
      }
    }
  }
  const recoverSelection = async () => {
    if (!pendingKey) return
    let recoveredNamespace: string | undefined
    try {
      const intent = JSON.parse(
        sessionStorage.getItem(correlationStore) ?? "null",
      ) as { body?: { network_namespace?: unknown } } | null
      if (typeof intent?.body?.network_namespace === "string")
        recoveredNamespace = intent.body.network_namespace
    } catch {
      // The operation key is still recoverable through the API.
    }
    const capturedScope = scope
    try {
      const revision = await SourceCorrelationsService.creationOperation({
        projectId,
        key: pendingKey,
      })
      if (scopeRef.current !== capturedScope) return
      sessionStorage.removeItem(correlationStore)
      setPendingKey(undefined)
      await navigate({
        search: (previous) => ({
          ...previous,
          namespace: recoveredNamespace ?? previous.namespace,
          revision: revision.correlation_revision_id,
          tab: "summary",
          taskId: undefined,
          addressKey: undefined,
        }),
      })
    } catch {
      if (scopeRef.current !== capturedScope) return
      setNotice([
        "The original operation is still unavailable.",
        "原操作仍不可读取。",
      ])
    }
  }
  useEffect(() => {
    try {
      const intent = JSON.parse(
        sessionStorage.getItem(correlationStore) ?? "null",
      ) as { key?: string } | null
      setPendingKey(intent?.key)
    } catch {
      setPendingKey(undefined)
    }
  }, [correlationStore])
  useEffect(() => {
    setAddressQuery(search.addressIp ?? "")
    setNamespace(search.namespace ?? "")
  }, [search.addressIp, search.namespace])
  if (!user) return null
  if (identityError)
    return (
      <section className="space-y-3">
        <p role="alert" className="text-sm text-destructive">
          {t(
            "The explicit fixed identity is invalid; it was not corrected or read.",
            "明确固定身份格式无效；系统未修正或读取该链接。",
          )}{" "}
          {search.identityErrors?.join(", ")}
        </p>
      </section>
    )
  if (explicitFeedbackMismatch && !feedbackValidation.isLoading)
    return (
      <section className="space-y-3">
        <p role="alert" className="text-sm text-destructive">
          {t(
            "The explicit feedback revision does not belong to this fixed Analysis.",
            "明确反馈修订不属于当前固定 Analysis。",
          )}
        </p>
      </section>
    )
  if (accessError)
    return (
      <section className="space-y-3">
        <ErrorNotice error={accessError} />
        {!readErrors.scopeAccess && independentInput.current && (
          <Button
            variant="outline"
            onClick={() =>
              void navigate({
                search: () => ({ ...independentInput.current, tab: "peers" }),
              })
            }
          >
            {t(
              "Read independent NetFlow Analysis",
              "读取独立 NetFlow Analysis",
            )}
          </Button>
        )}
        {accessError.status !== 401 && (
          <Button
            variant="outline"
            onClick={() => void navigate({ search: () => ({}) })}
          >
            {t("Choose fixed inputs", "选择固定输入")}
          </Button>
        )}
      </section>
    )
  const change = (patch: Partial<NetflowCorrelationSearch>, reset = false) =>
    void navigate({
      search: (previous) => ({
        ...previous,
        ...patch,
        ...(reset
          ? {
              revision: undefined,
              taskId: undefined,
              addressKey: undefined,
              addressPage: 0,
              servicePage: 0,
              comparisonPage: 0,
              evidencePage: 0,
              evidenceSource: undefined,
              comparison: undefined,
              positiveSources: undefined,
              unmatchedNetflow: undefined,
              hasReviewTask: undefined,
              feedbackRevision: undefined,
              taskPage: 0,
            }
          : {}),
      }),
    })
  const selectedAddress = addressDetail.data
  return (
    <main className="min-w-0 space-y-6 [overflow-wrap:anywhere] [&_label]:block [&_label]:min-w-0 [&_label]:max-w-full [&_select]:min-w-0 [&_select]:max-w-full [&_code]:break-all">
      {Object.entries(readErrors).map(([kind, error]) => (
        <ErrorNotice key={kind} error={error} />
      ))}
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          {t("Source comparison", "来源比对")}
        </h1>
        <p className="text-sm text-muted-foreground">
          {t(
            "Compare records in your fixed inputs, then inspect differences and evidence.",
            "先看本次固定资料的 IP 记录，再核对来源差异与依据。",
          )}
        </p>
        <div className="flex flex-wrap gap-3 text-sm">
          <a
            className="underline"
            href={`/projects/${projectId}/customer-ledger`}
          >
            {t("Customer ledger", "客户清单")}
          </a>
          <a
            className="underline"
            href={`/projects/${projectId}/external-assets`}
          >
            {t("CloudAtlas data", "云图数据")}
          </a>
          <a
            className="underline"
            href={`/projects/${projectId}/netflow-ledger`}
          >
            {t("Legacy NetFlow ledger", "旧 NetFlow 活动账")}
          </a>
          <a
            className="underline"
            href={`/?project=${projectId}&view=inputs#netflow-inputs`}
          >
            {t("Import NetFlow data", "导入 NetFlow 数据")}
          </a>
          <Technical
            label={t("Fixed identifiers", "固定标识详情")}
            value={{
              project_id: projectId,
              correlation_revision_id: search.revision,
            }}
          />
        </div>
      </header>
      {(revisionIdentity || independentAnalysis) && (
        <>
          <nav
            className="flex flex-wrap gap-2"
            aria-label={t("Correlation views", "关联视图")}
          >
            {TABS.filter(
              (item) =>
                revisionIdentity || item === "peers" || item === "tasks",
            ).map((item) => (
              <Button
                key={item}
                variant={tab === item ? "default" : "outline"}
                onClick={() =>
                  change({
                    tab: item,
                    addressKey:
                      item === "addresses" ? search.addressKey : undefined,
                    taskId: item === "tasks" ? search.taskId : undefined,
                  })
                }
                aria-current={tab === item ? "page" : undefined}
              >
                {item === "summary"
                  ? t("Summary", "汇总")
                  : item === "addresses"
                    ? t("Addresses", "地址")
                    : item === "peers"
                      ? t("Peers", "对端")
                      : t("Review tasks", "复核任务")}
              </Button>
            ))}
          </nav>
          {tab === "addresses" && summary.data && revisionIdentity && (
            <section
              className="space-y-2 rounded border p-3 text-sm"
              aria-label={t("Comparison status", "本次比对状态")}
            >
              <p>
                {netflowText(
                  `COMPARISON_${summary.data.comparison?.state ?? "INSUFFICIENT_SOURCES"}`,
                  t,
                )}
              </p>
              <div className="flex flex-wrap gap-x-5 gap-y-2">
                {summary.data.sources.map((source) => (
                  <p key={source.source}>
                    {netflowText(source.source, t)}:{" "}
                    {netflowText(source.read_state, t)}
                    {source.coverage_state === "INSUFFICIENT"
                      ? ` · ${netflowText("INSUFFICIENT", t)}`
                      : source.coverage_state === "UNKNOWN"
                        ? ` · ${t("Coverage unknown", "覆盖未知")}`
                        : ""}
                  </p>
                ))}
              </div>
            </section>
          )}
          <NetflowFilters
            search={search}
            comparison={summary.data?.comparison}
            onApply={change}
          />
          {tab === "summary" && revisionIdentity && (
            <SummaryView
              summary={summary.data}
              revision={revisionIdentity}
              error={summary.error}
              onView={(comparison) =>
                change({
                  tab: "addresses",
                  comparison,
                  positiveSources: undefined,
                  unmatchedNetflow: undefined,
                  hasReviewTask: undefined,
                  addressIp: undefined,
                  addressPage: 0,
                  addressKey: undefined,
                  servicePage: 0,
                  comparisonPage: 0,
                  evidencePage: 0,
                  evidenceSource: undefined,
                })
              }
            />
          )}
          {tab === "summary" && revisionId && user.is_superuser && canWrite && (
            <NetflowScopeControl
              key={`${scope}/${revisionId}`}
              actor={actor}
              projectId={projectId}
              revisionId={revisionId!}
              onRevision={(revision) =>
                change({
                  revision,
                  addressKey: undefined,
                  addressPage: 0,
                  servicePage: 0,
                  comparisonPage: 0,
                  evidencePage: 0,
                })
              }
            />
          )}
          {tab === "addresses" && (
            <AddressesView
              addresses={addresses.data}
              error={addresses.error}
              addressQuery={addressQuery}
              setAddressQuery={setAddressQuery}
              onSearch={() =>
                change({
                  addressIp: addressQuery || undefined,
                  addressPage: 0,
                  servicePage: 0,
                  comparisonPage: 0,
                  evidencePage: 0,
                  evidenceSource: undefined,
                  addressKey: undefined,
                })
              }
              onPage={(page) =>
                change({
                  addressPage: page,
                  addressKey: undefined,
                  servicePage: 0,
                  comparisonPage: 0,
                  evidencePage: 0,
                  evidenceSource: undefined,
                })
              }
              selectedAddress={selectedAddress}
              services={services.data}
              evidence={evidence.data}
              evidenceSource={search.evidenceSource}
              onEvidenceSource={(source) =>
                change({ evidenceSource: source, evidencePage: 0 })
              }
              evidencePage={search.evidencePage ?? 0}
              onEvidencePage={(page) => change({ evidencePage: page })}
              servicePage={search.servicePage ?? 0}
              onServicePage={(page) =>
                change({ servicePage: page, comparisonPage: 0 })
              }
              comparisonPage={search.comparisonPage ?? 0}
              onComparisonPage={(page) => change({ comparisonPage: page })}
              onAddress={(address) =>
                change({
                  addressKey: address.address_key,
                  servicePage: 0,
                  comparisonPage: 0,
                  evidencePage: 0,
                  evidenceSource: undefined,
                })
              }
              detailError={addressDetail.error}
              onOpenReviewTasks={() =>
                change({
                  tab: "tasks",
                  taskId: undefined,
                  addressKey: undefined,
                })
              }
            />
          )}
          {tab === "peers" && (
            <PeersView
              peers={peers.data}
              error={peers.error}
              onPage={(page) => change({ peerPage: page })}
            />
          )}
          {tab === "tasks" &&
            latestFeedback.data &&
            latestFeedbackMatches &&
            latestFeedback.data.feedback_revision_id !==
              search.feedbackRevision && (
              <div className="flex flex-wrap items-center gap-3">
                <p>
                  {t(
                    "Historical feedback is read-only; pages stay pinned until you switch.",
                    "历史反馈只读；明确切换前分页保持固定。",
                  )}
                </p>
                <Button
                  variant="outline"
                  onClick={() =>
                    change({
                      feedbackRevision:
                        latestFeedback.data.feedback_revision_id,
                      taskPage: 0,
                      addressKey: undefined,
                    })
                  }
                >
                  {t("Read current feedback revision", "读取当前反馈修订")}
                </Button>
              </div>
            )}
          {tab === "tasks" && (
            <TasksView
              key={`${scope}/${search.feedbackRevision}/${search.taskId ?? "none"}`}
              canWrite={
                canWrite &&
                !feedbackIdentityError &&
                !latestFeedback.isError &&
                !latestFeedback.isFetching &&
                latestFeedbackMatches &&
                latestFeedback.data?.feedback_revision_id ===
                  search.feedbackRevision
              }
              tasks={tasksMatch ? tasks.data : undefined}
              task={taskMatches ? task.data : undefined}
              feedback={feedbackMatches ? feedback.data : undefined}
              error={
                feedbackIdentityError ??
                tasks.error ??
                feedback.error ??
                task.error
              }
              status={search.taskStatus}
              onStatus={(status) =>
                change({
                  taskStatus: status,
                  taskPage: 0,
                  addressKey: undefined,
                })
              }
              onPage={(page) =>
                change({ taskPage: page, addressKey: undefined })
              }
              onTask={(taskId) => change({ taskId, addressKey: undefined })}
              projectId={projectId}
              actor={actor}
              analysisId={selectedAnalysisId}
              feedbackRevision={search.feedbackRevision}
              onFeedback={(revision) =>
                change({
                  feedbackRevision: revision,
                  taskPage: 0,
                  addressKey: undefined,
                })
              }
            />
          )}
        </>
      )}
      {summary.error && <ErrorNotice error={summary.error} />}
      {search.revision && summary.isSuccess && !identityMatches && (
        <p role="alert" className="text-sm text-destructive">
          {t(
            "The explicit correlation revision is unavailable; no latest fallback was used.",
            "明确关联修订不可读；未回退到 latest。",
          )}
        </p>
      )}
      <section
        className={search.revision ? "text-sm" : "rounded-md border p-4"}
        aria-label={t("Fixed inputs", "固定输入")}
      >
        <h2 className={search.revision ? "sr-only" : "font-semibold"}>
          {t("Fixed inputs", "固定输入")}
        </h2>
        <details open={!search.revision} className="mt-2">
          <summary className="cursor-pointer text-sm text-muted-foreground">
            {search.revision
              ? t(
                  "Change inputs or inspect processing",
                  "更换资料或查看处理过程",
                )
              : selectedDataset
                ? `${selectedDataset.display_filename} · ${selectedContext?.network_namespace ?? t("context not selected", "未选择上下文")}`
                : t("Choose NetFlow data to begin", "选择 NetFlow 数据以开始")}
          </summary>
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            <Label>
              {t("Dataset", "Dataset")}
              <select
                className="mt-1 block w-full rounded border bg-background p-2"
                value={search.dataset ?? ""}
                onChange={(event) => {
                  setContextPage(0)
                  setAnalysisPage(0)
                  setCorrelationPage(0)
                  change(
                    {
                      dataset: event.target.value || undefined,
                      context: undefined,
                      analysis: undefined,
                      namespace: undefined,
                      customerUpload: undefined,
                      cloudMode: "none",
                      cloudSnapshot: undefined,
                      cloudLedgerRevision: undefined,
                      cloudScopeRevision: undefined,
                      cloudSource: undefined,
                    },
                    true,
                  )
                }}
              >
                <option value="">{t("Choose explicitly", "明确选择")}</option>
                {datasets.data?.data.map((dataset: NetFlowDatasetPublic) => (
                  <option key={dataset.id} value={dataset.id}>
                    {dataset.display_filename} ·{" "}
                    {formatDate(dataset.created_at)}
                  </option>
                ))}
              </select>
            </Label>
            <Label>
              {t("Processing context", "处理上下文")}
              <select
                className="mt-1 block w-full rounded border bg-background p-2"
                value={search.context ?? ""}
                onChange={(event) =>
                  change(
                    {
                      context: event.target.value || undefined,
                      namespace: contexts.data?.data.find(
                        (item) =>
                          item.context_revision_id === event.target.value,
                      )?.network_namespace,
                      analysis: undefined,
                      revision: undefined,
                    },
                    true,
                  )
                }
                disabled={!search.dataset}
              >
                <option value="">{t("Choose explicitly", "明确选择")}</option>
                {contexts.data?.data.map((context: ContextPublic) => (
                  <option
                    key={context.context_revision_id}
                    value={context.context_revision_id}
                  >
                    {context.network_namespace} ·{" "}
                    {netflowText(context.state, t)} · r{context.revision}
                  </option>
                ))}
              </select>
            </Label>
            <Label>
              {t("Analysis", "Analysis")}
              <select
                className="mt-1 block w-full rounded border bg-background p-2"
                value={search.analysis ?? ""}
                onChange={(event) =>
                  change(
                    {
                      analysis: event.target.value || undefined,
                      revision: undefined,
                      feedbackRevision: undefined,
                    },
                    true,
                  )
                }
                disabled={!search.dataset}
              >
                <option value="">{t("Choose explicitly", "明确选择")}</option>
                {analyses.data?.data.map((analysis: AnalysisPublic) => (
                  <option
                    key={analysis.analysis_id}
                    value={analysis.analysis_id}
                  >
                    {netflowText(analysis.status, t)} ·{" "}
                    {formatDate(analysis.created_at)}
                  </option>
                ))}
              </select>
            </Label>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <SelectorPage
              label={t("Datasets", "数据集")}
              page={datasetPage}
              hasNext={
                (datasets.data?.count ?? 0) > (datasetPage + 1) * PAGE_SIZE
              }
              onPage={setDatasetPage}
            />
            <SelectorPage
              label={t("Contexts", "上下文")}
              page={contextPage}
              hasNext={
                (contexts.data?.count ?? 0) > (contextPage + 1) * PAGE_SIZE
              }
              onPage={setContextPage}
            />
            <SelectorPage
              label={t("Analyses", "分析")}
              page={analysisPage}
              hasNext={
                (analyses.data?.count ?? 0) > (analysisPage + 1) * PAGE_SIZE
              }
              onPage={setAnalysisPage}
            />
            <SelectorPage
              label={t("Customer versions", "客户版本")}
              page={uploadPage}
              hasNext={
                (uploads.data?.count ?? 0) > (uploadPage + 1) * PAGE_SIZE
              }
              onPage={setUploadPage}
            />
          </div>
          {selectedDataset && (
            <p className="mt-3 text-xs text-muted-foreground">
              {selectedDataset.display_filename} ·{" "}
              {t("Raw records", "原始记录")} {selectedDataset.raw_record_count}{" "}
              · {t("Valid records", "有效记录")}{" "}
              {selectedDataset.activity_valid_record_count} ·{" "}
              {t("Isolated records", "隔离记录")}{" "}
              {selectedDataset.isolated_record_count}
            </p>
          )}
          {selectedContext && (
            <p className="mt-1 text-xs text-muted-foreground">
              {t("Context state", "上下文状态")}:{" "}
              {netflowText(selectedContext.current_state, t)};{" "}
              {t("namespace", "namespace")}:{" "}
              <code>{selectedContext.network_namespace}</code>
            </p>
          )}
          {selectedAnalysis && (
            <p className="mt-1 text-xs text-muted-foreground">
              {t("Analysis status", "Analysis 状态")}:{" "}
              <StateText state={selectedAnalysis.status} />;{" "}
              {selectedAnalysis.error_code
                ? netflowText(selectedAnalysis.error_code, t)
                : ""}
            </p>
          )}
          {selectedUpload && (
            <p className="mt-1 text-xs text-muted-foreground">
              {t("Customer version", "客户版本")}:{" "}
              {selectedUpload.display_filename}
            </p>
          )}
          {search.dataset && (
            <details
              className="mt-3 rounded border p-3"
              open={!selectedContext}
            >
              <summary className="cursor-pointer font-semibold">
                {t(
                  selectedContext
                    ? "Correct processing context"
                    : "Confirm processing context",
                  selectedContext ? "更正处理上下文" : "确认处理上下文",
                )}
              </summary>
              <NetflowContextForm
                key={`${actor}:${projectId}:${search.dataset}`}
                actor={actor}
                projectId={projectId}
                datasetId={search.dataset}
                current={authoritativeCurrentContext}
                currentResolved={
                  !contexts.isFetching &&
                  !currentContext.isFetching &&
                  (currentContext.isSuccess ||
                    (contexts.isSuccess && contexts.data.count === 0))
                }
                onRefresh={() => {
                  void contexts.refetch()
                  void currentContext.refetch()
                }}
                isAdmin={user?.is_superuser === true}
                onCreated={(context) => {
                  void contexts.refetch()
                  change(
                    {
                      context: context.context_revision_id,
                      namespace: context.network_namespace,
                      analysis: undefined,
                    },
                    true,
                  )
                }}
              />
            </details>
          )}
          {search.dataset &&
            selectedContext &&
            (!search.analysis || selectedAnalysis) && (
              <NetflowAnalysisActions
                key={`${scope}/analysis-actions`}
                actor={actor}
                projectId={projectId}
                datasetId={search.dataset}
                contextId={selectedContext.context_revision_id}
                analysis={selectedAnalysis}
                canWrite={
                  canWrite && selectedContext.current_state === "CONFIRMED"
                }
                onAnalysis={(value) => {
                  void analyses.refetch()
                  change({ analysis: value.analysis_id, tab: "summary" }, true)
                }}
              />
            )}
        </details>
      </section>
      <section
        className={search.revision ? "text-sm" : "rounded-md border p-4"}
        aria-label={t("Source selection", "来源选择")}
      >
        <h2 className={search.revision ? "sr-only" : "font-semibold"}>
          {t("Fixed source selection", "固定来源选择")}
        </h2>
        <details open={!search.revision} className="mt-2">
          <summary className="cursor-pointer text-sm text-muted-foreground">
            {t("Choose or change source versions", "选择或更改来源版本")}
          </summary>
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            <Label>
              {t("Network namespace", "网络空间")}
              <Input
                value={namespace}
                onChange={(event) => setNamespace(event.target.value)}
                placeholder="synthetic-edge-a"
              />
            </Label>
            <Label>
              {t("Customer version", "客户版本")}
              <select
                className="mt-1 block w-full rounded border bg-background p-2"
                value={search.customerUpload ?? ""}
                onChange={(event) =>
                  change(
                    {
                      customerUpload: event.target.value || undefined,
                      revision: undefined,
                    },
                    true,
                  )
                }
              >
                <option value="">{t("Not provided", "未提供")}</option>
                {uploads.data?.data.map((upload) => (
                  <option key={upload.id} value={upload.id}>
                    {upload.display_filename} · {upload.id}
                  </option>
                ))}
              </select>
            </Label>
            <Label>
              {t("Cloud source", "云图来源")}
              <select
                className="mt-1 block w-full rounded border bg-background p-2"
                value={search.cloudMode ?? "none"}
                onChange={(event) => {
                  setSnapshotPage(0)
                  setVersionPage(0)
                  change(
                    {
                      cloudMode: event.target
                        .value as NetflowCorrelationSearch["cloudMode"],
                      cloudSnapshot: undefined,
                      cloudLedgerRevision: undefined,
                      cloudScopeRevision: undefined,
                      cloudSource: undefined,
                      revision: undefined,
                    },
                    true,
                  )
                }}
              >
                <option value="none">{t("Not provided", "未提供")}</option>
                <option value="legacy">{t("Legacy snapshot", "旧快照")}</option>
                <option value="external">
                  {t("Pinned external versions", "固定外部版本")}
                </option>
              </select>
            </Label>
          </div>
          {search.cloudMode === "legacy" && (
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              <Label>
                {t("Snapshot", "快照")}
                <select
                  className="mt-1 block w-full rounded border bg-background p-2"
                  value={search.cloudSnapshot ?? ""}
                  onChange={(event) =>
                    change(
                      {
                        cloudSnapshot: event.target.value || undefined,
                        cloudLedgerRevision: undefined,
                        cloudScopeRevision: undefined,
                        revision: undefined,
                      },
                      true,
                    )
                  }
                >
                  <option value="">{t("Choose explicitly", "明确选择")}</option>
                  {snapshots.data?.map((snapshot) => (
                    <option key={snapshot.id} value={snapshot.id}>
                      {snapshot.id} · {snapshot.record_count}
                    </option>
                  ))}
                </select>
              </Label>
              <Label>
                {t("Ledger revision", "台账修订")}
                <Input
                  type="number"
                  min={0}
                  value={search.cloudLedgerRevision ?? ""}
                  onChange={(event) =>
                    change(
                      {
                        cloudLedgerRevision: event.target.value
                          ? Number(event.target.value)
                          : undefined,
                        revision: undefined,
                      },
                      true,
                    )
                  }
                />
              </Label>
              <Label>
                {t("Scope revision", "范围修订")}
                <Input
                  type="number"
                  min={0}
                  value={search.cloudScopeRevision ?? ""}
                  onChange={(event) =>
                    change(
                      {
                        cloudScopeRevision: event.target.value
                          ? Number(event.target.value)
                          : undefined,
                        revision: undefined,
                      },
                      true,
                    )
                  }
                />
              </Label>
            </div>
          )}
          {search.cloudMode === "external" && (
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              <Label>
                {t("Assets source", "资产来源")}
                <select
                  className="mt-1 block w-full rounded border bg-background p-2"
                  value={search.cloudSource ?? ""}
                  onChange={(event) => {
                    setVersionPage(0)
                    change(
                      {
                        cloudSource: event.target.value || undefined,
                        cloudIpVersion: undefined,
                        cloudPortVersion: undefined,
                        revision: undefined,
                      },
                      true,
                    )
                  }}
                >
                  <option value="">{t("Choose explicitly", "明确选择")}</option>
                  {sources.data?.data
                    .filter(
                      (source) => source.capability_profile === "assets-v1",
                    )
                    .map((source) => (
                      <option key={source.id} value={source.id}>
                        {source.space_id} · {source.id} ·{" "}
                        {source.enabled ? "enabled" : "disabled"}
                      </option>
                    ))}
                </select>
              </Label>
              <Label>
                {t("IP version", "IP 版本")}
                <select
                  className="mt-1 block w-full rounded border bg-background p-2"
                  value={search.cloudIpVersion ?? ""}
                  onChange={(event) =>
                    change(
                      {
                        cloudIpVersion: event.target.value || undefined,
                        revision: undefined,
                      },
                      true,
                    )
                  }
                  disabled={!assetSource}
                >
                  <option value="">{t("Not selected", "未选择")}</option>
                  {externalVersions.data?.ip.data.map((version) => (
                    <option key={version.id} value={version.id}>
                      {version.id} · {version.status} · {version.record_count}
                    </option>
                  ))}
                </select>
              </Label>
              <Label>
                {t("Port version", "端口版本")}
                <select
                  className="mt-1 block w-full rounded border bg-background p-2"
                  value={search.cloudPortVersion ?? ""}
                  onChange={(event) =>
                    change(
                      {
                        cloudPortVersion: event.target.value || undefined,
                        revision: undefined,
                      },
                      true,
                    )
                  }
                  disabled={!assetSource}
                >
                  <option value="">{t("Not selected", "未选择")}</option>
                  {externalVersions.data?.port.data.map((version) => (
                    <option key={version.id} value={version.id}>
                      {version.id} · {version.status} · {version.record_count}
                    </option>
                  ))}
                </select>
              </Label>
            </div>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            <SelectorPage
              label={t("Legacy snapshots", "旧快照")}
              page={snapshotPage}
              hasNext={(snapshots.data?.length ?? 0) === PAGE_SIZE}
              onPage={setSnapshotPage}
            />
            <SelectorPage
              label={t("External versions", "外部版本")}
              page={versionPage}
              hasNext={
                (externalVersions.data?.ip.count ?? 0) >
                  (versionPage + 1) * PAGE_SIZE ||
                (externalVersions.data?.port.count ?? 0) >
                  (versionPage + 1) * PAGE_SIZE
              }
              onPage={setVersionPage}
            />
            <SelectorPage
              label={t("Correlations", "关联")}
              page={correlationPage}
              hasNext={
                (correlations.data?.count ?? 0) >
                (correlationPage + 1) * PAGE_SIZE
              }
              onPage={setCorrelationPage}
            />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button
              onClick={() => void createSelection()}
              disabled={
                !canWrite ||
                Boolean(search.revision) ||
                creationIdentityInvalid ||
                !hasSource ||
                !identityReady ||
                !cloudSelectionReady ||
                Boolean(pendingKey)
              }
            >
              {t("Create fixed correlation", "创建固定关联")}
            </Button>
            {pendingKey && (
              <Button variant="outline" onClick={() => void recoverSelection()}>
                {t("Query original operation", "查询原操作")}
              </Button>
            )}
            <span className="text-sm text-muted-foreground">
              {t(
                "No source choice falls back to latest; NetFlow is fixed by the selected Analysis.",
                "来源选择不回退 latest；NetFlow 由所选 Analysis 固定。",
              )}
            </span>
          </div>
        </details>
      </section>
      {notice && (
        <p role="alert" className="text-sm text-destructive">
          {t(...notice)}
        </p>
      )}
      {search.revision ? (
        <Button
          variant="outline"
          onClick={() =>
            change({
              revision: undefined,
              taskId: undefined,
              addressKey: undefined,
              tab: "summary",
            })
          }
        >
          {t("Browse saved revisions", "浏览已保存修订")}
        </Button>
      ) : (
        <section className="rounded-md border p-4">
          {(readErrors.correlations || correlations.error) && (
            <div>
              <ErrorNotice
                error={readErrors.correlations ?? correlations.error}
              />
              <p className="mt-1 text-sm text-muted-foreground">
                {t(
                  "The saved revision directory is unavailable; no older or latest revision was substituted. Open a fixed revision explicitly if you have its ID.",
                  "已保存修订目录不可读取；未替换为旧修订或 latest。若已有修订 ID，请显式打开固定修订。",
                )}
              </p>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-semibold">
              {t("Saved correlation revisions", "已保存关联修订")}
            </h2>
            <span className="text-sm text-muted-foreground">
              {t("Count", "总数")}: {correlations.data?.count ?? "—"}
            </span>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {correlations.data?.data.map((revision) => (
              <Button
                key={revision.correlation_revision_id}
                variant={
                  revision.correlation_revision_id === search.revision
                    ? "default"
                    : "outline"
                }
                onClick={() =>
                  change(
                    {
                      ...fixedInputSearch(revision.selection, revision.pins),
                      revision: revision.correlation_revision_id,
                      tab: "summary",
                      addressKey: undefined,
                      servicePage: 0,
                      comparisonPage: 0,
                      evidencePage: 0,
                      evidenceSource: undefined,
                      feedbackRevision: undefined,
                    },
                    false,
                  )
                }
              >
                {revision.network_namespace} · r{revision.revision} ·{" "}
                {netflowText(revision.current_scope_state, t)}
              </Button>
            ))}
            {correlations.isSuccess && correlations.data.count === 0 && (
              <span className="text-sm text-muted-foreground">
                {t(
                  "No saved revision in this explicit filter.",
                  "当前明确筛选下没有已保存修订。",
                )}
              </span>
            )}
          </div>
        </section>
      )}
    </main>
  )
}

function SummaryView({
  summary,
  revision,
  error,
  onView,
}: {
  summary:
    | Awaited<ReturnType<typeof SourceCorrelationsService.summary>>
    | undefined
  revision: { correlation_revision_id: string }
  error: unknown
  onView: (view: "all" | "differences" | "common") => void
}) {
  const { t, formatDate } = useI18n()
  if (error) return <ErrorNotice error={error} />
  if (!summary)
    return <p>{t("Reading pinned summary…", "正在读取固定汇总…")}</p>
  const comparison = summary.comparison
  const available = comparison?.state === "AVAILABLE"
  return (
    <section
      className="space-y-5"
      aria-label={t("Comparison results", "比对结果")}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xl font-semibold">
          {t("Comparison results", "比对结果")}
        </h2>
        <p className="text-sm text-muted-foreground">
          {summary.network_namespace} · {formatDate(summary.created_at)}
        </p>
      </div>
      <section aria-label={t("Input status", "本次资料")}>
        <div className="grid gap-3 md:grid-cols-3">
          {summary.sources.map((source) => (
            <SourceCard key={source.source} source={source} />
          ))}
        </div>
      </section>
      <div className="space-y-3 rounded-md border border-primary/25 bg-primary/5 p-4 sm:p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="font-semibold">
            {t("Confirmed IP facts", "确定的 IP 事实")}
          </h3>
          <span className="text-sm">
            {t(
              `${comparison?.sources.length ?? 0} selected sources`,
              `已选 ${comparison?.sources.length ?? 0} 个来源`,
            )}
          </span>
        </div>
        <p className="text-sm">
          {netflowText(
            `COMPARISON_${comparison?.state ?? "INSUFFICIENT_SOURCES"}`,
            t,
          )}
        </p>
        {available && comparison.sources.length === 2 && (
          <p className="text-sm font-medium">
            {!comparison.sources.includes("CUSTOMER")
              ? t(
                  "This is a two-source comparison; the customer ledger has not been checked.",
                  "当前为两源比对，尚不能核对客户登记清单。",
                )
              : t(
                  "This is a two-source comparison. The missing third input is not counted as an empty batch.",
                  "当前为两源比对；未提供的第三份资料不计作空批次。",
                )}
          </p>
        )}
        <div className="grid gap-3 sm:grid-cols-3">
          {(
            [
              [
                "all",
                t("All addresses", "全部地址"),
                t("All addresses count", "全量地址数"),
                summary.total_addresses,
              ],
              [
                "differences",
                t("Source differences", "来源差异"),
                t("Source difference count", "来源差异数"),
                comparison?.different_addresses,
              ],
              [
                "common",
                t("All selected sources present", "全部已选来源均有记录"),
                t("Common address count", "共同记录地址数"),
                comparison?.common_addresses,
              ],
            ] as const
          ).map(([view, label, countLabel, value]) => (
            <div
              key={view}
              className="space-y-2 rounded border bg-background p-3"
            >
              <output
                aria-label={countLabel}
                className="block text-2xl font-semibold tabular-nums"
              >
                {value == null ? t("Unavailable", "不可用") : value}
              </output>
              <Button
                className="h-auto whitespace-normal p-0 text-left"
                variant="link"
                aria-label={label}
                disabled={view !== "all" && !available}
                onClick={() => onView(view)}
              >
                {label}
              </Button>
            </div>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          {t(
            "The customer ledger is the registration baseline for this comparison; it does not establish ownership or reachability.",
            "客户清单是本次登记基准；登记记录本身不证明资产所有权或可达性。",
          )}
        </p>
      </div>
      <p className="text-sm text-muted-foreground">
        {t(
          "Next: open a difference, check the three source states and original evidence, then supply material to an existing review task if needed.",
          "下一步：打开一条差异，核对三源状态和原始依据；如有已有复核任务，再补充相应材料。",
        )}
      </p>
      <details className="rounded-md border p-4">
        <summary className="cursor-pointer text-sm">
          {t(
            "Comparison scope and technical details",
            "本次比对范围与技术详情",
          )}
        </summary>
        <p className="mt-3 text-sm">
          {t("Current scope", "当前范围")}:{" "}
          {netflowText(summary.current_scope_state, t)}
        </p>
        <Technical
          label={t("Fixed identifiers", "固定标识详情")}
          value={{
            project_id: summary.project_id,
            correlation_revision_id: revision.correlation_revision_id,
          }}
        />
        <Technical
          label={t("Selection", "来源选择")}
          value={summary.selection}
        />
        <Technical label={t("Pins", "固定指纹")} value={summary.pins} />
        <NoticeList values={summary.limitations} />
      </details>
    </section>
  )
}

function SourceCard({ source }: { source: SourceState }) {
  const { t, formatDate } = useI18n()
  const domains =
    source.metadata?.domains && typeof source.metadata?.domains === "object"
      ? Object.entries(source.metadata?.domains)
      : []
  return (
    <article className="rounded border p-3">
      <h4 className="font-medium">{netflowText(source.source, t)}</h4>
      <p className="mt-1 text-sm">
        <strong>{netflowText(source.read_state, t)}</strong>
      </p>
      <p className="mt-2 text-sm">
        {count(source.source_addresses)} IP · {count(source.source_records)}{" "}
        {t("records", "条记录")}
      </p>
      {source.coverage_state === "UNKNOWN" && (
        <p className="mt-2 text-xs text-muted-foreground">
          {t(
            "Coverage is unknown; no match does not prove absence.",
            "覆盖未知；本批未匹配不能据此判断是否不存在。",
          )}
        </p>
      )}
      {source.coverage_state === "INSUFFICIENT" && (
        <p className="mt-2 text-sm text-destructive">
          {t(
            "Coverage is insufficient; comparison counts are unavailable.",
            "覆盖不足；比对数量不可用。",
          )}
        </p>
      )}
      <details className="mt-3">
        <summary className="cursor-pointer text-xs text-muted-foreground">
          {t("Counts, time and evidence limits", "计数、时间与依据限制")}
        </summary>
        <dl className="mt-2 grid grid-cols-2 gap-x-3 text-xs">
          <dt>{t("Records", "记录")}</dt>
          <dd>{count(source.source_records)}</dd>
          <dt>{t("Addresses", "地址")}</dt>
          <dd>{count(source.source_addresses)}</dd>
          <dt>{t("Objects", "对象")}</dt>
          <dd>{count(source.source_objects)}</dd>
          <dt>{t("Raw records", "原始记录")}</dt>
          <dd>{count(source.raw_records)}</dd>
          <dt>{t("Valid records", "有效记录")}</dt>
          <dd>{count(source.valid_records)}</dd>
          <dt>{t("Candidates", "候选数")}</dt>
          <dd>{count(source.candidate_count)}</dd>
          <dt>{t("Tasks", "任务")}</dt>
          <dd>{count(source.review_task_count)}</dd>
        </dl>
        {domains.map(([domain, raw]) => {
          const data = raw as Record<string, unknown>
          return (
            <p key={domain} className="mt-2 text-xs">
              {domain === "ip"
                ? t("IP assets", "IP 资产")
                : t("Port material", "端口材料")}{" "}
              · {t("Fetched", "获取时间")}:{" "}
              {typeof data.fetched_at === "string"
                ? formatDate(data.fetched_at)
                : "—"}{" "}
              · {t("Retained until", "保留至")}:{" "}
              {typeof data.retain_until === "string"
                ? formatDate(data.retain_until)
                : "—"}
            </p>
          )
        })}
        <Technical
          label={t("Source version and time details", "来源版本与时间详情")}
          value={source.metadata}
        />
        <Technical
          label={t("State codes", "状态原码")}
          value={{
            state: source.state,
            read_state: source.read_state,
            coverage_state: source.coverage_state,
          }}
        />
        {source.limitations?.length ? (
          <NoticeList values={source.limitations} />
        ) : null}
      </details>
    </article>
  )
}

function NoticeList({ values }: { values: string[] }) {
  const { t } = useI18n()
  return (
    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground [overflow-wrap:anywhere]">
      {values.map((value) => (
        <li key={value}>{netflowText(value, t)}</li>
      ))}
    </ul>
  )
}
function ErrorNotice({ error }: { error: unknown }) {
  const { t } = useI18n()
  return (
    <div role="alert" className="text-sm text-destructive">
      <p>
        {errorCode(error)
          ? netflowText(errorCode(error)!, t)
          : t(
              "Pinned data could not be read. Retry the read or ask an administrator to investigate.",
              "固定数据不可读取，请重试读取或联系管理员核查。",
            )}
      </p>
      <Technical
        label={t("Error details", "错误详情")}
        value={errorCode(error)}
      />
    </div>
  )
}

function AddressesView({
  addresses,
  error,
  addressQuery,
  setAddressQuery,
  onSearch,
  onPage,
  selectedAddress,
  services,
  evidence,
  evidenceSource,
  onEvidenceSource,
  evidencePage,
  onEvidencePage,
  comparisonPage,
  servicePage,
  onServicePage,
  onComparisonPage,
  onAddress,
  detailError,
  onOpenReviewTasks,
}: {
  addresses:
    | Awaited<ReturnType<typeof SourceCorrelationsService.listAddresses>>
    | undefined
  error: unknown
  addressQuery: string
  setAddressQuery: (value: string) => void
  onSearch: () => void
  onPage: (page: number) => void
  selectedAddress: AddressPublic | undefined
  services:
    | Awaited<ReturnType<typeof SourceCorrelationsService.addressServices>>
    | undefined
  evidence:
    | Awaited<ReturnType<typeof SourceCorrelationsService.addressEvidence>>
    | undefined
  evidenceSource: NetflowCorrelationSearch["evidenceSource"]
  onEvidenceSource: (
    source: NonNullable<NetflowCorrelationSearch["evidenceSource"]>,
  ) => void
  evidencePage: number
  onEvidencePage: (page: number) => void
  comparisonPage: number
  onComparisonPage: (page: number) => void
  servicePage: number
  onServicePage: (page: number) => void
  onAddress: (address: AddressPublic) => void
  detailError: unknown
  onOpenReviewTasks: () => void
}) {
  const { t } = useI18n()
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Input
          aria-label={t("Exact IP", "精确 IP")}
          value={addressQuery}
          onChange={(event) => setAddressQuery(event.target.value)}
        />
        <Button onClick={onSearch}>{t("Filter", "筛选")}</Button>
        <span className="self-center text-sm text-muted-foreground">
          {t(
            "Current page and full filtered count are separate.",
            "当前页数量与完整筛选总数分开。",
          )}
        </span>
      </div>
      {error ? (
        <ErrorNotice error={error} />
      ) : (
        <>
          <section
            className="overflow-x-auto"
            aria-label={t("Address table", "地址表格")}
          >
            <table className="w-full min-w-[40rem] text-left text-sm">
              <thead>
                <tr className="border-b">
                  <th className="p-2">IP</th>
                  <th className="p-2">{t("Sources", "来源")}</th>
                  <th className="p-2">
                    {t("Flow source records", "流量源记录")}
                  </th>
                  <th className="p-2">{t("Tasks", "任务")}</th>
                  <th className="p-2">{t("Meaning", "含义")}</th>
                </tr>
              </thead>
              <tbody>
                {addresses?.data.map((address: AddressPublic) => (
                  <tr
                    key={address.address_key}
                    className={`border-b ${selectedAddress?.address_key === address.address_key ? "bg-muted" : ""}`}
                  >
                    <td className="p-2">
                      <Button
                        variant="link"
                        className="h-auto p-0 font-mono"
                        onClick={() => onAddress(address)}
                      >
                        {address.canonical_ip}
                      </Button>
                      <Technical
                        label={t("Address identifier", "地址标识")}
                        value={address.address_key}
                      />
                    </td>
                    <td className="p-2">
                      {address.positive_sources
                        .map((source) => netflowText(source, t))
                        .join(", ") || "—"}
                    </td>
                    <td className="p-2">
                      {count(address.source_record_count)}
                    </td>
                    <td className="p-2">{address.task_refs.length}</td>
                    <td className="max-w-xs p-2 text-xs">
                      {netflowText(address.conclusion ?? "RECORDED_IP", t)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          <ResultPagination
            label="Addresses"
            count={addresses?.count ?? 0}
            page={
              addresses?.skip ? Math.floor(addresses.skip / addresses.limit) : 0
            }
            pageSize={addresses?.limit ?? PAGE_SIZE}
            onPageChange={onPage}
          />
          <div className="text-sm text-muted-foreground">
            {t("Current page", "当前页")}: {addresses?.data.length ?? 0} ·{" "}
            {t("Filtered count", "筛选总数")}: {addresses?.count ?? "—"} ·{" "}
            {t("All addresses", "全量地址")}:{" "}
            {addresses?.total_addresses ?? "—"}
          </div>
        </>
      )}
      {selectedAddress && (
        <AddressDetail
          detail={selectedAddress}
          detailError={detailError}
          onOpenReviewTasks={onOpenReviewTasks}
          services={services}
          evidence={evidence}
          evidenceSource={evidenceSource}
          onEvidenceSource={onEvidenceSource}
          comparisonPage={comparisonPage}
          servicePage={servicePage}
          onServicePage={onServicePage}
          onComparisonPage={onComparisonPage}
          evidencePage={evidencePage}
          onEvidencePage={onEvidencePage}
        />
      )}
    </div>
  )
}

function AddressDetail({
  detail,
  detailError,
  services,
  evidence,
  evidenceSource,
  onEvidenceSource,
  comparisonPage,
  servicePage,
  onServicePage,
  onComparisonPage,
  evidencePage,
  onEvidencePage,
  onOpenReviewTasks,
}: {
  detail: AddressPublic
  detailError: unknown
  services:
    | Awaited<ReturnType<typeof SourceCorrelationsService.addressServices>>
    | undefined
  evidence:
    | Awaited<ReturnType<typeof SourceCorrelationsService.addressEvidence>>
    | undefined
  evidenceSource: NetflowCorrelationSearch["evidenceSource"]
  onEvidenceSource: (
    source: NonNullable<NetflowCorrelationSearch["evidenceSource"]>,
  ) => void
  comparisonPage: number
  servicePage: number
  onServicePage: (page: number) => void
  onComparisonPage: (page: number) => void
  evidencePage: number
  onEvidencePage: (page: number) => void
  onOpenReviewTasks: () => void
}) {
  const { t } = useI18n()
  return (
    <section className="space-y-4 rounded-md border p-4">
      <h2 className="font-semibold">
        {t("Address detail", "地址详情")} · <code>{detail.canonical_ip}</code>
      </h2>
      {detailError ? (
        <ErrorNotice error={detailError} />
      ) : (
        <>
          <p className="text-base font-medium">
            {netflowText(detail.conclusion ?? "RECORDED_IP", t)}
          </p>
          <div className="grid gap-3 md:grid-cols-3">
            {(["CUSTOMER", "CLOUD", "NETFLOW"] as const).map((source) => (
              <div key={source} className="rounded border p-3 text-sm">
                <p className="font-medium">{netflowText(source, t)}</p>
                <p className="mt-1">
                  {netflowText(detail.presence?.[source] ?? "UNKNOWN", t)}
                </p>
                <p className="mt-1 text-muted-foreground">
                  {t("Source records", "来源记录")}:{" "}
                  {count(detail.source_counts?.[source])}
                </p>
              </div>
            ))}
          </div>
          <div className="space-y-2 text-sm">
            <h3 className="font-medium">{t("Next step", "下一步")}</h3>
            <p>
              {t(
                "Check the original records and collection scope. No flow match does not mean activity stopped; a flow-only record does not establish risk or missing governance.",
                "核对原始记录与采集范围。没有流量记录不等于停止活动；仅流量有记录不代表风险或漏管。",
              )}
            </p>
            {detail.task_refs.length > 0 && (
              <div className="space-y-2">
                <p>
                  {t(
                    "Existing review tasks are linked below the comparison. Batch tasks are shared across addresses.",
                    "本次比对的复核任务可从“复核任务”入口查看；批次任务由多个地址共享。",
                  )}
                </p>
                <Button variant="outline" onClick={onOpenReviewTasks}>
                  {t("Open existing review tasks", "查看已有复核任务")}
                </Button>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              {(["customer", "cloud", "netflow"] as const).map((source) => (
                <Button
                  key={source}
                  variant="outline"
                  onClick={() => {
                    onEvidenceSource(source)
                    document.getElementById("address-source-evidence")?.focus()
                  }}
                >
                  {t("View evidence", "查看依据")} ·{" "}
                  {netflowText(source.toUpperCase(), t)}
                </Button>
              ))}
            </div>
          </div>
          <div className="grid gap-2 text-sm md:grid-cols-3">
            <p>
              {t("Family", "地址族")}: {detail.family}
            </p>
            <p>
              {t("Positive sources", "正向来源")}:{" "}
              {detail.positive_sources
                .map((source) => netflowText(source, t))
                .join(", ") || "—"}
            </p>
            <p>
              {t("Reachability", "可达性")}:{" "}
              {netflowText(detail.reachability ?? "NOT_VERIFIED", t)}
            </p>
            <Technical
              label={t("Existing resource link", "已有资源链接")}
              value={detail.resource_id}
            />
            <p>
              {t("Source records", "源记录")}:{" "}
              {count(detail.source_record_count)}
            </p>
            <p>
              {t("Service objects", "服务对象")}:{" "}
              {count(detail.service_object_count)}
            </p>
          </div>
          <details>
            <summary className="cursor-pointer text-sm">
              {t("Matching reasons and limitations", "匹配依据与限制")}
            </summary>
            <NoticeList values={detail.reasons} />
          </details>
          <Technical
            label={t("History link", "历史链接")}
            value={detail.history_link}
          />
          <section>
            <h3 className="font-medium">
              {t("Port and protocol material", "端口与协议材料")}
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              {t(
                "Customer port declarations, CloudAtlas port records and flow source-side ports are different material. A port difference alone does not establish a service change or risk. Role and time may remain unknown.",
                "客户声明端口区间、云图端口记录、流量源侧观测端口分别保留。端口不同本身不构成服务变化或风险；角色和时间关系仍可能未知。",
              )}
            </p>
            <p className="mt-2 text-sm">
              {t(
                "Time relationship is unconfirmed. Source-side position does not establish a listening service or connection initiator.",
                "时间关系未确认。源侧位置不能证明服务监听或连接发起方。",
              )}
            </p>
            <section
              className="mt-2 overflow-x-auto"
              aria-label={t("Service material table", "服务材料表格")}
            >
              <table className="w-full min-w-[64rem] text-left text-sm [&_td]:align-top">
                <thead>
                  <tr className="border-b">
                    <th className="p-2">{t("Object", "对象")}</th>
                    <th className="p-2">{t("Source", "来源")}</th>
                    <th className="p-2">{t("Protocol", "协议")}</th>
                    <th className="p-2">{t("Port", "端口")}</th>
                    <th className="p-2">{t("Assessment", "判断")}</th>
                    <th className="p-2">{t("Comparisons", "比较")}</th>
                  </tr>
                </thead>
                <tbody>
                  {services?.data.map((service: ServicePublic) => (
                    <tr key={service.object_key} className="border-b">
                      <td className="min-w-72 max-w-sm break-all p-2 font-mono">
                        {netflowText(service.source, t)} ·{" "}
                        {netflowProtocol(service.protocol_number, t)}/
                        {service.local_port ?? "—"}
                        <Technical
                          label={t("Object identifier", "对象标识")}
                          value={service.object_key}
                        />
                        <Technical
                          label={t("Original material", "原始材料")}
                          value={service.original}
                        />
                        <NoticeList values={service.reasons} />
                      </td>
                      <td className="p-2">{netflowText(service.source, t)}</td>
                      <td className="p-2">
                        {netflowProtocol(service.protocol_number, t)}
                      </td>
                      <td className="p-2">{servicePortText(service, t)}</td>
                      <td className="p-2">
                        {netflowText(
                          service.assessment ?? "INSUFFICIENT_EVIDENCE",
                          t,
                        )}{" "}
                        · {netflowText(service.role_state ?? "UNKNOWN", t)} ·{" "}
                        {netflowText(service.reachability ?? "NOT_VERIFIED", t)}
                      </td>
                      <td className="p-2">
                        {(
                          [
                            ["CUSTOMER", service.customer_comparisons],
                            ["CLOUD", service.cloud_comparisons],
                          ] as const
                        ).map(([source, comparisons]) => (
                          <details key={source} className="min-w-64 space-y-2">
                            <summary className="cursor-pointer">
                              {netflowText(source, t)} ·{" "}
                              {t("Current page / total", "当前页 / 总数")}:{" "}
                              {comparisons.data.length} / {comparisons.count}
                            </summary>
                            {comparisons.data.map((item) => (
                              <details
                                key={`${item.domain}:${item.version_id}:${item.record_key}`}
                                className="rounded border p-2"
                              >
                                <summary className="cursor-pointer break-all">
                                  {t("Source comparison", "来源比较")} ·{" "}
                                  {netflowText(item.protocol_relation, t)} /{" "}
                                  {netflowText(item.port_relation, t)}
                                </summary>
                                <p className="break-all">
                                  {t("Version", "版本")}: {item.version_id}
                                </p>
                                <p>
                                  {t("Protocol", "协议")}:{" "}
                                  {netflowText(item.protocol_relation, t)}
                                </p>
                                <p>
                                  {t("Port", "端口")}:{" "}
                                  {netflowText(item.port_relation, t)}
                                </p>
                                <p>
                                  {t("Time", "时间")}:{" "}
                                  {netflowText(
                                    item.time_relation ?? "UNKNOWN",
                                    t,
                                  )}
                                </p>
                                <NoticeList values={item.reasons} />
                              </details>
                            ))}
                          </details>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
            <ResultPagination
              label="Services"
              count={services?.count ?? 0}
              page={servicePage}
              pageSize={services?.limit ?? PAGE_SIZE}
              onPageChange={onServicePage}
            />
            <p className="text-sm text-muted-foreground">
              {t("Service objects on this page", "当前页服务对象")}:{" "}
              {count(services?.data.length)} ·{" "}
              {t("All objects for this address", "此地址对象总数")}:{" "}
              {count(services?.count)}
            </p>
            <div className="flex flex-wrap gap-2 text-sm">
              <Button
                variant="outline"
                disabled={comparisonPage === 0}
                onClick={() => onComparisonPage(comparisonPage - 1)}
              >
                {t("Previous comparisons", "上一页比较")}
              </Button>
              <span>
                {t("Comparison page", "比较页")} {comparisonPage + 1}
              </span>
              <Button
                variant="outline"
                onClick={() => onComparisonPage(comparisonPage + 1)}
                disabled={
                  !services?.data.some(
                    (service) =>
                      service.customer_comparisons.count >
                        (comparisonPage + 1) * COMPARISON_SIZE ||
                      service.cloud_comparisons.count >
                        (comparisonPage + 1) * COMPARISON_SIZE,
                  )
                }
              >
                {t("Next comparisons", "下一页比较")}
              </Button>
            </div>
          </section>
          <section
            id="address-source-evidence"
            tabIndex={-1}
            className="scroll-mt-6"
          >
            <h3 className="font-medium">{t("Source evidence", "来源证据")}</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {(["customer", "cloud", "netflow"] as const).map((source) => (
                <Button
                  key={source}
                  variant={evidenceSource === source ? "default" : "outline"}
                  onClick={() => onEvidenceSource(source)}
                >
                  {netflowText(source.toUpperCase(), t)}
                </Button>
              ))}
            </div>
            {evidence && (
              <>
                <p className="mt-2 text-sm text-muted-foreground">
                  {t("Current page", "当前页")}: {evidence.data.length} ·{" "}
                  {t("Filtered count", "筛选总数")}: {evidence.count} ·{" "}
                  {t("Omitted", "省略记录")} {evidence.omitted_count}
                </p>
                <div className="space-y-2">
                  {evidence.data.map((row, index) => (
                    <details
                      key={`${row.source}:${row.record_key}`}
                      className="rounded border p-2"
                    >
                      <summary className="cursor-pointer font-mono text-sm">
                        {netflowText(row.source.toUpperCase(), t)} ·{" "}
                        {t("Record", "记录")} {evidence.skip + index + 1}
                      </summary>
                      <Technical
                        label={t("Record identifiers", "记录标识")}
                        value={{
                          record_key: row.record_key,
                          version_id: row.version_id,
                          domain: row.domain,
                        }}
                      />
                      <Technical
                        label={t("Original", "原始字段")}
                        value={row.original}
                      />
                      <Technical
                        label={t("Availability", "字段可用性")}
                        value={row.availability}
                      />
                    </details>
                  ))}
                </div>
                <ResultPagination
                  label="Evidence"
                  count={evidence.count}
                  page={evidencePage}
                  pageSize={evidence.limit}
                  onPageChange={onEvidencePage}
                />
              </>
            )}
          </section>
        </>
      )}
    </section>
  )
}

function PeersView({
  peers,
  error,
  onPage,
}: {
  peers: Awaited<ReturnType<typeof NetflowReviewsService.readPeers>> | undefined
  error: unknown
  onPage: (page: number) => void
}) {
  const { t } = useI18n()
  if (error) return <ErrorNotice error={error} />
  return (
    <section className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {t(
          "Peers are an independent destination-side collection; they are not source addresses, services, Resources or Runs.",
          "peers 是独立目的侧集合，不是源地址、服务、Resource 或 Run。",
        )}
      </p>
      <section
        className="overflow-x-auto"
        aria-label={t("Peer table", "对端表格")}
      >
        <table className="w-full min-w-[40rem] text-left text-sm">
          <thead>
            <tr className="border-b">
              <th className="p-2">Peer</th>
              <th className="p-2">IP</th>
              <th className="p-2">{t("Protocol", "协议")}</th>
              <th className="p-2">{t("Port", "端口")}</th>
              <th className="p-2">{t("Records", "记录")}</th>
            </tr>
          </thead>
          <tbody>
            {peers?.data.map((peer) => (
              <tr key={peer.peer_key} className="border-b">
                <td className="p-2">
                  <Technical
                    label={t("Peer identifier", "对端标识")}
                    value={peer.peer_key}
                  />
                </td>
                <td className="p-2 font-mono">{peer.canonical_ip}</td>
                <td className="p-2">{peer.protocol_number}</td>
                <td className="p-2">{peer.peer_port ?? "—"}</td>
                <td className="p-2">{peer.source_record_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <ResultPagination
        label="Peers"
        count={peers?.count ?? 0}
        page={peers?.skip ? Math.floor(peers.skip / peers.limit) : 0}
        pageSize={peers?.limit ?? PAGE_SIZE}
        onPageChange={onPage}
      />
      <p className="text-sm text-muted-foreground">
        {t("Current page", "当前页")}: {peers?.data.length ?? 0} ·{" "}
        {t("Filtered total", "筛选总数")}: {count(peers?.count)} ·{" "}
        {t("All peers", "全量 peers")}: {peers?.total_peers ?? "—"} ·{" "}
        {t("All peer records", "全量 peer 记录")}:{" "}
        {peers?.total_peer_records ?? "—"}
      </p>
    </section>
  )
}

function taskName(
  task: Record<string, unknown>,
  t: (en: string, zh: string) => string,
) {
  const target =
    task.target && typeof task.target === "object"
      ? (task.target as Record<string, unknown>)
      : undefined
  return [
    netflowText(String(task.task_kind ?? task.title ?? "Review material"), t),
    target?.ip,
    target?.local_port,
  ]
    .filter((value) => value !== null && value !== undefined)
    .join(" · ")
}

function TasksView({
  canWrite,
  tasks,
  task,
  feedback,
  error,
  status,
  onStatus,
  onPage,
  onTask,
  projectId,
  actor,
  analysisId,
  feedbackRevision,
  onFeedback,
}: {
  canWrite: boolean
  tasks: Awaited<ReturnType<typeof NetflowReviewsService.readTasks>> | undefined
  task: Awaited<ReturnType<typeof NetflowReviewsService.readTask>> | undefined
  feedback: FeedbackPublic | undefined
  error: unknown
  status: TaskMaterial["material_status"] | undefined
  onStatus: (status: TaskMaterial["material_status"] | undefined) => void
  onPage: (page: number) => void
  onTask: (taskId: string) => void
  projectId: string
  actor: string
  analysisId: string | undefined
  feedbackRevision: string | undefined
  onFeedback: (revision: string) => void
}) {
  const { t } = useI18n()
  const cache = useQueryClient()
  const [answers, setAnswers] = useState<Record<string, unknown>>({})
  const [answersSupported, setAnswersSupported] = useState(true)
  const [answersValid, setAnswersValid] = useState(true)
  const updateAnswers = useCallback(
    (value: Record<string, unknown>, supported: boolean, valid: boolean) => {
      setAnswers(value)
      setAnswersSupported(supported)
      setAnswersValid(valid)
    },
    [],
  )
  const [providedBy, setProvidedBy] = useState("")
  const [submittedAt, setSubmittedAt] = useState("")
  const [note, setNote] = useState("")
  const [saving, setSaving] = useState(false)
  const [feedbackError, setFeedbackError] = useState<[string, string]>()
  const feedbackStore = `exposure:netflow-feedback:${actor}:${projectId}:${analysisId ?? "none"}:${feedbackRevision ?? "none"}:${task?.material.task_id ?? "none"}`
  const feedbackScopeRef = useRef(feedbackStore)
  feedbackScopeRef.current = feedbackStore
  useEffect(() => {
    feedbackScopeRef.current = feedbackStore
    return () => {
      feedbackScopeRef.current = "unmounted"
    }
  }, [feedbackStore])
  const [pendingFeedbackKey, setPendingFeedbackKey] = useState<string>()
  useEffect(() => {
    try {
      const stored = sessionStorage.getItem(feedbackStore)
      setPendingFeedbackKey(stored || undefined)
    } catch {
      setPendingFeedbackKey(undefined)
    }
  }, [feedbackStore])
  const initialClaim = task?.material.provider_claim
  const initialProvidedBy =
    typeof initialClaim?.provided_by === "string"
      ? initialClaim.provided_by
      : ""
  const initialSubmittedAt =
    typeof initialClaim?.submitted_at === "string"
      ? initialClaim.submitted_at
      : ""
  useEffect(() => {
    setProvidedBy(initialProvidedBy)
    setSubmittedAt(initialSubmittedAt)
  }, [initialProvidedBy, initialSubmittedAt])
  if (error) return <ErrorNotice error={error} />
  if (!feedback)
    return (
      <p className="text-sm text-muted-foreground">
        {t("Feedback revision is unavailable.", "反馈修订不可读取。")}
      </p>
    )
  const recoverFeedback = async () => {
    if (!analysisId || !pendingFeedbackKey) return
    const capturedFeedbackStore = feedbackStore
    try {
      const revision = await NetflowReviewsService.readOperation({
        projectId,
        analysisId,
        key: pendingFeedbackKey,
      })
      if (feedbackScopeRef.current !== capturedFeedbackStore) return
      sessionStorage.removeItem(feedbackStore)
      setPendingFeedbackKey(undefined)
      cache.setQueriesData(
        {
          predicate: (query) =>
            query.queryKey[0] === "netflow-correlation" &&
            query.queryKey[2] === "current-feedback" &&
            query.queryKey[3] === analysisId,
        },
        revision,
      )
      onFeedback(revision.feedback_revision_id)
    } catch {
      if (feedbackScopeRef.current !== capturedFeedbackStore) return
      setFeedbackError([
        "The original feedback operation is still unavailable.",
        "原反馈操作仍不可读取。",
      ])
    }
  }
  const save = async () => {
    if (
      !canWrite ||
      saving ||
      pendingFeedbackKey ||
      !task ||
      !feedback ||
      !analysisId ||
      !feedbackRevision
    )
      return
    const capturedFeedbackStore = feedbackStore
    if (!answersSupported) return
    const operationKey = crypto.randomUUID()
    try {
      sessionStorage.setItem(feedbackStore, operationKey)
    } catch {
      setFeedbackError(["Recovery storage is unavailable.", "恢复存储不可用。"])
      return
    }
    setPendingFeedbackKey(operationKey)
    setSaving(true)
    setFeedbackError(undefined)
    try {
      const revision = await NetflowReviewsService.appendFeedback({
        projectId,
        analysisId,
        idempotencyKey: operationKey,
        requestBody: {
          expected_parent_id: feedbackRevision,
          responses: [
            {
              task_id: task.material.task_id,
              provided_by: providedBy || null,
              submitted_at: submittedAt || null,
              answers,
              note_checks: task.material.note_checks,
            },
          ],
          human_note: note || null,
        },
      })
      if (feedbackScopeRef.current !== capturedFeedbackStore) return
      sessionStorage.removeItem(feedbackStore)
      setPendingFeedbackKey(undefined)
      cache.setQueriesData(
        {
          predicate: (query) =>
            query.queryKey[0] === "netflow-correlation" &&
            query.queryKey[2] === "current-feedback" &&
            query.queryKey[3] === analysisId,
        },
        revision,
      )
      onFeedback(revision.feedback_revision_id)
      setNote("")
    } catch (error) {
      if (feedbackScopeRef.current !== capturedFeedbackStore) return
      if (isClientError(error)) {
        sessionStorage.removeItem(feedbackStore)
        setPendingFeedbackKey(undefined)
      }
      const code = errorCode(error)
      setFeedbackError(
        code
          ? [netflowText(code, (en) => en), netflowText(code, (_, zh) => zh)]
          : [
              "Feedback was rejected; the previous version remains.",
              "反馈被拒绝；上一版本保持不变。",
            ],
      )
    } finally {
      if (feedbackScopeRef.current === capturedFeedbackStore) setSaving(false)
    }
  }
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Label>
          {t("Material status", "材料状态")}
          <select
            className="mt-1 block rounded border bg-background p-2"
            value={status ?? ""}
            onChange={(event) =>
              onStatus(
                (event.target.value || undefined) as
                  | TaskMaterial["material_status"]
                  | undefined,
              )
            }
          >
            <option value="">{t("All statuses", "全部状态")}</option>
            {[
              "AWAITING_FEEDBACK",
              "MATERIAL_INCOMPLETE",
              "INVALID_MATERIAL",
              "MATERIAL_CONFLICT",
              "AWAITING_DEPENDENCY_MATERIAL",
              "FIELDS_COMPLETE_PENDING_REVIEW",
            ].map((value) => (
              <option key={value} value={value}>
                {netflowText(value, t)}
              </option>
            ))}
          </select>
        </Label>
        <span className="self-end text-sm text-muted-foreground">
          {t("Feedback revision", "反馈修订")}: {feedback.revision}
          <Technical
            label={t("Feedback identifier", "反馈标识")}
            value={feedbackRevision}
          />
        </span>
        {pendingFeedbackKey && (
          <Button variant="outline" onClick={() => void recoverFeedback()}>
            {t("Query original feedback operation", "查询原反馈操作")}
          </Button>
        )}
      </div>
      <section
        className="overflow-x-auto"
        aria-label={t("Task table", "任务表格")}
      >
        <table className="w-full min-w-[48rem] text-left text-sm">
          <thead>
            <tr className="border-b">
              <th className="p-2">{t("Material", "材料")}</th>
              <th className="p-2">{t("Status", "状态")}</th>
              <th className="p-2">{t("Scope", "范围")}</th>
              <th className="p-2">{t("Next action", "下一步")}</th>
            </tr>
          </thead>
          <tbody>
            {tasks?.data.map((item) => (
              <tr
                key={item.task_id}
                className={`border-b ${task?.material.task_id === item.task_id ? "bg-muted" : ""}`}
              >
                <td className="p-2">
                  <Button
                    variant="link"
                    className="h-auto p-0"
                    onClick={() => onTask(item.task_id)}
                  >
                    {taskName(item.task, t)}
                  </Button>
                </td>
                <td className="p-2">{netflowText(item.material_status, t)}</td>
                <td className="p-2">
                  {netflowText(
                    String(item.task.task_scope ?? item.task.task_kind ?? "—"),
                    t,
                  )}
                </td>
                <td className="p-2">
                  <BusinessNextAction
                    status={item.material_status}
                    missing={item.missing_fields}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <ResultPagination
        label="Review tasks"
        count={tasks?.count ?? 0}
        page={tasks?.skip ? Math.floor(tasks.skip / tasks.limit) : 0}
        pageSize={tasks?.limit ?? PAGE_SIZE}
        onPageChange={onPage}
      />
      <p className="text-sm text-muted-foreground">
        {t("Current page", "当前页")}: {tasks?.data.length ?? 0} ·{" "}
        {t("Filtered count", "筛选总数")}: {tasks?.count ?? "—"} ·{" "}
        {t("All tasks", "任务总数")}: {tasks?.total_tasks ?? "—"}
      </p>
      {task && (
        <section className="space-y-3 rounded-md border p-4">
          <h2 className="font-semibold">{t("Task detail", "任务详情")}</h2>
          <p className="text-sm">
            {t("Status", "状态")}:{" "}
            {netflowText(task.material.material_status, t)}
          </p>
          <NoticeList
            values={task.material.missing_fields.map((field) =>
              businessField(field, t),
            )}
          />
          <NoticeList
            values={task.material.field_errors.map(
              (item) =>
                `${businessField(String(item.field), t)}: ${netflowText(String(item.code), t)}`,
            )}
          />
          <Technical
            label={t("Task ID", "任务 ID")}
            value={task.material.task_id}
          />
          <Technical
            label={t("Task material", "任务材料")}
            value={task.material.task}
          />
          <Technical
            label={t("Server next action", "服务端下一步")}
            value={task.material.next_action}
          />
          <Technical
            label={t("Answer schema", "答案 Schema")}
            value={task.material.answer_schema}
          />
          <Technical
            label={t("Provider declaration", "提供方声明")}
            value={task.material.provider_claim}
          />
          <Technical
            label={t("Actual task author", "实际任务提交者")}
            value={task.material.authenticated_author}
          />
          {task.material.blocked_by.length > 0 && (
            <p>
              {t(
                "Complete the shared material listed below first.",
                "请先补齐下列共享材料。",
              )}
            </p>
          )}
          {task.dependencies.length > 0 && (
            <section className="space-y-2">
              <h3>{t("Shared dependencies", "共享依赖")}</h3>
              {task.dependencies.map((dependency) => (
                <div key={dependency.task_id}>
                  <Button
                    variant="link"
                    className="h-auto max-w-full whitespace-normal break-all"
                    onClick={() => onTask(dependency.task_id)}
                  >
                    {taskName(dependency.task, t)}
                  </Button>
                  <p>{netflowText(dependency.material_status, t)}</p>
                </div>
              ))}
            </section>
          )}
          <Label>
            {t("Declared provider", "声明提供方")}
            <Input
              value={providedBy}
              maxLength={128}
              disabled={!canWrite || saving || Boolean(pendingFeedbackKey)}
              onChange={(event) => setProvidedBy(event.target.value)}
            />
          </Label>
          <Label>
            {t(
              "Declared submission time (ISO 8601)",
              "声明提交时间（ISO 8601）",
            )}
            <Input
              value={submittedAt}
              disabled={!canWrite || saving || Boolean(pendingFeedbackKey)}
              onChange={(event) => setSubmittedAt(event.target.value)}
            />
          </Label>
          <NetflowTaskAnswers
            identity={`${feedbackRevision ?? "none"}:${task.material.task_id}`}
            schema={task.material.answer_schema}
            declared={task.material.declared_answers}
            serverErrors={task.material.field_errors}
            disabled={!canWrite || saving || Boolean(pendingFeedbackKey)}
            onChange={updateAnswers}
          />
          <Label>
            {t("Human note", "人工说明")}
            <Input
              value={note}
              maxLength={2048}
              onChange={(event) => setNote(event.target.value)}
              disabled={!canWrite || saving || Boolean(pendingFeedbackKey)}
            />
          </Label>
          <Button
            onClick={() => void save()}
            disabled={
              !canWrite ||
              saving ||
              Boolean(pendingFeedbackKey) ||
              !feedback ||
              !feedbackRevision ||
              !answersSupported ||
              !answersValid
            }
          >
            {t("Append correction", "追加更正")}
          </Button>
          {feedbackError && (
            <p role="alert" className="text-sm text-destructive">
              {t(...feedbackError)}
            </p>
          )}
          <div className="grid gap-2 text-sm md:grid-cols-3">
            <p>
              {t("Review required", "需要人工复核")}:{" "}
              {task.material.review_required === true ? t("Yes", "是") : "—"}
            </p>
            <p>
              {t("Task closed", "任务关闭")}:{" "}
              {task.material.task_closed === false ? t("No", "否") : "—"}
            </p>
            <p>
              {t("Facts changed", "事实变化")}:{" "}
              {task.material.facts_changed === false ? t("No", "否") : "—"}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <span>
              {t("Feedback history", "反馈历史")}: {feedback.revision}
            </span>
            {feedback.parent_id && (
              <Button
                variant="outline"
                onClick={() => onFeedback(feedback.parent_id!)}
              >
                {t("Read parent revision", "读取父修订")}
              </Button>
            )}
            <Technical
              label={t("Authenticated submitter", "实际提交身份")}
              value={{
                actor: feedback.authenticated_actor_id,
                submitted_at: feedback.authenticated_submitted_at,
              }}
            />
          </div>
        </section>
      )}
    </section>
  )
}

const businessFields: Record<string, [string, string]> = {
  provided_by: ["declared provider", "声明提供方"],
  submitted_at: ["declared submission time", "声明提交时间"],
  depends_on: ["shared material", "共享材料"],
  mode: ["mode", "方式"],
  rate: ["rate", "比例"],
  responsible_unit: ["responsible unit", "责任单位"],
  supporting_evidence: ["supporting evidence", "材料引用"],
  additional_dataset: ["additional dataset", "补充数据集"],
  coverage_notes: ["coverage notes", "覆盖说明"],
  observation_window: ["observation window", "观测时间窗"],
  counter_semantics: ["counter semantics", "计数语义"],
  direction_semantics: ["direction semantics", "方向语义"],
  export_selection: ["export selection", "导出选择"],
  input_timezone: ["input timezone", "输入时区"],
  observation_view: ["observation view", "观测视角"],
  sampling: ["sampling", "采样情况"],
  nat_mapping: ["NAT mapping", "NAT 映射"],
  mapping_time_window: ["mapping time window", "映射时间窗"],
  actual_service: ["actual service", "实际服务"],
  business_purpose: ["business purpose", "业务用途"],
  business_role: ["business role", "业务角色"],
  external_access_need: ["external access need", "对外访问需求"],
  access_control: ["access control", "访问控制"],
  cause_assessment: ["cause assessment", "原因判断"],
}

function businessField(value: string, t: (en: string, zh: string) => string) {
  return value
    .split(".")
    .map((part) => {
      const pair = businessFields[part]
      return pair ? t(...pair) : part
    })
    .join(" / ")
}

function BusinessNextAction({
  status,
  missing,
}: {
  status: TaskMaterial["material_status"]
  missing: string[]
}) {
  const { t } = useI18n()
  if (status === "FIELDS_COMPLETE_PENDING_REVIEW")
    return <>{t("Await human review", "等待人工复核")}</>
  if (status === "MATERIAL_CONFLICT")
    return <>{t("Resolve conflicting material", "处理冲突材料")}</>
  if (status === "INVALID_MATERIAL")
    return <>{t("Correct invalid material", "更正无效材料")}</>
  if (status === "AWAITING_DEPENDENCY_MATERIAL")
    return <>{t("Wait for shared material", "等待共享材料")}</>
  return missing.length ? (
    <>
      {t("Provide: ", "请补充：")}
      {missing.map((field) => businessField(field, t)).join(", ")}
    </>
  ) : (
    t("Add review material", "补充复核材料")
  )
}
