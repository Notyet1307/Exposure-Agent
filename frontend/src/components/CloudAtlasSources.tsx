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

function validationLabel(status: string): string {
  return (
    {
      validated: "Validated",
      invalid: "Invalid",
      failed: "Failed",
      unavailable: "Unavailable",
      not_validated: "Not validated",
    }[status] ?? "Unknown"
  )
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
  if (sources.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No CloudAtlas SourceInstance configured.
      </p>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Instance binding</TableHead>
          <TableHead>Capset</TableHead>
          <TableHead>Validation</TableHead>
          <TableHead>Fingerprint</TableHead>
          <TableHead>State</TableHead>
          {canManage && <TableHead>Action</TableHead>}
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
                {validationLabel(source.validation_status)}
              </Badge>
            </TableCell>
            <TableCell className="font-mono text-xs">
              {source.fingerprint_summary ?? "—"}
            </TableCell>
            <TableCell>
              <Badge variant={source.enabled ? "default" : "outline"}>
                {source.enabled ? "Enabled" : "Disabled"}
              </Badge>
            </TableCell>
            {canManage && (
              <TableCell>
                {source.id === selectedSourceId ? (
                  <Badge variant="secondary">Managing</Badge>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => onSelect(source.id)}
                  >
                    Manage source
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
    return <p role="status">Loading CloudAtlas source…</p>
  }
  if (sourcesQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>CloudAtlas source could not be loaded</AlertTitle>
        <AlertDescription>Please try again later.</AlertDescription>
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
        <CardTitle>CloudAtlas source</CardTitle>
        <CardDescription>
          Read-only OctoBus Instance and Capset binding. Credentials remain in
          OctoBus.
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
                Add source binding
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
                  OctoBus Instance ID
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
                  Read-only Capset ID
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
                Save binding
              </LoadingButton>
            </form>

            {source && (
              <div className="grid gap-3 md:grid-cols-[1fr_auto_auto] md:items-end">
                <div className="space-y-2">
                  <Label htmlFor={`cloudatlas-token-${projectId}`}>
                    Capset token
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
                    Used only for this validation request and never displayed or
                    stored by Exposure-Agent.
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
                  Validate source
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
                  {source.enabled ? "Disable source" : "Enable source"}
                </LoadingButton>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            You have read-only access to this CloudAtlas source summary.
          </p>
        )}

        {message && (
          <p className="text-sm" role="status">
            {message}
          </p>
        )}
        {source?.validation_status === "unavailable" ? (
          <Alert>
            <AlertTitle>Validation check unavailable</AlertTitle>
            <AlertDescription>
              The stored validation was not invalidated, but the current OctoBus
              material could not be confirmed.
            </AlertDescription>
          </Alert>
        ) : (
          source &&
          source.validation_status !== "validated" && (
            <Alert>
              <AlertTitle>Source not ready</AlertTitle>
              <AlertDescription>
                The current binding must pass the single read-only method before
                it can be enabled.
              </AlertDescription>
            </Alert>
          )
        )}
      </CardContent>
    </Card>
  )
}
