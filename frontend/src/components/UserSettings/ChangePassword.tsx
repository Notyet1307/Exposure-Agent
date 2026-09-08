import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type UpdatePassword, UsersService } from "@/client"
import { useLocale } from "@/components/LocaleProvider"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { LoadingButton } from "@/components/ui/loading-button"
import { PasswordInput } from "@/components/ui/password-input"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

type Text = (zh: string, en: string) => string

const formSchema = (text: Text) =>
  z
    .object({
      current_password: z
        .string()
        .min(1, { message: text("请输入当前密码", "Password is required") })
        .min(8, {
          message: text(
            "密码至少需要 8 个字符",
            "Password must be at least 8 characters",
          ),
        }),
      new_password: z
        .string()
        .min(1, { message: text("请输入新密码", "Password is required") })
        .min(8, {
          message: text(
            "密码至少需要 8 个字符",
            "Password must be at least 8 characters",
          ),
        }),
      confirm_password: z
        .string()
        .min(1, {
          message: text("请确认新密码", "Password confirmation is required"),
        }),
    })
    .refine((data) => data.new_password === data.confirm_password, {
      message: text("两次输入的密码不一致", "The passwords don't match"),
      path: ["confirm_password"],
    })

type FormData = z.infer<ReturnType<typeof formSchema>>

const ChangePassword = () => {
  const { text } = useLocale()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const form = useForm<FormData>({
    resolver: zodResolver(formSchema(text)),
    mode: "onSubmit",
    criteriaMode: "all",
    defaultValues: {
      current_password: "",
      new_password: "",
      confirm_password: "",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: UpdatePassword) =>
      UsersService.updatePasswordMe({ requestBody: data }),
    onSuccess: () => {
      showSuccessToast(text("密码已更新。", "Password updated successfully"))
      form.reset()
    },
    onError: handleError.bind(showErrorToast),
  })

  const onSubmit = async (data: FormData) => {
    mutation.mutate(data)
  }

  return (
    <div className="max-w-md">
      <h3 className="text-lg font-semibold py-4">{text("修改密码", "Change Password")}</h3>
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          noValidate
          className="flex flex-col gap-4"
        >
          <FormField
            control={form.control}
            name="current_password"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>{text("当前密码", "Current Password")}</FormLabel>
                <FormControl>
                  <PasswordInput
                    data-testid="current-password-input"
                    placeholder="••••••••"
                    aria-invalid={fieldState.invalid}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="new_password"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>{text("新密码", "New Password")}</FormLabel>
                <FormControl>
                  <PasswordInput
                    data-testid="new-password-input"
                    placeholder="••••••••"
                    aria-invalid={fieldState.invalid}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="confirm_password"
            render={({ field, fieldState }) => (
              <FormItem>
                <FormLabel>{text("确认新密码", "Confirm Password")}</FormLabel>
                <FormControl>
                  <PasswordInput
                    data-testid="confirm-password-input"
                    placeholder="••••••••"
                    aria-invalid={fieldState.invalid}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <LoadingButton
            type="submit"
            loading={mutation.isPending}
            className="self-start"
          >
            {text("更新密码", "Update Password")}
          </LoadingButton>
        </form>
      </Form>
    </div>
  )
}

export default ChangePassword
