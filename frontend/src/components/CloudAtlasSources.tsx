import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import {
  type CloudAtlasSourcePublic,
  CloudatlasSourceInstancesService,
} from "@/client"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
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

const VALIDATION_LABELS: Record<string, [string, string]> =
  Object.setPrototypeOf(
    {
      validated: ["Validated", "已验证 (validated)"],
      invalid: ["Invalid", "无效 (invalid)"],
      failed: ["Failed", "失败 (failed)"],
      unavailable: ["Unavailable", "暂不可用 (unavailable)"],
      not_validated: ["Not validated", "未验证 (not_validated)"],
    },
    null,
  )

const MESSAGE_ZH: Record<string, string> = {
  "CloudAtlas binding saved. Validation is required.":
    "CloudAtlas 绑定已保存，需要验证。",
  "The CloudAtlas binding could not be saved.": "无法保存 CloudAtlas 绑定。",
  "CloudAtlas source validated successfully.": "CloudAtlas 来源验证成功。",
  "CloudAtlas source validation failed.": "CloudAtlas 来源验证失败。",
  "CloudAtlas source enabled.": "CloudAtlas 来源已启用。",
  "CloudAtlas source disabled.": "CloudAtlas 来源已停用。",
  "The CloudAtlas source state could not be changed.":
    "无法更改 CloudAtlas 来源状态。",
  "OctoBus Instance ID and Read-only Capset ID are required.":
    "请输入 OctoBus 实例 ID 和只读 Capset ID。",
}

function SourceRows({
  sources,
  canManage,
  selectedSourceId,
  onSelect,
}: {
  sources: CloudAtlasSourcePublic[]
  canManage: boolean
  selectedSourceId: string | null
  onSelect: (sourceId: string) => void
}) {
  const { t } = useI18n()
  if (sources.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {t(
          "No CloudAtlas SourceInstance configured.",
          "尚未配置 CloudAtlas 来源实例。",
        )}
      </p>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("Instance binding", "实例绑定")}</TableHead>
          <TableHead>{t("Capset", "能力集（Capset）")}</TableHead>
          <TableHead>{t("Validation", "验证")}</TableHead>
          <TableHead>{t("Fingerprint", "指纹")}</TableHead>
          <TableHead>{t("State", "状态")}</TableHead>
          {canManage && <TableHead>{t("Action", "操作")}</TableHead>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {sources.map((source) => (
          <TableRow key={source.id}>
            <TableCell className="font-mono text-xs">
              {source.instance_id}
            </TableCell>
            <TableCell className="font-mono text-xs">
              {source.capset_id}
            </TableCell>
            <TableCell>
              <Badge
                variant={
                  source.validation_status === "validated"
                    ? "default"
                    : "secondary"
                }
              >
                {VALIDATION_LABELS[source.validation_status]
                  ? t(...VALIDATION_LABELS[source.validation_status])
                  : source.validation_status}
              </Badge>
            </TableCell>
            <TableCell className="font-mono text-xs">
              {source.fingerprint_summary ?? "—"}
            </TableCell>
            <TableCell>
              <Badge variant={source.enabled ? "default" : "outline"}>
                {source.enabled
                  ? t("Enabled", "已启用")
                  : t("Disabled", "已停用")}
              </Badge>
            </TableCell>
            {canManage && (
              <TableCell>
                {source.id === selectedSourceId ? (
                  <Badge variant="secondary">{t("Managing", "管理中")}</Badge>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => onSelect(source.id)}
                  >
                    {t("Manage source", "管理来源")}
                  </Button>
                )}
              </TableCell>
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

export default function CloudAtlasSources({
  projectId,
}: {
  projectId: string
}) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null)
  const [isAddingSource, setIsAddingSource] = useState(false)
  const [instanceId, setInstanceId] = useState("")
  const [capsetId, setCapsetId] = useState("")
  const [capsetToken, setCapsetToken] = useState("")
  const [message, setMessage] = useState<string | null>(null)
  const queryKey = ["cloudatlas-source-instances", projectId]
  const sourcesQuery = useQuery({
    queryKey,
    queryFn: () =>
      CloudatlasSourceInstancesService.readCloudatlasSources({ projectId }),
  })
  const source = isAddingSource
    ? undefined
    : sourcesQuery.data?.data.find(
        (candidate) => candidate.id === selectedSourceId,
      )

  useEffect(() => {
    if (isAddingSource) return
    const sources = sourcesQuery.data?.data
    if (!sources || sources.length === 0) {
      setSelectedSourceId(null)
      return
    }
    if (selectedSourceId === null) {
      setSelectedSourceId(
        sources.find((candidate) => candidate.enabled)?.id ?? sources[0].id,
      )
    }
  }, [sourcesQuery.data?.data, selectedSourceId, isAddingSource])

  useEffect(() => {
    setInstanceId(source?.instance_id ?? "")
    setCapsetId(source?.capset_id ?? "")
    setCapsetToken("")
    setMessage(null)
  }, [source?.instance_id, source?.capset_id])

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey }),
      queryClient.invalidateQueries({
        queryKey: ["governance-runs", projectId],
      }),
    ])
  }
  const bindingMutation = useMutation({
    mutationFn: () => {
      const requestBody = { instance_id: instanceId, capset_id: capsetId }
      return source
        ? CloudatlasSourceInstancesService.updateCloudatlasSource({
            projectId,
            sourceId: source.id,
            requestBody,
          })
        : CloudatlasSourceInstancesService.createCloudatlasSource({
            projectId,
            requestBody,
          })
    },
    onSuccess: async (savedSource) => {
      setIsAddingSource(false)
      setSelectedSourceId(savedSource.id)
      setMessage("CloudAtlas binding saved. Validation is required.")
      await refresh()
    },
    onError: () => setMessage("The CloudAtlas binding could not be saved."),
  })
  const validationMutation = useMutation({
    mutationFn: () => {
      if (!source) throw new Error("SourceInstance is not configured")
      return CloudatlasSourceInstancesService.validateCloudatlasSource({
        projectId,
        sourceId: source.id,
        requestBody: { capset_token: capsetToken },
      })
    },
    onSuccess: async () => {
      setMessage("CloudAtlas source validated successfully.")
      await refresh()
    },
    onError: () => setMessage("CloudAtlas source validation failed."),
    onSettled: () => setCapsetToken(""),
  })
  const stateMutation = useMutation({
    mutationFn: (enabled: boolean) => {
      if (!source) throw new Error("SourceInstance is not configured")
      return enabled
        ? CloudatlasSourceInstancesService.enableCloudatlasSource({
            projectId,
            sourceId: source.id,
          })
        : CloudatlasSourceInstancesService.disableCloudatlasSource({
            projectId,
            sourceId: source.id,
          })
    },
    onSuccess: async (_result, enabled) => {
      setMessage(
        enabled ? "CloudAtlas source enabled." : "CloudAtlas source disabled.",
      )
      await refresh()
    },
    onError: () =>
      setMessage("The CloudAtlas source state could not be changed."),
  })

  if (sourcesQuery.isPending) {
    return (
      <p role="status">
        {t("Loading CloudAtlas source…", "正在加载 CloudAtlas 来源…")}
      </p>
    )
  }
  if (sourcesQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>
          {t(
            "CloudAtlas source could not be loaded",
            "无法加载 CloudAtlas 来源",
          )}
        </AlertTitle>
        <AlertDescription>
          {t("Please try again later.", "请稍后重试。")}
        </AlertDescription>
      </Alert>
    )
  }

  const sources = sourcesQuery.data
  const busy =
    bindingMutation.isPending ||
    validationMutation.isPending ||
    stateMutation.isPending

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("CloudAtlas source", "CloudAtlas 来源")}</CardTitle>
        <CardDescription>
          {t(
            "Read-only OctoBus Instance and Capset binding. Credentials remain in OctoBus.",
            "只读 OctoBus 实例与 Capset 绑定。凭据保留在 OctoBus 中。",
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <SourceRows
          sources={sources.data}
          canManage={sources.can_manage}
          selectedSourceId={selectedSourceId}
          onSelect={(sourceId) => {
            setIsAddingSource(false)
            setSelectedSourceId(sourceId)
            setMessage(null)
          }}
        />

        {sources.can_manage ? (
          <div className="space-y-5 border-t pt-5">
            {sources.data.length > 0 && (
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setIsAddingSource(true)
                  setSelectedSourceId(null)
                  setInstanceId("")
                  setCapsetId("")
                  setCapsetToken("")
                  setMessage(null)
                }}
              >
                {t("Add source binding", "添加来源绑定")}
              </Button>
            )}
            <form
              noValidate
              className="grid gap-3 md:grid-cols-[1fr_1fr_auto] md:items-end"
              onSubmit={(event) => {
                event.preventDefault()
                setMessage(null)
                if (!instanceId || !capsetId) {
                  setMessage(
                    "OctoBus Instance ID and Read-only Capset ID are required.",
                  )
                  return
                }
                bindingMutation.mutate()
              }}
            >
              <div className="space-y-2">
                <Label htmlFor={`cloudatlas-instance-${projectId}`}>
                  {t("OctoBus Instance ID", "OctoBus 实例 ID")}
                </Label>
                <Input
                  id={`cloudatlas-instance-${projectId}`}
                  value={instanceId}
                  required
                  disabled={busy}
                  onChange={(event) => setInstanceId(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor={`cloudatlas-capset-${projectId}`}>
                  {t("Read-only Capset ID", "只读 Capset ID")}
                </Label>
                <Input
                  id={`cloudatlas-capset-${projectId}`}
                  value={capsetId}
                  required
                  disabled={busy}
                  onChange={(event) => setCapsetId(event.target.value)}
                />
              </div>
              <LoadingButton type="submit" loading={bindingMutation.isPending}>
                {t("Save binding", "保存绑定")}
              </LoadingButton>
            </form>

            {source && (
              <div className="grid gap-3 md:grid-cols-[1fr_auto_auto] md:items-end">
                <div className="space-y-2">
                  <Label htmlFor={`cloudatlas-token-${projectId}`}>
                    {t("Capset token", "Capset 令牌")}
                  </Label>
                  <Input
                    id={`cloudatlas-token-${projectId}`}
                    type="password"
                    autoComplete="off"
                    value={capsetToken}
                    disabled={busy}
                    onChange={(event) => setCapsetToken(event.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    {t(
                      "Used only for this validation request and never displayed or stored by Exposure-Agent.",
                      "仅用于此次验证请求，Exposure-Agent 不会显示或存储此令牌。",
                    )}
                  </p>
                </div>
                <LoadingButton
                  type="button"
                  variant="outline"
                  loading={validationMutation.isPending}
                  disabled={!capsetToken || busy}
                  onClick={() => {
                    setMessage(null)
                    validationMutation.mutate()
                  }}
                >
                  {t("Validate source", "验证来源")}
                </LoadingButton>
                <LoadingButton
                  type="button"
                  loading={stateMutation.isPending}
                  disabled={
                    busy ||
                    (!source.enabled &&
                      source.validation_status !== "validated")
                  }
                  onClick={() => {
                    setMessage(null)
                    stateMutation.mutate(!source.enabled)
                  }}
                >
                  {source.enabled
                    ? t("Disable source", "停用来源")
                    : t("Enable source", "启用来源")}
                </LoadingButton>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {t(
              "You have read-only access to this CloudAtlas source summary.",
              "您对此 CloudAtlas 来源摘要仅有只读权限。",
            )}
          </p>
        )}

        {message && (
          <p className="text-sm" role="status">
            {t(message, MESSAGE_ZH[message] ?? message)}
          </p>
        )}
        {source?.validation_status === "unavailable" ? (
          <Alert>
            <AlertTitle>
              {t("Validation check unavailable", "暂时无法检查验证状态")}
            </AlertTitle>
            <AlertDescription>
              {t(
                "The stored validation was not invalidated, but the current OctoBus material could not be confirmed.",
                "已存储的验证结果未失效，但当前无法确认 OctoBus 材料。",
              )}
            </AlertDescription>
          </Alert>
        ) : (
          source &&
          source.validation_status !== "validated" && (
            <Alert>
              <AlertTitle>{t("Source not ready", "来源尚未就绪")}</AlertTitle>
              <AlertDescription>
                {t(
                  "The current binding must pass the single read-only method before it can be enabled.",
                  "当前绑定必须通过该唯一只读方法的验证后才能启用。",
                )}
              </AlertDescription>
            </Alert>
          )
        )}
      </CardContent>
    </Card>
  )
}
