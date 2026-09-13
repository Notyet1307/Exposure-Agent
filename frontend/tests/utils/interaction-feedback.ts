import { writeFileSync } from "node:fs"
import { expect, type Locator } from "@playwright/test"

export async function feedback(button: Locator) {
  await expect(button).toBeEnabled()
  return button.evaluate(async (element) => {
    const tasks: number[] = []
    const observer = new PerformanceObserver((entries) => {
      tasks.push(...entries.getEntries().map((entry) => entry.duration))
    })
    observer.observe({ type: "longtask" })
    await new Promise(requestAnimationFrame)
    const start = performance.now()
    const href = location.href
    ;(element as HTMLButtonElement).click()
    const elapsed = await new Promise<number>((resolve) => {
      const frame = () => {
        if (
          (element as HTMLButtonElement).disabled ||
          location.href !== href ||
          performance.now() - start > 1000
        )
          resolve(performance.now() - start)
        else requestAnimationFrame(frame)
      }
      requestAnimationFrame(frame)
    })
    await new Promise((resolve) => setTimeout(resolve, 400))
    observer.disconnect()
    return { elapsed, tasks }
  })
}

export function recordFeedback(
  name: string,
  samples: Awaited<ReturnType<typeof feedback>>[],
) {
  writeFileSync(
    `/tmp/expux04-${name}-${process.env.EXPUX04_PHASE ?? "candidate"}.json`,
    JSON.stringify(samples),
  )
  expect(samples).toHaveLength(5)
  expect(
    samples.every(
      ({ elapsed, tasks }) => elapsed <= 100 && tasks.every((ms) => ms <= 200),
    ),
  ).toBe(true)
}
