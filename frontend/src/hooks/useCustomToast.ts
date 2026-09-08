import { createElement } from "react"
import { toast } from "sonner"
import { LocalizedMessage } from "@/lib/i18n"

const useCustomToast = () => {
  const showSuccessToast = (description: string) => {
    toast.success(createElement(LocalizedMessage, { text: "Success!" }), {
      description: createElement(LocalizedMessage, { text: description }),
    })
  }

  const showErrorToast = (description: string) => {
    toast.error(
      createElement(LocalizedMessage, { text: "Something went wrong!" }),
      {
        description: createElement(LocalizedMessage, { text: description }),
      },
    )
  }

  return { showSuccessToast, showErrorToast }
}

export default useCustomToast
