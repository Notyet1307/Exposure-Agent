import { createFileRoute, redirect } from "@tanstack/react-router"
import AssetViews from "@/components/AssetViews"
import { validateAssetSearch } from "@/lib/assetSearch"

export const Route = createFileRoute(
  "/_layout/projects/$projectId/external-assets",
)({
  validateSearch: validateAssetSearch,
  beforeLoad: ({ search, params, location }) => {
    if (!search.asset_error) {
      throw redirect({
        to: "/projects/$projectId/cloudatlas-ledger",
        params,
        search,
        hash: location.hash,
        replace: true,
      })
    }
  },
  component: ConflictingAssetLink,
})

function ConflictingAssetLink() {
  return (
    <AssetViews
      projectId={Route.useParams().projectId}
      search={Route.useSearch()}
    />
  )
}
