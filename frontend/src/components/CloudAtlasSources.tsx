import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import {
  type CloudAtlasSourcePublic,
  CloudatlasSourceInstancesService,
} from "@/client"
import { useLocale } from "@/components/LocaleProvider"
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

type Text = (zh: string, en: string) => string

function validationLabel(status: string, text: Text): string {
  return (
    {
      validated: text("已验证", "Validated"),
      invalid: text("无效", "Invalid"),
      failed: text("失败", "Failed"),
      unavailable: text("不可用", "Unavailable"),
      not_validated: text("未验证", "Not validated"),
    }[status] ?? text("未知", "Unknown")
  )
}

function SourceRows({
  sources,
  canManage,
  selectedSourceId,
  onSelect,
  text,
}: {
  sources: CloudAtlasSourcePublic[]
  canManage: boolean
  selectedSourceId: string | null
  onSelect: (sourceId: string) => void
  text: Text
}) {
  if (sources.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {text("尚未配置 CloudAtlas 来源实例。", "No CloudAtlas SourceInstance configured.")}
      </p>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{text("实例绑定", "Instance binding")}</TableHead>
          <TableHead>Capset</TableHead>
          <TableHead>{text("验证", "Validation")}</TableHead>
          <TableHead>{text("指纹", "Fingerprint")}</TableHead>
          <TableHead>{text("状态", "State")}</TableHead>
          {canManage && <TableHead>{text("操作", "Action")}</TableHead>}
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
                {validationLabel(source.validation_status, text)}
              </Badge>
            </TableCell>
            <TableCell className="font-mono text-xs">
              {source.fingerprint_summary ?? "—"}
            </TableCell>
            <TableCell>
              <Badge variant={source.enabled ? "default" : "outline"}>
                {source.enabled ? text("已启用", "Enabled") : text("已停用", "Disabled")}
              </Badge>
            </TableCell>
            {canManage && (
              <TableCell>
                {source.id === selectedSourceId ? (
                  <Badge variant="secondary">{text("正在管理", "Managing")}</Badge>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => onSelect(source.id)}
                  >
                    {text("管理来源", "Manage source")}
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
  const { text } = useLocale()
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
      setMessage(text("CloudAtlas 绑定已保存，需要验证。", "CloudAtlas binding saved. Validation is required."))
      await refresh()
    },
    onError: () => setMessage(text("无法保存 CloudAtlas 绑定。", "The CloudAtlas binding could not be saved.")),
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
      setMessage(text("CloudAtlas 来源验证成功。", "CloudAtlas source validated successfully."))
      await refresh()
    },
    onError: () => setMessage(text("CloudAtlas 来源验证失败。", "CloudAtlas source validation failed.")),
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
        enabled ? text("CloudAtlas 来源已启用。", "CloudAtlas source enabled.") : text("CloudAtlas 来源已停用。", "CloudAtlas source disabled."),
      )
      await refresh()
    },
    onError: () =>
      setMessage(text("无法更改 CloudAtlas 来源状态。", "The CloudAtlas source state could not be changed.")),
  })

  if (sourcesQuery.isPending) {
    return <p role="status">{text("正在加载 CloudAtlas 来源…", "Loading CloudAtlas source…")}</p>
  }
  if (sourcesQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>{text("无法加载 CloudAtlas 来源", "CloudAtlas source could not be loaded")}</AlertTitle>
        <AlertDescription>{text("请稍后重试。", "Please try again later.")}</AlertDescription>
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
        <CardTitle>{text("CloudAtlas 来源", "CloudAtlas source")}</CardTitle>
        <CardDescription>
          {text("只读的 OctoBus 实例与 Capset 绑定。凭据仍保留在 OctoBus 中。", "Read-only OctoBus Instance and Capset binding. Credentials remain in OctoBus.")}
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
          text={text}
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
                {text("添加来源绑定", "Add source binding")}
              </Button>
            )}
            <form
              className="grid gap-3 md:grid-cols-[1fr_1fr_auto] md:items-end"
              onSubmit={(event) => {
                event.preventDefault()
                setMessage(null)
                bindingMutation.mutate()
              }}
            >
              <div className="space-y-2">
                <Label htmlFor={`cloudatlas-instance-${projectId}`}>
                  {text("OctoBus 实例 ID", "OctoBus Instance ID")}
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
                  {text("只读 Capset ID", "Read-only Capset ID")}
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
                {text("保存绑定", "Save binding")}
              </LoadingButton>
            </form>

            {source && (
              <div className="grid gap-3 md:grid-cols-[1fr_auto_auto] md:items-end">
                <div className="space-y-2">
                  <Label htmlFor={`cloudatlas-token-${projectId}`}>
                    {text("Capset 令牌", "Capset token")}
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
                    {text("仅用于本次验证请求；Exposure-Agent 不会显示或保存该令牌。", "Used only for this validation request and never displayed or stored by Exposure-Agent.")}
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
                  {text("验证来源", "Validate source")}
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
                  {source.enabled ? text("停用来源", "Disable source") : text("启用来源", "Enable source")}
                </LoadingButton>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {text("你对此 CloudAtlas 来源摘要只有只读权限。", "You have read-only access to this CloudAtlas source summary.")}
          </p>
        )}

        {message && (
          <p className="text-sm" role="status">
            {message}
          </p>
        )}
        {source?.validation_status === "unavailable" ? (
          <Alert>
          <AlertTitle>{text("验证检查不可用", "Validation check unavailable")}</AlertTitle>
            <AlertDescription>
              {text("已存验证未失效，但无法确认当前 OctoBus 材料。", "The stored validation was not invalidated, but the current OctoBus material could not be confirmed.")}
            </AlertDescription>
          </Alert>
        ) : (
          source &&
          source.validation_status !== "validated" && (
            <Alert>
              <AlertTitle>{text("来源尚未就绪", "Source not ready")}</AlertTitle>
              <AlertDescription>
                {text("当前绑定必须通过单个只读方法验证后才能启用。", "The current binding must pass the single read-only method before it can be enabled.")}
              </AlertDescription>
            </Alert>
          )
        )}
      </CardContent>
    </Card>
  )
}
