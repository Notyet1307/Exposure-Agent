import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react"
import { businessLabels } from "./business-labels"

export type Language = "zh-CN" | "en"
const STORAGE_KEY = "exposure:language"

interface LanguageContextValue {
  language: Language
  setLanguage: (language: Language) => void
  t: (english: string, chinese: string) => string
  message: (value: string) => string
  translateValue: (value: string) => string
  formatDate: (value: string, timeZone?: "UTC") => string
}

// Null-prototype records keep unknown server diagnostics (including "__proto__") verbatim.
const messages: Record<string, string> = Object.setPrototypeOf(
  {
    "Invalid email address": "请输入有效的电子邮箱地址",
    "Password is required": "请输入密码",
    "Password must be at least 8 characters": "密码至少需要 8 个字符",
    "Please confirm your password": "请确认密码",
    "Password confirmation is required": "请确认密码",
    "The passwords don't match": "两次输入的密码不一致",
    "Too big: expected string to have <=30 characters":
      "姓名不能超过 30 个字符",
    "Success!": "操作成功！",
    "Something went wrong!": "操作失败！",
    "Something went wrong.": "操作失败，请重试。",
    "User created successfully": "用户创建成功",
    "User updated successfully": "用户更新成功",
    "Password updated successfully": "密码更新成功",
    "Incorrect email or password": "邮箱或密码错误",
    "Inactive user": "用户已停用",
    "User not found": "用户不存在",
    "Not authenticated": "尚未登录",
    "Could not validate credentials": "无法验证登录凭据",
    "The user doesn't have enough privileges": "当前用户权限不足",
    "The user with this email already exists in the system.":
      "该邮箱对应的用户已存在。",
    "User with this email already exists": "该邮箱对应的用户已存在",
    "Incorrect password": "密码错误",
    "New password cannot be the same as the current one":
      "新密码不能与当前密码相同",
    "Network Error": "网络连接失败",
    "The user with this id does not exist in the system.":
      "该 ID 对应的用户不存在。",
    "The upload filename is invalid.": "上传文件名无效。",
    "The upload was incomplete.": "文件上传不完整。",
    "The upload exceeds the allowed size.": "上传文件超过允许的大小。",
    "The workbook exceeds safe resource limits.": "工作簿超过安全资源限制。",
    "Only XLSX workbooks are supported.": "仅支持 XLSX 工作簿。",
    "The workbook is malformed.": "工作簿格式损坏。",
    "The workbook contains an unsupported feature.": "工作簿包含不支持的功能。",
    "The workbook is missing required structure.": "工作簿缺少必需的结构。",
    "The workbook contains an invalid required value.":
      "工作簿中的必填值无效。",
    "The upload could not be stored.": "无法保存上传文件。",
    "CustomerUpload not found.": "客户上传文件不存在。",
    "The CustomerUpload is still referenced by the Project or Governance facts.":
      "项目或治理事实仍在引用该客户上传文件。",
    "The CustomerUpload could not be deleted.": "无法删除客户上传文件。",
    "The NetFlow filename is invalid.": "NetFlow 文件名无效。",
    "The NetFlow upload was incomplete.": "NetFlow 文件上传不完整。",
    "The NetFlow upload exceeds the allowed size.":
      "NetFlow 文件超过允许的大小。",
    "Only CSV or TXT NetFlow files are supported.":
      "NetFlow 仅支持 CSV 或 TXT 文件。",
    "The NetFlow file is empty or missing a header.":
      "NetFlow 文件为空或缺少表头。",
    "The NetFlow header is invalid.": "NetFlow 表头无效。",
    "The NetFlow header is missing required fields.":
      "NetFlow 表头缺少必需的字段。",
    "The NetFlow row structure is invalid.": "NetFlow 行结构无效。",
    "The NetFlow CSV is malformed.": "NetFlow CSV 格式损坏。",
    "The NetFlow encoding is unsupported.": "不支持该 NetFlow 文件编码。",
    "The NetFlow content is invalid.": "NetFlow 内容无效。",
    "The NetFlow content changed during acceptance.":
      "NetFlow 内容在接收期间发生了变化。",
    "The NetFlow dataset could not be stored.": "无法保存 NetFlow 数据集。",
    "The NetFlow dataset could not be processed.": "无法处理 NetFlow 数据集。",
    "The upload could not be accepted. Please try again.":
      "无法接受上传，请重试。",
    "Upload accepted successfully.": "上传已成功接受。",
    "Current Project input updated successfully.": "项目当前输入已更新。",
    "The current Project input could not be changed.": "无法更改项目当前输入。",
    "Choose one XLSX file to upload.": "请选择一个 XLSX 文件上传。",
    "NetFlowDataset upload accepted successfully.":
      "NetFlow 数据集上传已成功接受。",
    "The NetFlowDataset upload could not be accepted.":
      "无法接受 NetFlow 数据集上传。",
    "Current NetFlowDataset updated successfully.":
      "当前 NetFlow 数据集已更新。",
    "The current NetFlowDataset could not be changed.":
      "无法更改当前 NetFlow 数据集。",
    "Current NetFlowDataset cleared successfully.":
      "当前 NetFlow 数据集已清除。",
    "The current NetFlowDataset could not be cleared.":
      "无法清除当前 NetFlow 数据集。",
    "Choose one .csv or .txt file to upload.":
      "请选择一个 .csv 或 .txt 文件上传。",
  },
  null,
)

function initialLanguage(): Language {
  try {
    return localStorage.getItem(STORAGE_KEY) === "en" ? "en" : "zh-CN"
  } catch {
    return "zh-CN"
  }
}

const LanguageContext = createContext<LanguageContextValue | null>(null)

function createLanguageValue(
  language: Language,
  setLanguage: (language: Language) => void,
): LanguageContextValue {
  const locale = language === "en" ? "en-US" : "zh-CN"
  const dateOptions: Intl.DateTimeFormatOptions = {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "numeric",
    second: "numeric",
  }
  const dateFormatter = new Intl.DateTimeFormat(locale, dateOptions)
  const utcDateFormatter = new Intl.DateTimeFormat(locale, {
    ...dateOptions,
    timeZone: "UTC",
    timeZoneName: "short",
  })
  return {
    language,
    setLanguage,
    t: (english: string, chinese: string) =>
      language === "en" ? english : chinese,
    message: (value: string) =>
      language === "en" ? value : (messages[value] ?? value),
    translateValue: (value: string) => {
      const explanation = businessLabels[value]
      return language === "en" || explanation === undefined
        ? value
        : `${value}（${explanation}）`
    },
    formatDate: (value: string, timeZone?: "UTC") => {
      const date = new Date(value)
      return Number.isNaN(date.getTime())
        ? value
        : (timeZone === "UTC" ? utcDateFormatter : dateFormatter).format(date)
    },
  }
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(initialLanguage)
  useEffect(() => {
    document.documentElement.lang = language
    try {
      localStorage.setItem(STORAGE_KEY, language)
    } catch {
      // Storage may be disabled; switching still works for the current page.
    }
  }, [language])
  const value = useMemo(
    () => createLanguageValue(language, setLanguage),
    [language],
  )
  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  )
}

export function useI18n() {
  const value = useContext(LanguageContext)
  if (!value) throw new Error("useI18n requires LanguageProvider")
  return value
}

export function LocalizedMessage({ text }: { text: string }) {
  const { message } = useI18n()
  return <>{message(text)}</>
}

export function LanguageSwitcher() {
  const { language, setLanguage } = useI18n()
  return (
    <select
      aria-label="Language / 语言"
      className="h-8 rounded-md border bg-background px-2 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-ring"
      value={language}
      onChange={(event) =>
        setLanguage(event.target.value === "en" ? "en" : "zh-CN")
      }
    >
      <option value="zh-CN" lang="zh-CN">
        简体中文
      </option>
      <option value="en" lang="en">
        English
      </option>
    </select>
  )
}
