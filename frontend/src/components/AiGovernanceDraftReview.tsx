import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import {
  type AiGovernanceDraftDetailPublic,
  type AiGovernanceDraftReviewRequest,
  AiGovernanceDraftReviewsService,
  ApiError,
  type GovernanceReportDetailPublic,
} from "@/client"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

type Recommendation = {
  findingId: string
  recommendation: string
  pendingVerifications: string[]
  limitations: string[]
  evidenceIds: string[]
}

type EditorialFinding = {
  findingId: string
  recommendation: string
  pendingVerifications: string
  limitations: string
}

function object(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null
}

function textList(value: unknown): string[] {
  return Array.isArray(value) ? value.flatMap((item) => text(item) ?? []) : []
}

function recommendations(modelOutput: unknown): Recommendation[] | null {
  const output = object(modelOutput)
  if (!output || !Array.isArray(output.recommendations)) return null
  const parsed = output.recommendations.flatMap((item) => {
    const value = object(item)
    const findingId = value ? text(value.finding_id) : null
    const recommendation = value ? text(value.rescan_recommendation) : null
    if (!value || !findingId || !recommendation) return []
    const evidenceIds = Array.isArray(value.claims)
      ? value.claims.flatMap((claim) => {
          const claimObject = object(claim)
          return claimObject ? textList(claimObject.evidence_ids) : []
        })
      : []
    return [
      {
        findingId,
        recommendation,
        pendingVerifications: textList(value.pending_verifications),
        limitations: textList(value.limitations),
        evidenceIds: [...new Set(evidenceIds)],
      },
    ]
  })
  return parsed.length === output.recommendations.length && parsed.length > 0
    ? parsed
    : null
}

function TextItems({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <div className="space-y-1">
      <h4 className="font-medium">{title}</h4>
      <ul className="list-disc space-y-1 pl-5">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

export function AiGovernanceDraftReview({
  draft,
  projectId,
  reportId,
  canReview,
}: {
  draft: AiGovernanceDraftDetailPublic
  projectId: string
  reportId: string
  canReview: boolean
}) {
  const queryClient = useQueryClient()
  const entries = recommendations(draft.model_output)
  const [editing, setEditing] = useState(false)
  const [editorialFindings, setEditorialFindings] = useState<
    EditorialFinding[]
  >([])
  const reviewMutation = useMutation({
    mutationFn: (requestBody: AiGovernanceDraftReviewRequest) =>
      AiGovernanceDraftReviewsService.reviewAiGovernanceDraft({
        projectId,
        reportId,
        draftId: draft.id,
        requestBody,
      }),
    onSuccess: (reviewed) => {
      setEditing(false)
      queryClient.setQueryData<GovernanceReportDetailPublic>(
        ["governance-report", projectId, reportId],
        (current) =>
          current
            ? {
                ...current,
                ai_governance_drafts: current.ai_governance_drafts?.map(
                  (item) => (item.id === reviewed.id ? reviewed : item),
                ),
              }
            : current,
      )
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status === 409) {
        await queryClient.invalidateQueries({
          queryKey: ["governance-report", projectId, reportId],
        })
      }
    },
  })

  if (!entries) {
    return (
      <Alert variant="destructive">
        <AlertTitle>AI draft content is not readable</AlertTitle>
        <AlertDescription>
          The persisted draft did not match the bounded review contract.
        </AlertDescription>
      </Alert>
    )
  }

  const beginEditing = () => {
    setEditorialFindings(
      entries.map((entry) => ({
        findingId: entry.findingId,
        recommendation: entry.recommendation,
        pendingVerifications: entry.pendingVerifications.join("\n"),
        limitations: entry.limitations.join("\n"),
      })),
    )
    setEditing(true)
  }
  const updateEditorialFinding = (
    index: number,
    field: keyof Omit<EditorialFinding, "findingId">,
    value: string,
  ) => {
    setEditorialFindings((current) =>
      current.map((entry, entryIndex) =>
        entryIndex === index ? { ...entry, [field]: value } : entry,
      ),
    )
  }
  const submitEditedReview = () => {
    if (
      reviewMutation.isPending ||
      editorialFindings.some((entry) => !entry.recommendation.trim())
    )
      return
    const lines = (value: string) =>
      value
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean)
    reviewMutation.mutate({
      decision: "EDITED",
      edited_output: {
        findings: editorialFindings.map((entry) => ({
          finding_id: entry.findingId,
          rescan_recommendation: entry.recommendation.trim(),
          pending_verifications: lines(entry.pendingVerifications),
          limitations: lines(entry.limitations),
        })),
      },
    })
  }

  return (
    <div className="space-y-4 rounded-md border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold">Immutable draft recommendations</h3>
        <Badge>{draft.status}</Badge>
      </div>
      <div className="space-y-3">
        {entries.map((entry) => (
          <article
            className="space-y-2 rounded-md border p-3"
            data-testid="ai-draft-recommendation"
            key={entry.findingId}
          >
            <p>
              <span className="font-medium">Finding </span>
              <span className="break-all font-mono text-xs">
                {entry.findingId}
              </span>
            </p>
            <p>{entry.recommendation}</p>
            <TextItems
              title="Pending confirmations"
              items={entry.pendingVerifications}
            />
            <TextItems title="Limitations" items={entry.limitations} />
            <div className="space-y-1">
              <h4 className="font-medium">Evidence citations</h4>
              <ul className="list-disc space-y-1 pl-5">
                {entry.evidenceIds.map((evidenceId, index) => (
                  <li key={evidenceId}>
                    <a
                      aria-label={`Evidence citation ${evidenceId}`}
                      className="underline"
                      href="#report-evidence"
                      title={evidenceId}
                    >
                      Evidence citation {index + 1}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </article>
        ))}
      </div>
      {draft.review_decision ? (
        <p role="status">
          Review <Badge>{draft.review_decision}</Badge>
        </p>
      ) : canReview && editing ? (
        <div className="space-y-4">
          {editorialFindings.map((entry, index) => (
            <div
              className="space-y-3 rounded-md border p-3"
              key={entry.findingId}
            >
              <p className="break-all font-mono text-xs">
                Finding {entry.findingId}
              </p>
              <label className="block space-y-1">
                <span className="font-medium">
                  Recommendation for Finding {entry.findingId}
                </span>
                <textarea
                  aria-label={`Recommendation for Finding ${entry.findingId}`}
                  className="min-h-20 w-full rounded-md border bg-background p-2"
                  disabled={reviewMutation.isPending}
                  onChange={(event) =>
                    updateEditorialFinding(
                      index,
                      "recommendation",
                      event.target.value,
                    )
                  }
                  value={entry.recommendation}
                />
              </label>
              <label className="block space-y-1">
                <span className="font-medium">
                  Pending confirmations for Finding {entry.findingId}
                </span>
                <textarea
                  aria-label={`Pending confirmations for Finding ${entry.findingId}`}
                  className="min-h-20 w-full rounded-md border bg-background p-2"
                  disabled={reviewMutation.isPending}
                  onChange={(event) =>
                    updateEditorialFinding(
                      index,
                      "pendingVerifications",
                      event.target.value,
                    )
                  }
                  value={entry.pendingVerifications}
                />
              </label>
              <label className="block space-y-1">
                <span className="font-medium">
                  Limitations for Finding {entry.findingId}
                </span>
                <textarea
                  aria-label={`Limitations for Finding ${entry.findingId}`}
                  className="min-h-20 w-full rounded-md border bg-background p-2"
                  disabled={reviewMutation.isPending}
                  onChange={(event) =>
                    updateEditorialFinding(
                      index,
                      "limitations",
                      event.target.value,
                    )
                  }
                  value={entry.limitations}
                />
              </label>
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={
                reviewMutation.isPending ||
                editorialFindings.some((entry) => !entry.recommendation.trim())
              }
              onClick={submitEditedReview}
              type="button"
            >
              Submit edited review
            </Button>
            <Button
              disabled={reviewMutation.isPending}
              onClick={() => setEditing(false)}
              type="button"
              variant="outline"
            >
              Cancel edit
            </Button>
          </div>
        </div>
      ) : canReview ? (
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={reviewMutation.isPending}
            onClick={() => reviewMutation.mutate({ decision: "ACCEPTED" })}
            type="button"
          >
            Accept draft
          </Button>
          <Button
            disabled={reviewMutation.isPending}
            onClick={beginEditing}
            type="button"
            variant="outline"
          >
            Edit and accept draft
          </Button>
          <Button
            disabled={reviewMutation.isPending}
            onClick={() => reviewMutation.mutate({ decision: "REJECTED" })}
            type="button"
            variant="destructive"
          >
            Reject draft
          </Button>
        </div>
      ) : (
        <p className="text-muted-foreground">
          A Project Operator can complete the terminal review.
        </p>
      )}
      {reviewMutation.isError && (
        <Alert variant="destructive">
          <AlertTitle>Draft review could not be completed</AlertTitle>
          <AlertDescription>
            The persisted server state was refreshed when available.
          </AlertDescription>
        </Alert>
      )}
    </div>
  )
}
