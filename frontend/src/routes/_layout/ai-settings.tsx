import { createFileRoute } from "@tanstack/react-router"
import ModelConnectionSettings from "@/components/ModelConnectionSettings"

export const Route = createFileRoute("/_layout/ai-settings")({
  component: ModelConnectionSettings,
})
