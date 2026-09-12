import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  type Body_login_login_access_token as AccessToken,
  ApiError,
  LoginService,
  type UserPublic,
  UsersService,
} from "@/client"
import { handleError } from "@/utils"
import useCustomToast from "./useCustomToast"

const isLoggedIn = () => {
  return localStorage.getItem("access_token") !== null
}

export const isInactiveAccountError = (error: unknown) =>
  error instanceof ApiError &&
  error.status === 400 &&
  typeof error.body === "object" &&
  error.body !== null &&
  "detail" in error.body &&
  error.body.detail === "Inactive user"

const useAuth = () => {
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()

  const {
    data: user,
    error: userError,
    refetch: refetchUser,
  } = useQuery<UserPublic | null, Error>({
    queryKey: ["currentUser"],
    queryFn: UsersService.readUserMe,
    enabled: isLoggedIn(),
  })

  const login = async (data: AccessToken) => {
    const response = await LoginService.loginAccessToken({
      formData: data,
    })
    localStorage.setItem("access_token", response.access_token)
  }

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: () => {
      queryClient.clear()
      window.location.href = "/"
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
    },
  })

  const logout = () => {
    void queryClient.cancelQueries()
    queryClient.clear()
    localStorage.removeItem("access_token")
    window.location.href = "/login"
  }

  return {
    loginMutation,
    logout,
    user,
    userError,
    refetchUser,
  }
}

export { isLoggedIn }
export default useAuth
