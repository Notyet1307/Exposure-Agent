import {
  Link,
  useParams,
  useRouterState,
  useSearch,
} from "@tanstack/react-router"

import { useI18n } from "@/lib/i18n"
import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const { t } = useI18n()
  const params = useParams({ strict: false })
  const search = useSearch({ strict: false })
  const project = params.projectId ?? search.project
  const comparisonPage = useRouterState({
    select: (state) => state.location.pathname.endsWith("/netflow-correlation"),
  })
  const fullLogo = (
    <span
      className={cn(
        "inline-flex items-center font-semibold tracking-tight",
        className,
      )}
    >
      Exposure-Agent
    </span>
  )
  const iconLogo = (
    <span
      className={cn(
        "bg-primary text-primary-foreground inline-flex size-6 items-center justify-center rounded-md text-[10px] font-bold",
        className,
      )}
    >
      EA
    </span>
  )
  const content =
    variant === "responsive" ? (
      <>
        <span className="group-data-[collapsible=icon]:hidden">{fullLogo}</span>
        <span className="hidden group-data-[collapsible=icon]:block">
          {iconLogo}
        </span>
      </>
    ) : variant === "full" ? (
      fullLogo
    ) : (
      iconLogo
    )

  if (!asLink) {
    return content
  }

  if (project) {
    return (
      <Link
        to="/projects/$projectId/netflow-correlation"
        params={{ projectId: project }}
        search={comparisonPage && !search.legacy ? true : {}}
        aria-label={t("Exposure-Agent home", "Exposure-Agent 首页")}
      >
        {content}
      </Link>
    )
  }

  return (
    <Link
      to="/"
      search={{}}
      aria-label={t("Exposure-Agent home", "Exposure-Agent 首页")}
    >
      {content}
    </Link>
  )
}
