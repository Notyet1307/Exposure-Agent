import { zodResolver } from "@hookform/resolvers/zod"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { useEffect } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import type { Body_login_login_access_token as AccessToken } from "@/client"
import { AuthLayout } from "@/components/Common/AuthLayout"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { PasswordInput } from "@/components/ui/password-input"
import useAuth, { isLoggedIn } from "@/hooks/useAuth"
import { useLocale } from "@/components/LocaleProvider"

function formSchema(zh: boolean) { return z.object({
  username: z.email({ message: zh ? "请输入有效邮箱地址" : "Invalid email address" }),
  password: z
    .string()
    .min(1, { message: zh ? "请输入密码" : "Password is required" })
    .min(8, { message: zh ? "密码至少需要 8 个字符" : "Password must be at least 8 characters" }),
}) satisfies z.ZodType<AccessToken> }

type FormData = z.infer<ReturnType<typeof formSchema>>

export const Route = createFileRoute("/login")({
  component: Login,
  beforeLoad: async () => {
    if (isLoggedIn()) {
      throw redirect({
        to: "/",
      })
    }
  },
  head: () => ({
    meta: [
      {
        title: "Log In - Exposure-Agent",
      },
    ],
  }),
})

function Login() {
  const { loginMutation } = useAuth()
  const { locale, text } = useLocale()
  useEffect(() => { document.title = text("登录 · Exposure-Agent", "Log In - Exposure-Agent") }, [text])
  const form = useForm<FormData>({
    resolver: zodResolver(formSchema(locale === "zh")),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      username: "",
      password: "",
    },
  })

  const onSubmit = (data: FormData) => {
    if (loginMutation.isPending) return
    loginMutation.mutate(data)
  }

  return (
    <AuthLayout>
      <Form {...form}>
        <form
          noValidate
          onSubmit={form.handleSubmit(onSubmit)}
          className="flex flex-col gap-6"
        >
          <div className="flex flex-col items-center gap-2 text-center">
            <h1 className="text-2xl font-bold">{text("登录账号", "Login to your account")}</h1>
          </div>

          <div className="grid gap-4">
            <FormField
              control={form.control}
              name="username"
              render={({ field }) => (
                <FormItem>
              <FormLabel>{text("邮箱", "Email")}</FormLabel>
                  <FormControl>
                    <Input
                      data-testid="email-input"
                      placeholder="user@example.com"
                      type="email"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage className="text-xs" />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{text("密码", "Password")}</FormLabel>
                  <FormControl>
                    <PasswordInput
                      data-testid="password-input"
                  placeholder={text("密码", "Password")}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage className="text-xs" />
                </FormItem>
              )}
            />

            <LoadingButton type="submit" loading={loginMutation.isPending}>
              {text("登录", "Log In")}
            </LoadingButton>
          </div>
        </form>
      </Form>
    </AuthLayout>
  )
}
