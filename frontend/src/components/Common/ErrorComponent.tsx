import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { useLocale } from "@/components/LocaleProvider"

const ErrorComponent = () => {
  const { text } = useLocale()
  return (
    <div
      className="flex min-h-screen items-center justify-center flex-col p-4"
      data-testid="error-component"
    >
      <div className="flex items-center z-10">
        <div className="flex flex-col ml-4 items-center justify-center p-4">
          <span className="text-6xl md:text-8xl font-bold leading-none mb-4">
            {text("出错了", "Error")}
          </span>
          <span className="text-2xl font-bold mb-2">{text("抱歉！", "Oops!")}</span>
        </div>
      </div>

      <p className="text-lg text-muted-foreground mb-4 text-center z-10">
        {text("发生错误，请重试。", "Something went wrong. Please try again.")}
      </p>
      <Link to="/">
        <Button>{text("返回首页", "Go Home")}</Button>
      </Link>
    </div>
  )
}

export default ErrorComponent
