import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { useLocale } from "@/components/LocaleProvider"

const NotFound = () => {
  const { text } = useLocale()
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
          <span className="text-2xl font-bold mb-2">{text("抱歉！", "Oops!")}</span>
        </div>
      </div>

      <p className="text-lg text-muted-foreground mb-4 text-center z-10">
        {text("未找到你访问的页面。", "The page you are looking for was not found.")}
      </p>
      <div className="z-10">
        <Link to="/">
          <Button className="mt-4">{text("返回", "Go Back")}</Button>
        </Link>
      </div>
    </div>
  )
}

export default NotFound
