import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

// Explicitly loaded by the supervisor, never discovered from a project or user.
export default function (pi: ExtensionAPI) {
  const bridge = process.env.INVESTIGATION_BRIDGE!;
  const capability = process.env.INVESTIGATION_CAPABILITY!;
  const maxOutput = Number(process.env.INVESTIGATION_MAX_OUTPUT_BYTES);
  let outputBytes = 0;

  function contentBytes(content: Array<{ type: string; thinkingSignature?: string }>) {
    // Responses repeats reasoning in its opaque replay signature.
    return Buffer.byteLength(JSON.stringify(content.map(block =>
      block.type === "thinking" ? { ...block, thinkingSignature: undefined } : block,
    )), "utf8");
  }

  async function request(path: string, value: unknown, signal?: AbortSignal) {
    try {
      const response = await fetch(`${bridge}${path}`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${capability}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(value),
        redirect: "error",
        signal,
      });
      if (!response.ok) throw new Error("investigation_boundary_failed");
      return await response.text();
    } catch {
      // Print-mode ctx.shutdown() is a no-op in pinned Pi 0.82.1. Stop rather
      // than let a failed tool/session produce a plausible successful answer.
      process.exit(1);
    }
  }

  pi.on("message_update", async (event, ctx) => {
    if (event.message.role !== "assistant") return;
    const size = contentBytes(event.message.content);
    if (outputBytes + size > maxOutput) {
      await request("/output-limit", {}, ctx.signal);
    }
  });

  pi.on("message_end", async (event, ctx) => {
    if (event.message.role !== "assistant") return;
    // AgentSession drains this event before tool_call execution: authorize ALL
    // model tool names and uncoerced arguments before any material is read.
    await request("/assistant", event.message.content, ctx.signal);
    outputBytes += contentBytes(event.message.content);
  });

  const tools = process.env.INVESTIGATION_TASK === "analysis_report" ? [
    {
      name: "read_report_material",
      label: "Read authorized fixed report material",
      description: "Read the deterministic summary and bounded already-obtained evidence for the server-fixed report subject, with citation identities, times and explicit gaps. Required first. Exactly empty arguments; scope cannot change.",
    },
  ] : [
    {
      name: "read_asset_facts",
      label: "Read authorized asset facts",
      description: "Read bounded facts and citation identities for the one server-authorized asset and published base Run. Required first in every round. No arguments; scope cannot be changed.",
    },
    {
      name: "read_asset_history",
      label: "Read authorized asset history",
      description: "Read bounded published history for the same server-authorized project and asset. Historical snapshots retain their own source and time, not the base Run's time. No arguments; scope cannot be changed.",
    },
    {
      name: "read_cloudatlas_asset",
      label: "Read authorized CloudAtlas asset",
      description: "Query existing CloudAtlas read-only capability for this server-authorized asset. Returns bounded matching facts and query time, or an explicit gap/failed read without facts. No arguments; scope cannot be changed.",
    },
  ];
  for (const tool of tools) {
    pi.registerTool({
      ...tool,
      parameters: Type.Object({}, { additionalProperties: false }),
      async execute(toolCallId, args, signal) {
        const text = await request(`/${tool.name}`, {
          id: toolCallId,
          arguments: args,
        }, signal);
        return { content: [{ type: "text" as const, text }], details: {} };
      },
    });
  }
}
