import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { useI18n } from "@/lib/i18n"

const ErrorComponent = () => {
  const { t } = useI18n()
  return (
    <div
      className="flex min-h-screen items-center justify-center flex-col p-4"
      data-testid="error-component"
    >
      <div className="flex items-center z-10">
        <div className="flex flex-col ml-4 items-center justify-center p-4">
          <span className="text-6xl md:text-8xl font-bold leading-none mb-4">
            {t("Error", "错误")}
          </span>
          <span className="text-2xl font-bold mb-2">
            {t("Oops!", "出错了！")}
          </span>
        </div>
      </div>

      <p className="text-lg text-muted-foreground mb-4 text-center z-10">
        {t("Something went wrong. Please try again.", "发生错误，请重试。")}
      </p>
      <Link to="/">
        <Button>{t("Go Home", "返回首页")}</Button>
      </Link>
    </div>
  )
}

export default ErrorComponent
