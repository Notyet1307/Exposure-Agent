import { Link } from "@tanstack/react-router"
import type { AnalysisReportsService } from "@/client"
import { CustomerRecordFields } from "@/components/CustomerRecordFields"
import { RecordFields } from "@/components/ExternalAssets"
import { TechnicalValue } from "@/components/TechnicalValue"
import { comparisonUuid } from "@/lib/comparisonReturn"
import { useI18n } from "@/lib/i18n"

export type V2Report = Awaited<
  ReturnType<typeof AnalysisReportsService.readV2AnalysisReport>
>
export type V2Text = NonNullable<V2Report["text"]>
const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}

export function V2ReportContent({
  report,
  compact = false,
  print = false,
}: {
  report: V2Report
  compact?: boolean
  print?: boolean
}) {
  const { t, formatDate } = useI18n()
  const material = report.material
  if (!report.readable || !material) return null
  const text = report.text
  const pins = object(material.identity.pins)
  const customer = object(pins.CUSTOMER)
  const cloud = object(pins.CLOUD)
  const display = (value: unknown) =>
    value === null || value === undefined
      ? t("Not provided", "未提供")
      : typeof value === "object"
        ? JSON.stringify(value)
        : String(value)
  const date = (value: unknown) =>
    typeof value === "string" ? formatDate(value) : t("Not provided", "未提供")
  const counts = (value: Record<string, unknown>) => (
    <dl className="grid min-w-0 gap-3 sm:grid-cols-2">
      {[
        ["total_addresses", "All addresses", "全部地址"],
        ["both", "Recorded on both sides", "双方都有记录"],
        [
          "cloud_only",
          "CloudAtlas record, absent from this customer version",
          "云图有记录，客户本版未登记",
        ],
        [
          "customer_only",
          "Customer record, not observed in this CloudAtlas batch",
          "客户有记录，云图本批未观测",
        ],
      ].map(([key, en, zh]) => (
        <div key={key}>
          <dt className="text-sm text-muted-foreground">{t(en, zh)}</dt>
          <dd className="font-medium tabular-nums">{display(value[key])}</dd>
        </div>
      ))}
    </dl>
  )
  const classification = (value: unknown) =>
    value === "both"
      ? t("Recorded on both sides", "双方都有记录")
      : value === "cloud_only"
        ? t(
            "CloudAtlas record, absent from this customer version",
            "云图有记录，客户本版未登记",
          )
        : value === "customer_only"
          ? t(
              "Customer record, not observed in this CloudAtlas batch",
              "客户有记录，云图本批未观测",
            )
          : t(
              "Known records; coverage does not support full differences",
              "已知记录；覆盖不足以支持全范围差异",
            )
  const fact = (ref: string) => {
    const value = material.facts[ref]
    if (!value) return null
    const data = value.value
    if (value.kind === "counts") return <div key={ref}>{counts(data)}</div>
    if (value.kind === "address")
      return (
        <p key={ref}>
          {display(data.canonical_ip)} · {classification(data.classification)} ·{" "}
          {t("Customer records", "客户记录")} {display(data.customer_records)} ·{" "}
          {t("CloudAtlas records", "云图记录")} {display(data.cloud_records)}
        </p>
      )
    if (value.kind === "identity")
      return (
        <p key={ref}>
          {t("Generated", "生成时间")} {date(data.published_at)} ·{" "}
          {t("Customer applied", "客户资料生效")}{" "}
          {date(data.customer_applied_at)}
        </p>
      )
    if (value.kind === "source_record") {
      const item = material.items.find(
        (item) => item.citation_id === data.source_ref,
      )
      if (!item) return null
      const identity = object(item.identity)
      return (
        <section key={ref} className="space-y-2">
          <h4 className="font-medium">
            {identity.source === "CUSTOMER"
              ? t("Customer declaration", "客户声明")
              : t("CloudAtlas observation", "云图观测")}
          </h4>
          {identity.source === "CUSTOMER" ? (
            <CustomerRecordFields fields={object(item.data)} />
          ) : (
            <RecordFields
              record={{ fields: object(item.data) }}
              domain={String(identity.domain)}
            />
          )}
        </section>
      )
    }
    const binding = object(data.binding)
    return (
      <p key={ref}>
        {t("Fixed NetFlow observations", "固定 NetFlow 观测")} ·{" "}
        {t("Observation objects", "观测对象")}{" "}
        {display(binding.observation_count)} · {t("Source records", "源记录")}{" "}
        {display(binding.source_records)} · {t("Evidence cutoff", "辅证截止")}{" "}
        {date(binding.valid_until)}
      </p>
    )
  }
  const references = (refs: string[]) => (
    <div className="flex flex-wrap gap-2 text-sm">
      {refs.map((ref) => {
        const sample = material.samples.find(
          (sample) =>
            Array.isArray(sample.evidence_refs) &&
            sample.evidence_refs.includes(ref),
        )
        const key = sample?.address_key
        return typeof key === "string" && /^addr:[a-f0-9]{64}$/.test(key) ? (
          <Link
            key={ref}
            className="underline"
            to="/projects/$projectId/netflow-correlation"
            params={{ projectId: report.project_id }}
            search={{
              result: report.result_id,
              binding: report.supplement_binding_id ?? "none",
              core_address: key,
            }}
          >
            {t("Read fixed evidence", "查看固定依据")}{" "}
            {display(sample?.canonical_ip)}
          </Link>
        ) : (
          <details key={ref}>
            <summary className="cursor-pointer text-muted-foreground">
              {t("Source reference", "来源引用")}
            </summary>
            <TechnicalValue
              value={ref}
              label={t("Fixed reference", "固定引用")}
            />
          </details>
        )
      })}
    </div>
  )
  const claim = (id: string) => {
    const value = text?.claims.find((value) => value.id === id)
    if (!value) return null
    const labels: Record<string, [string, string]> = {
      explanation: ["Explanation to verify", "待核实解释"],
      hypothesis: ["Hypothesis", "可能解释"],
      gap: ["Missing evidence", "尚缺依据"],
      action: ["Suggested check", "建议核实"],
    }
    return (
      <div key={id} className="min-w-0 space-y-2">
        {value.type === "fact" ? (
          value.fact_refs.map(fact)
        ) : (
          <>
            <p className="text-sm font-medium">{t(...labels[value.type])}</p>
            <p className="max-w-prose whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
              {value.text}
            </p>
            {(value.fact_refs ?? []).map(fact)}
          </>
        )}
        {references(value.evidence_refs)}
      </div>
    )
  }
  const titles: Record<string, [string, string]> = {
    conclusion: ["This comparison's conclusion", "本轮核对结论"],
    differences: ["Main differences and their meaning", "主要差异及业务含义"],
    priority: ["Objects to verify first", "建议核实的重点对象"],
    netflow: ["NetFlow observations and limits", "NetFlow 佐证与限制"],
    next_steps: ["Suggested next steps", "下一步建议"],
    appendix: ["Data scope and evidence", "数据范围与证据附录"],
    known_facts: ["Known facts", "已知事实"],
    possible_explanations: ["Possible explanations", "可能解释"],
    missing_evidence: ["Missing evidence", "尚缺依据"],
    next_checks: ["Suggested checks", "建议核实"],
  }
  const addressFact = report.address_key
    ? `fact:${report.result_id}:${report.address_key}`
    : null
  return (
    <div className="min-w-0 space-y-6">
      <section className="space-y-3">
        <h3 className="font-semibold">
          {addressFact
            ? t("Fixed address facts", "固定地址事实")
            : t("Fixed comparison facts", "固定核对事实")}
        </h3>
        {counts(material.summary)}
        {addressFact && fact(addressFact)}
      </section>
      {text ? (
        compact ? (
          <div className="space-y-4">{text.summary.map(claim)}</div>
        ) : (
          text.sections.map((section) => (
            <section key={section.id} className="min-w-0 space-y-4">
              <h3 className="text-lg font-semibold">
                {t(...titles[section.id])}
              </h3>
              {section.claim_ids.map(claim)}
            </section>
          ))
        )
      ) : (
        <section className="space-y-3">
          <h3 className="font-semibold">
            {t("Fixed data report", "固定资料报告")}
          </h3>
          {counts(material.summary)}
          <p>
            {t(
              "AI interpretation is unavailable. These are the fixed deterministic facts.",
              "AI 解读未生成；这里显示固定的确定性事实。",
            )}
          </p>
        </section>
      )}
      {!!text?.priority_cases.length && (
        <section className="space-y-4">
          <h3 className="font-semibold">
            {t("Suggested verification order", "建议核实顺序")}
          </h3>
          <ol className="list-decimal space-y-4 pl-5">
            {text.priority_cases.map((value) => {
              const sample = material.samples.find(
                (sample) => sample.address_key === value.address_key,
              )
              return (
                <li key={value.address_key} className="min-w-0 space-y-2">
                  <p className="font-medium">{display(sample?.canonical_ip)}</p>
                  <p className="whitespace-pre-wrap break-words">
                    {value.why_review}
                  </p>
                  <p className="whitespace-pre-wrap break-words">
                    {value.next_check}
                  </p>
                  {references(value.evidence_refs)}
                </li>
              )
            })}
          </ol>
        </section>
      )}
      <section className="space-y-3">
        <h3 className="font-semibold">{t("Data limits", "资料限制")}</h3>
        <p>
          {t("Addresses sampled", "地址样本")}{" "}
          {display(material.coverage.sampled_addresses)} /{" "}
          {display(material.coverage.eligible_addresses)} ·{" "}
          {t("Addresses omitted", "未纳入样本的地址")}{" "}
          {display(material.coverage.omitted_addresses)} ·{" "}
          {t("Source-record projections omitted", "未纳入的来源记录投影")}{" "}
          {display(material.coverage.omitted_source_records)}
        </p>
        <ul className="list-disc space-y-2 pl-5">
          {(text?.limitations ?? material.limitations).map((value) => (
            <li
              key={value}
              className="max-w-prose whitespace-pre-wrap break-words"
            >
              {value}
            </li>
          ))}
        </ul>
        <p className="text-sm">
          {t(
            "All figures come from the fixed result. The model interprets bounded samples; it has not reviewed every source record.",
            "全部数字来自固定结果。模型仅解释有界样本，并未逐条审阅所有来源记录。",
          )}
        </p>
      </section>
      {!compact && (
        <section className="min-w-0 space-y-3">
          <h3 className="font-semibold">
            {t("Fixed source versions", "固定来源版本")}
          </h3>
          <p className="text-sm">
            {t("Customer upload", "客户上传版本")}{" "}
            <span className="break-all">{display(customer.upload_id)}</span> ·{" "}
            {t("Customer revision", "客户修订")}{" "}
            <span className="break-all">{display(customer.revision_id)}</span> ·{" "}
            {t("Profile version", "配置版本")}{" "}
            {display(customer.profile_version)}
          </p>
          {Object.entries(object(cloud.domains)).map(([domain, pin]) => {
            const value = object(pin)
            return (
              <p key={domain} className="text-sm">
                {domain.toUpperCase()} · {t("Fixed version", "固定版本")}{" "}
                <span className="break-all">{display(value.id)}</span> ·{" "}
                {t("Collected", "采集时间")} {date(value.fetched_at)}
              </p>
            )
          })}
          <p className="text-sm">
            {t("Evidence cutoff", "辅证截止")}{" "}
            {report.valid_until
              ? date(report.valid_until)
              : t("No supplement selected", "明确不使用辅证")}
          </p>
        </section>
      )}
      {print && (
        <section className="space-y-2 text-sm">
          <h3 className="font-semibold">
            {t("Printed report identity", "打印报告身份")}
          </h3>
          <p>
            {t("Result", "比对结果")} {report.result_id} ·{" "}
            {t("Report", "解读报告")} {report.id} · {t("Revision", "修订")}{" "}
            {report.revision}
          </p>
          <p>
            {t("Material contract", "材料合同")}{" "}
            {display(material.subject.material_contract_version)} ·{" "}
            {t("Template", "模板")} {display(material.subject.template_version)}
          </p>
          <p>
            {t("Material fingerprint", "材料指纹")} {report.material_sha256} ·{" "}
            {t("Model configuration fingerprint", "模型配置指纹")}{" "}
            {report.config_fingerprint}
          </p>
        </section>
      )}
      {!compact && (
        <details className="space-y-3 text-sm">
          <summary className="cursor-pointer">
            {t("Fixed identities and report version", "固定身份与报告版本")}
          </summary>
          <TechnicalValue
            value={report.result_id}
            label={t("Result", "比对结果")}
          />
          <TechnicalValue value={report.id} label={t("Report", "解读报告")} />
          <TechnicalValue
            value={report.material_sha256}
            label={t("Material fingerprint", "材料指纹")}
          />
          <p>
            {t("Revision", "修订")} {report.revision} ·{" "}
            {t("Created", "创建时间")} {date(report.created_at)} ·{" "}
            {t("Confirmed", "确认时间")} {date(report.confirmed_at)}
          </p>
          {report.connection_version_id &&
            comparisonUuid.test(report.connection_version_id) && (
              <TechnicalValue
                value={report.connection_version_id}
                label={t("Model connection version", "模型连接版本")}
              />
            )}
        </details>
      )}
    </div>
  )
}
