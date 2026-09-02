import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import {
  type AiDraftEditedOutput,
  type AiDraftModelOutput,
  type AiGovernanceDraftPublic,
  type AiGovernanceDraftReviewPublic,
  type AiGovernanceDraftReviewRequest,
  AiGovernanceDraftReviewsService,
} from "@/client"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"

const TEXTAREA_CLASS_NAME =
  "border-input placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 min-h-24 w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50"

type EditableFinding = {
  findingId: string
  rescanRecommendation: string
  pendingVerifications: string
  limitations: string
}

function inlineReviewDetail(
  draft: AiGovernanceDraftPublic,
): AiGovernanceDraftReviewPublic | null {
  const candidate = draft as AiGovernanceDraftPublic &
    Partial<AiGovernanceDraftReviewPublic>
  if (
    !("model_output" in candidate) &&
    !("review_decision" in candidate) &&
    !("operator_edited_output" in candidate)
  ) {
    return null
  }
  return candidate as AiGovernanceDraftReviewPublic
}

function lines(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

function editableProjection(output: AiDraftModelOutput): EditableFinding[] {
  return output.recommendations.map((recommendation) => ({
    findingId: recommendation.finding_id,
    rescanRecommendation: recommendation.rescan_recommendation,
    pendingVerifications: (recommendation.pending_verifications ?? []).join(
      "\n",
    ),
    limitations: (recommendation.limitations ?? []).join("\n"),
  }))
}

function reviewRequest(
  decision: "ACCEPTED" | "EDITED" | "REJECTED",
  edits: EditableFinding[],
): AiGovernanceDraftReviewRequest {
  if (decision !== "EDITED") return { decision }
  const editedOutput: AiDraftEditedOutput = {
    findings: edits.map((finding) => ({
      finding_id: finding.findingId,
      rescan_recommendation: finding.rescanRecommendation.trim(),
      pending_verifications: lines(finding.pendingVerifications),
      limitations: lines(finding.limitations),
    })),
  }
  return { decision, edited_output: editedOutput }
}

function TextList({
  title,
  values,
}: {
  title: string
  values: string[] | undefined
}) {
  if (!values || values.length === 0) return null
  return (
    <div className="space-y-1">
      <h5 className="text-sm font-medium">{title}</h5>
      <ul className="list-disc space-y-1 pl-5 text-sm">
        {values.map((value, index) => (
          <li key={`${title}-${index}-${value}`}>{value}</li>
        ))}
      </ul>
    </div>
  )
}

function ImmutableModelOutput({ output }: { output: AiDraftModelOutput }) {
  return (
    <div className="space-y-4">
      <div className="rounded-md border bg-muted/20 p-3">
        <p className="text-sm font-medium">Model-authored summary</p>
        <p className="mt-1 text-sm">{output.summary}</p>
        <p className="mt-2 break-all font-mono text-xs text-muted-foreground">
          Report SHA-256 {output.report_sha256}
        </p>
      </div>
      {output.recommendations.map((recommendation) => (
        <article
          className="space-y-3 rounded-md border p-3"
          key={recommendation.finding_id}
        >
          <div className="space-y-1">
            <h4 className="font-semibold">Immutable recommendation</h4>
            <p className="break-all font-mono text-xs">
              Finding {recommendation.finding_id}
            </p>
          </div>
          <div>
            <h5 className="text-sm font-medium">Rescan recommendation</h5>
            <p className="text-sm">{recommendation.rescan_recommendation}</p>
          </div>
          <TextList
            title="Pending verifications"
            values={recommendation.pending_verifications}
          />
          <TextList title="Limitations" values={recommendation.limitations} />
          <div className="space-y-2">
            <h5 className="text-sm font-medium">Evidence-bound claims</h5>
            {recommendation.claims.map((claim) => (
              <div className="rounded border p-2 text-sm" key={claim.claim_id}>
                <p className="break-all font-mono text-xs">
                  Claim {claim.claim_id}
                </p>
                <ul className="mt-1 list-disc space-y-1 pl-5">
                  {claim.evidence_ids.map((evidenceId) => (
                    <li className="break-all font-mono text-xs" key={evidenceId}>
                      Evidence {evidenceId}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </article>
      ))}
    </div>
  )
}

function EditorialForm({
  edits,
  disabled,
  onCancel,
  onChange,
  onSubmit,
}: {
  edits: EditableFinding[]
  disabled: boolean
  onCancel: () => void
  onChange: (index: number, field: keyof EditableFinding, value: string) => void
  onSubmit: () => void
}) {
  const valid = edits.every(
    (finding) => finding.rescanRecommendation.trim().length > 0,
  )
  return (
    <div className="space-y-4 rounded-md border p-3">
      <div>
        <h4 className="font-semibold">Editorial-only changes</h4>
        <p className="text-sm text-muted-foreground">
          Finding identities, report hash, claims, and Evidence citations remain
          immutable. Reject the draft when a factual correction is required.
        </p>
      </div>
      {edits.map((finding, index) => (
        <fieldset
          className="space-y-3 rounded-md border p-3"
          disabled={disabled}
          key={finding.findingId}
        >
          <legend className="px-1 text-sm font-medium">
            Finding {finding.findingId}
          </legend>
          <div className="space-y-1">
            <Label htmlFor={`draft-recommendation-${finding.findingId}`}>
              Rescan recommendation
            </Label>
            <textarea
              aria-label={`Recommendation for ${finding.findingId}`}
              className={TEXTAREA_CLASS_NAME}
              id={`draft-recommendation-${finding.findingId}`}
              onChange={(event) =>
                onChange(index, "rescanRecommendation", event.target.value)
              }
              required
              value={finding.rescanRecommendation}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor={`draft-pending-${finding.findingId}`}>
              Pending verifications, one per line
            </Label>
            <textarea
              aria-label={`Pending verifications for ${finding.findingId}`}
              className={TEXTAREA_CLASS_NAME}
              id={`draft-pending-${finding.findingId}`}
              onChange={(event) =>
                onChange(index, "pendingVerifications", event.target.value)
              }
              value={finding.pendingVerifications}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor={`draft-limitations-${finding.findingId}`}>
              Limitations, one per line
            </Label>
            <textarea
              aria-label={`Limitations for ${finding.findingId}`}
              className={TEXTAREA_CLASS_NAME}
              id={`draft-limitations-${finding.findingId}`}
              onChange={(event) =>
                onChange(index, "limitations", event.target.value)
              }
              value={finding.limitations}
            />
          </div>
        </fieldset>
      ))}
      <div className="flex flex-wrap gap-2">
        <Button disabled={disabled || !valid} onClick={onSubmit} type="button">
          {disabled ? "Submitting review…" : "Submit edited draft"}
        </Button>
        <Button
          disabled={disabled}
          onClick={onCancel}
          type="button"
          variant="outline"
        >
          Cancel editing
        </Button>
      </div>
    </div>
  )
}

export default function AiGovernanceDraftReview({
  draft,
  projectId,
  reportId,
}: {
  draft: AiGovernanceDraftPublic
  projectId: string
  reportId: string
}) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [edits, setEdits] = useState<EditableFinding[]>([])
  const inlineDetail = inlineReviewDetail(draft)
  const queryKey = ["ai-governance-draft-review", projectId, reportId, draft.id]
  const detailQuery = useQuery({
    queryKey,
    queryFn: () =>
      AiGovernanceDraftReviewsService.readAiGovernanceDraft({
        projectId,
        reportId,
        draftId: draft.id,
      }),
    enabled: draft.status === "REVIEWABLE" && inlineDetail === null,
    staleTime: Number.POSITIVE_INFINITY,
  })
  const mutation = useMutation({
    mutationFn: (requestBody: AiGovernanceDraftReviewRequest) =>
      AiGovernanceDraftReviewsService.reviewAiGovernanceDraft({
        projectId,
        reportId,
        draftId: draft.id,
        requestBody,
      }),
    onSuccess: async (reviewed) => {
      queryClient.setQueryData(queryKey, reviewed)
      setEditing(false)
      await queryClient.invalidateQueries({
        queryKey: ["governance-report", projectId, reportId],
      })
    },
  })
  const detail = mutation.data ?? inlineDetail ?? detailQuery.data

  if (draft.status !== "REVIEWABLE") return null
  if (!detail && detailQuery.isPending) {
    return <p role="status">Loading AI draft recommendations…</p>
  }
  if (!detail || detailQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>AI draft could not be loaded</AlertTitle>
        <AlertDescription>
          The deterministic report remains available. No review was recorded.
        </AlertDescription>
      </Alert>
    )
  }
  if (!detail.model_output) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Reviewable draft is incomplete</AlertTitle>
        <AlertDescription>
          Model output is unavailable, so the terminal review is disabled.
        </AlertDescription>
      </Alert>
    )
  }

  const beginEditing = () => {
    setEdits(editableProjection(detail.model_output as AiDraftModelOutput))
    setEditing(true)
    mutation.reset()
  }
  const updateEdit = (
    index: number,
    field: keyof EditableFinding,
    value: string,
  ) => {
    if (field === "findingId") return
    setEdits((current) =>
      current.map((finding, findingIndex) =>
        findingIndex === index ? { ...finding, [field]: value } : finding,
      ),
    )
  }
  const submit = (
    decision: "ACCEPTED" | "EDITED" | "REJECTED",
    currentEdits: EditableFinding[] = [],
  ) => {
    if (mutation.isPending || detail.review_decision) return
    mutation.mutate(reviewRequest(decision, currentEdits))
  }

  return (
    <div className="space-y-4 rounded-md border p-3" aria-label="AI draft review">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-semibold">Operator review</h3>
          <p className="text-sm text-muted-foreground">
            This model output is non-authoritative until one terminal review is
            recorded.
          </p>
        </div>
        {detail.review_decision && (
          <Badge>Review {detail.review_decision}</Badge>
        )}
      </div>

      <ImmutableModelOutput output={detail.model_output} />

      {detail.review_decision ? (
        <div className="rounded-md border p-3 text-sm">
          <p className="font-medium">Review {detail.review_decision}</p>
          {detail.reviewed_at && <p>Recorded {detail.reviewed_at}</p>}
          {detail.operator_edited_output && (
            <p className="text-muted-foreground">
              The separate Operator editorial projection is stored with the
              unchanged model output.
            </p>
          )}
        </div>
      ) : editing ? (
        <EditorialForm
          disabled={mutation.isPending}
          edits={edits}
          onCancel={() => setEditing(false)}
          onChange={updateEdit}
          onSubmit={() => submit("EDITED", edits)}
        />
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={mutation.isPending}
            onClick={() => submit("ACCEPTED")}
            type="button"
          >
            {mutation.isPending ? "Submitting review…" : "Accept draft"}
          </Button>
          <Button
            disabled={mutation.isPending}
            onClick={beginEditing}
            type="button"
            variant="outline"
          >
            Edit and accept draft
          </Button>
          <Button
            disabled={mutation.isPending}
            onClick={() => submit("REJECTED")}
            type="button"
            variant="destructive"
          >
            Reject draft
          </Button>
        </div>
      )}

      {mutation.isError && (
        <Alert variant="destructive">
          <AlertTitle>Review was not recorded</AlertTitle>
          <AlertDescription>
            Reload the immutable draft state before attempting another terminal
            decision.
          </AlertDescription>
        </Alert>
      )}
    </div>
  )
}
