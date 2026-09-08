import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

const NotFound = () => {
  const { t } = useI18n()
  return (
    <div
      className="flex min-h-screen items-center justify-center flex-col p-4"
      data-testid="not-found"
    >
      <div className="flex items-center z-10">
        <div className="flex flex-col ml-4 items-center justify-center p-4">
          <span className="text-6xl md:text-8xl font-bold leading-none mb-4">
            404
          </span>
          <span className="text-2xl font-bold mb-2">
            {t("Oops!", "出错了！")}
          </span>
        </div>
      </div>

      <p className="text-lg text-muted-foreground mb-4 text-center z-10">
        {t(
          "The page you are looking for was not found.",
          "未找到您要访问的页面。",
        )}
      </p>
      <div className="z-10">
        <Link to="/">
          <Button className="mt-4">{t("Go Back", "返回")}</Button>
        </Link>
      </div>
    </div>
  )
}

export default NotFound
