import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { type UserCreateByAdmin, UsersService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
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
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"
import { useLocale } from "@/components/LocaleProvider"

function formSchema(zh: boolean) { return z
  .object({
    email: z.email({ message: zh ? "请输入有效邮箱地址" : "Invalid email address" }),
    full_name: z.string().optional(),
    password: z
      .string()
      .min(1, { message: zh ? "请输入密码" : "Password is required" })
      .min(8, { message: zh ? "密码至少需要 8 个字符" : "Password must be at least 8 characters" }),
    confirm_password: z
      .string()
      .min(1, { message: zh ? "请确认密码" : "Please confirm your password" }),
  })
  .refine((data) => data.password === data.confirm_password, {
    message: zh ? "两次输入的密码不一致" : "The passwords don't match",
    path: ["confirm_password"],
  }) }

type FormData = z.infer<ReturnType<typeof formSchema>>

const AddUser = () => {
  const [isOpen, setIsOpen] = useState(false)
  const { locale, text } = useLocale()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema(locale === "zh")),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      email: "",
      full_name: "",
      password: "",
      confirm_password: "",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: UserCreateByAdmin) =>
      UsersService.createUser({ requestBody: data }),
    onSuccess: () => {
      showSuccessToast(text("用户创建成功", "User created successfully"))
      form.reset()
      setIsOpen(false)
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
    },
  })

  const onSubmit = (data: FormData) => {
    const { confirm_password: _, ...userCreate } = data
    mutation.mutate(userCreate)
  }

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button className="my-4">
          <Plus className="mr-2" />
          {text("添加用户", "Add User")}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{text("添加用户", "Add User")}</DialogTitle>
          <DialogDescription>
            {text("填写以下信息以添加系统用户。", "Fill in the form below to add a new user to the system.")}
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form noValidate onSubmit={form.handleSubmit(onSubmit)}>
            <div className="grid gap-4 py-4">
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      {text("邮箱", "Email")} <span className="text-destructive">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder={text("邮箱", "Email")}
                        type="email"
                        {...field}
                        required
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="full_name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{text("姓名", "Full Name")}</FormLabel>
                    <FormControl>
                      <Input placeholder={text("姓名", "Full name")} type="text" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      {text("设置密码", "Set Password")} <span className="text-destructive">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder={text("密码", "Password")}
                        type="password"
                        {...field}
                        required
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="confirm_password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      {text("确认密码", "Confirm Password")}{" "}
                      <span className="text-destructive">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder={text("密码", "Password")}
                        type="password"
                        {...field}
                        required
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline" aria-label={text("取消添加用户", "Cancel adding user")} disabled={mutation.isPending}>
                  {text("取消", "Cancel")}
                </Button>
              </DialogClose>
              <LoadingButton type="submit" loading={mutation.isPending}>
                {text("保存", "Save")}
              </LoadingButton>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

export default AddUser
