import { Link } from "@tanstack/react-router"

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

  return (
    <Link to="/" aria-label="Exposure-Agent home">
      {content}
    </Link>
  )
}
