import { expect, type Page } from "@playwright/test"
import { LoginService, OpenAPI, UsersService } from "../../src/client"
import { firstSuperuser, firstSuperuserPassword } from "../config"

export async function createUser({
  email,
  password,
}: {
  email: string
  password: string
}) {
  OpenAPI.BASE = `${process.env.VITE_API_URL}`
  const token = await LoginService.loginAccessToken({
    formData: {
      username: firstSuperuser,
      password: firstSuperuserPassword,
    },
  })
  OpenAPI.TOKEN = token.access_token

  return await UsersService.createUser({
    requestBody: {
      email,
      password,
      full_name: "Test User",
    },
  })
}

export async function logInUser(page: Page, email: string, password: string) {
  await page.goto("/login")

  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "Log In" }).click()
  await page.waitForURL("/")
  await expect(
    page.getByText("Welcome back, nice to see you again!"),
  ).toBeVisible()
}

export async function logOutUser(page: Page) {
  await page.getByTestId("user-menu").click()
  await page.getByRole("menuitem", { name: "Log out" }).click()
  await page.goto("/login")
}
