/** @jsxImportSource @opentui/solid */
/**
 * Full-screen Sarma TUI built on @opentui/solid.
 *
 * Layout (kilo-inspired):
 *   ┌ chat (scrollbox, flexGrow) ──┬ sidebar ───┐
 *   │ transcript items             │ workflow   │
 *   │                              │ model      │
 *   │                              │ stages     │
 *   └ prompt input ─────────────────────────────┘
 */

import { For, Show, Switch, Match, createSignal, onMount, onCleanup, type Accessor } from "solid-js";
import { useKeyboard, useRenderer, useSelectionHandler, useTerminalDimensions } from "@opentui/solid";
import "opentui-spinner/solid";

import { theme, SPINNER_FRAMES, GLYPH, SIDEBAR_WIDTH, TRUNCATE } from "@/tui/theme";
import type { Controller, GraphStageView, McpStatusView, TodoView } from "@/tui/controller";
import type { SubagentEntry, TranscriptItem } from "@/tui/transcript";
import { ConfigForm } from "@/tui/configForm";
import { ModelPicker } from "@/tui/modelPicker";
import { PluginPanel } from "@/tui/pluginPanel";
import { RagPanel } from "@/tui/ragPanel";
import { MarkdownBody } from "@/tui/markdown";
import { appendInputHistory, loadInputHistory } from "@/tui/inputHistory";
import { WorkflowPicker } from "@/tui/workflowPicker";
import { GraphPanel } from "@/tui/graphPanel";

export interface TuiKeyEventLike {
  name?: string;
  ctrl?: boolean;
  sequence?: string;
  raw?: string;
}

interface FocusableInputRef {
  focus?: () => void;
}

export function isCtrlCKey(key: TuiKeyEventLike): boolean {
  const name = (key.name ?? "").toLowerCase();
  return (Boolean(key.ctrl) && name === "c") || key.sequence === "\u0003" || key.raw === "\u0003";
}

export function isEscapeKey(key: TuiKeyEventLike): boolean {
  const name = (key.name ?? "").toLowerCase();
  return name === "escape" || key.sequence === "\u001b" || key.raw === "\u001b";
}

export function tuiHelpText(): string {
  return [
    "commands:",
    "  /help             show this help",
    "  /status           show combined runtime status",
    "  /model [name]     list or select active model",
    "  /config           configure model providers",
    "  /mcp              show MCP status",
    "  /skills           show skill status",
    "  /graph            open workflow graph view",
    "  /workflow [name]  select or switch workflow",
    "  /models           show configured models and assignments",
    "  /sessions         list saved sessions",
    "  /resume <id>      resume a saved session",
    "  /plugin           show MCP/skill plugin config and enablement",
    "  /rag              open RAG model and knowledge base config",
    "  /debug [on|off]   enable debug console/file logging",
    "  /restart          restart workflow runtime",
    "  /compact          compact conversation context",
    "  /clear            clear current session history",
    "  /exit             leave the TUI",
  ].join("\n");
}

const STAGE_GLYPH: Record<GraphStageView["status"], string> = {
  pending: GLYPH.pending,
  running: GLYPH.running,
  complete: GLYPH.ok,
  error: GLYPH.error,
};

function stageColor(status: GraphStageView["status"]): string {
  switch (status) {
    case "complete":
      return theme.success;
    case "running":
      return theme.primary;
    case "error":
      return theme.error;
    default:
      return theme.textWeaker;
  }
}

function todoColor(status: TodoView["status"]): string {
  switch (status) {
    case "completed":
      return theme.success;
    case "in_progress":
      return theme.primary;
    default:
      return theme.textWeaker;
  }
}

function todoMarker(status: TodoView["status"]): string {
  switch (status) {
    case "completed":
      return "[X]";
    case "in_progress":
      return "[*]";
    default:
      return "[ ]";
  }
}

function mcpStatusColor(connected: boolean): string {
  return connected ? theme.success : theme.textWeaker;
}

function subagentColor(status: SubagentEntry["status"]): string {
  switch (status) {
    case "complete":
      return theme.success;
    case "running":
      return theme.primary;
    case "error":
      return theme.error;
  }
}

function subagentMarker(status: SubagentEntry["status"]): string {
  switch (status) {
    case "complete":
      return "[X]";
    case "running":
      return "[*]";
    case "error":
      return "[!]";
  }
}

function truncate(text: string, max: number): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length > max ? t.slice(0, max - 1) + "…" : t;
}

function coerceInputValue(arg: unknown, fallback = ""): string {
  if (typeof arg === "string") return arg;
  if (arg && typeof arg === "object") {
    const record = arg as Record<string, unknown>;
    for (const key of ["value", "text", "currentValue"]) {
      if (typeof record[key] === "string") return record[key] as string;
    }
    const target = record.target;
    if (target && typeof target === "object" && typeof (target as Record<string, unknown>).value === "string") {
      return (target as Record<string, string>).value;
    }
  }
  return fallback;
}

function parseJsonRecord(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function ToolView(props: {
  item: Extract<TranscriptItem, { kind: "tool" }>;
  pairedSubagent?: SubagentEntry;
  onOpenSubagent?: (id: string) => void;
}) {
  const t = () => props.item.tool;
  const isDelegate = () => t().name === "delegate_task" || t().name === "task";
  const args = () => parseJsonRecord(t().args);
  const delegateName = () => String(args().subagent_name ?? args().subagent_type ?? "");
  const delegateTask = () => String(args().task ?? args().description ?? "");
  const [open, setOpen] = createSignal(false);
  const expanded = () => open() || isDelegate() || Boolean(props.pairedSubagent);
  const glyph = () =>
    t().status === "running" ? GLYPH.toolRunning : t().status === "ok" ? GLYPH.ok : GLYPH.error;
  const color = () =>
    t().status === "running" ? theme.toolRunning : t().status === "ok" ? theme.toolOk : theme.toolError;
  const title = () => (isDelegate() && delegateName() ? `${t().name} -> ${delegateName()}` : t().name);
  const tail = () =>
    isDelegate() && delegateTask()
      ? truncate(delegateTask(), TRUNCATE.summary)
      : t().status === "running"
        ? truncate(t().args, TRUNCATE.args)
        : truncate(t().summary || t().result || t().error, TRUNCATE.summary);
  const time = () => (t().elapsed > 0.1 ? ` (${t().elapsed.toFixed(1)}s)` : "");
  const hasDetail = () => Boolean(t().args || t().result || t().error || t().summary || props.pairedSubagent);
  const paired = () => props.pairedSubagent;
  const pairedRunning = () => paired()?.status === "running";
  const pairedErrored = () => paired()?.status === "error";
  const pairedPreview = () => {
    const s = paired();
    if (!s) return "";
    return s.error || s.output || s.reasoning || s.result || s.description || "waiting for output...";
  };
  const pairedPreviewLabel = () => {
    const s = paired();
    if (!s) return "TASK";
    if (s.error) return "ERROR";
    if (s.output) return "OUTPUT";
    if (s.reasoning) return "THINKING";
    if (s.result) return "RETURNED RESULT";
    return "TASK";
  };
  return (
    <box
      flexDirection="column"
      paddingLeft={2}
      paddingRight={1}
      border
      borderStyle="single"
      borderColor={t().status === "error" ? theme.error : theme.borderSubtle}
      onMouseDown={() => {
        const subagent = paired();
        if (subagent) {
          props.onOpenSubagent?.(subagent.id);
          return;
        }
        if (hasDetail()) setOpen((v) => !v);
      }}
    >
      <box flexDirection="row">
        <text fg={color()} attributes={1} selectable>
          {hasDetail() ? (expanded() ? "▾" : "▸") : " "}
          {" "}
          {glyph()} {title()}
        </text>
        <text fg={theme.textWeaker} selectable>
          {"  "}
          {tail()}
          {time()}
        </text>
      </box>
      <Show when={expanded() && hasDetail()}>
        <box flexDirection="column" paddingLeft={2} paddingTop={1}>
          <Show when={t().args}>
            <text fg={theme.textMuted} attributes={1}>PARAMS</text>
            <scrollbox
              height={isDelegate() ? 5 : 8}
              backgroundColor={theme.background}
              verticalScrollbarOptions={{
                visible: true,
                showArrows: false,
                trackOptions: { foregroundColor: theme.border, backgroundColor: theme.background },
              }}
              horizontalScrollbarOptions={{ visible: false }}
            >
              <text fg={theme.textWeaker} selectable>{t().args}</text>
            </scrollbox>
          </Show>
          <Show when={paired()}>
            {(subagent: () => SubagentEntry) => (
              <box
                flexDirection="column"
                border={["top"]}
                borderColor={theme.borderSubtle}
                paddingTop={1}
              >
                <text
                  fg={pairedErrored() ? theme.error : pairedRunning() ? theme.primary : theme.success}
                  attributes={1}
                >
                  {pairedRunning() ? "[*]" : pairedErrored() ? "[!]" : "[X]"} SUBAGENT {subagent().name.toUpperCase()}
                </text>
                <text fg={pairedErrored() ? theme.error : theme.textMuted} attributes={1}>
                  {pairedPreviewLabel()}
                </text>
                <scrollbox
                  height={6}
                  backgroundColor={theme.background}
                  verticalScrollbarOptions={{
                    visible: true,
                    showArrows: false,
                    trackOptions: { foregroundColor: theme.border, backgroundColor: theme.background },
                  }}
                  horizontalScrollbarOptions={{ visible: false }}
                >
                  <MarkdownBody content={pairedPreview()} streaming={pairedRunning()} />
                </scrollbox>
                <text fg={theme.textWeaker}>click to open full subagent output</text>
              </box>
            )}
          </Show>
          <Show when={t().error}>
            <text fg={theme.error} attributes={1}>ERROR</text>
            <MarkdownBody content={t().error} />
          </Show>
          <Show when={!paired() && !t().error && t().result}>
            <text fg={theme.textMuted} attributes={1}>RESULT</text>
            <MarkdownBody content={t().result} />
          </Show>
        </box>
      </Show>
    </box>
  );
}

function SubagentView(props: { item: Extract<TranscriptItem, { kind: "subagent" }>; onOpen: (id: string) => void }) {
  const s = () => props.item.subagent;
  const running = () => s().status === "running";
  const errored = () => s().status === "error";
  const detail = () => s().error || s().result || s().output || s().reasoning || s().description;
  const canOpen = () => Boolean(detail());
  const time = () => (s().elapsed > 0.1 ? ` (${s().elapsed.toFixed(1)}s)` : "");
  const branchColor = () => (running() ? theme.toolRunning : errored() ? theme.toolError : theme.toolOk);
  const previewContent = () => s().error || s().output || s().reasoning || s().result || s().description || "waiting for output...";
  const previewLabel = () =>
    s().error ? "ERROR" : s().output ? "OUTPUT" : s().reasoning ? "THINKING" : s().result ? "RETURNED RESULT" : "TASK";
  return (
    <box
      flexDirection="column"
      paddingLeft={2}
      paddingRight={1}
      border
      borderStyle="single"
      borderColor={errored() ? theme.error : running() ? theme.borderActive : theme.borderSubtle}
      onMouseDown={() => {
        if (canOpen()) props.onOpen(s().id);
      }}
    >
      <box flexDirection="row">
        <text fg={branchColor()} attributes={1} selectable>
          {running() ? "[*]" : errored() ? "[!]" : "[X]"} SUBAGENT {s().name.toUpperCase()}
        </text>
        <Show when={running() && s().description}>
          <text fg={theme.textWeaker} selectable> {truncate(s().description, TRUNCATE.desc)}</text>
        </Show>
        <Show when={!running()}>
          <text fg={theme.textWeaker} selectable> {errored() ? "failed" : "complete"}{time()}</text>
        </Show>
      </box>
      <Show when={canOpen()}>
        <box flexDirection="column" paddingLeft={2} paddingTop={1}>
          <text fg={errored() ? theme.error : theme.textMuted} attributes={1}>{previewLabel()}</text>
          <scrollbox
            height={6}
            backgroundColor={theme.background}
            verticalScrollbarOptions={{
              visible: true,
              showArrows: false,
              trackOptions: { foregroundColor: theme.border, backgroundColor: theme.background },
            }}
            horizontalScrollbarOptions={{ visible: false }}
          >
            <MarkdownBody content={previewContent()} streaming={running()} />
          </scrollbox>
          <text fg={theme.textWeaker}>click to open full subagent output</text>
        </box>
      </Show>
    </box>
  );
}

function SubagentDetailPanel(props: {
  subagent: () => SubagentEntry | undefined;
  items: TranscriptItem[];
  onClose: () => void;
}) {
  const dims = useTerminalDimensions();
  const s = props.subagent;
  const tools = () => {
    const subagent = s();
    if (!subagent) return [];
    return props.items.flatMap((item) =>
      item.kind === "tool" && item.tool.subagent === subagent.name ? [item.tool] : [],
    );
  };

  useKeyboard((key) => {
    if (!s()) return;
    if (key.name === "escape") {
      key.preventDefault();
      key.stopPropagation();
      props.onClose();
    }
  });

  return (
    <Show when={s()}>
      {(subagent: () => SubagentEntry) => (
        <box
          position="absolute"
          left={0}
          top={0}
          zIndex={2560}
          width={dims().width}
          height={dims().height}
          overflow="hidden"
          backgroundColor={theme.background}
          border
          borderStyle="single"
          borderColor={subagent().status === "error" ? theme.error : theme.borderActive}
          flexDirection="column"
          paddingLeft={1}
          paddingRight={1}
          paddingTop={1}
          paddingBottom={1}
          onMouseDown={(event) => event.stopPropagation()}
        >
          <box flexDirection="row" paddingBottom={1}>
            <text fg={subagentColor(subagent().status)} attributes={1}>
              SUBAGENT {subagent().name.toUpperCase()}{" "}
            </text>
            <text fg={theme.textWeaker}>
              {subagent().status}{subagent().elapsed > 0.1 ? ` (${subagent().elapsed.toFixed(1)}s)` : ""}
            </text>
          </box>
          <scrollbox
            flexGrow={1}
            minHeight={0}
            paddingRight={1}
            backgroundColor={theme.background}
            verticalScrollbarOptions={{
              visible: true,
              showArrows: false,
              trackOptions: { foregroundColor: theme.border, backgroundColor: theme.background },
            }}
            horizontalScrollbarOptions={{ visible: false }}
          >
            <box flexDirection="column">
              <Show when={subagent().description}>
                <text fg={theme.textMuted} attributes={1}>TASK</text>
                <text fg={theme.textMuted} selectable>{subagent().description}</text>
              </Show>
              <Show when={subagent().reasoning}>
                <box paddingTop={1} flexDirection="column">
                  <text fg={theme.textMuted} attributes={1}>THINKING</text>
                  <text fg={theme.textWeaker} attributes={2} selectable>{subagent().reasoning}</text>
                </box>
              </Show>
              <Show when={subagent().output}>
                <box paddingTop={1} flexDirection="column">
                  <text fg={theme.textMuted} attributes={1}>OUTPUT</text>
                  <MarkdownBody content={subagent().output} streaming={subagent().status === "running"} />
                </box>
              </Show>
              <Show when={tools().length > 0}>
                <box paddingTop={1} flexDirection="column">
                  <text fg={theme.textMuted} attributes={1}>TOOLS</text>
                  <For each={tools()}>
                    {(tool) => (
                      <box
                        flexDirection="column"
                        border={["top"]}
                        borderColor={theme.borderSubtle}
                        paddingTop={1}
                      >
                        <box flexDirection="row">
                          <text
                            fg={tool.status === "running" ? theme.toolRunning : tool.status === "ok" ? theme.toolOk : theme.toolError}
                            attributes={1}
                            selectable
                          >
                            {tool.status === "running" ? "[*]" : tool.status === "ok" ? "[X]" : "[!]"} {tool.name}
                          </text>
                          <text fg={theme.textWeaker} selectable>
                            {tool.elapsed > 0.1 ? ` (${tool.elapsed.toFixed(1)}s)` : ""}
                          </text>
                        </box>
                        <Show when={tool.args}>
                          <text fg={theme.textWeaker} selectable>{truncate(tool.args, 160)}</text>
                        </Show>
                        <Show when={tool.error || tool.result || tool.summary}>
                          <MarkdownBody content={tool.error || tool.result || tool.summary} />
                        </Show>
                      </box>
                    )}
                  </For>
                </box>
              </Show>
              <Show when={subagent().error}>
                <box paddingTop={1} flexDirection="column">
                  <text fg={theme.error} attributes={1}>ERROR</text>
                  <MarkdownBody content={subagent().error} />
                </box>
              </Show>
              <Show when={!subagent().error && subagent().result}>
                <box paddingTop={1} flexDirection="column">
                  <text fg={theme.textMuted} attributes={1}>RETURNED RESULT</text>
                  <MarkdownBody content={subagent().result} />
                </box>
              </Show>
            </box>
          </scrollbox>
          <box flexShrink={0} minWidth={0} height={3} overflow="hidden" border={["top"]} borderColor={theme.borderSubtle} paddingTop={1}>
            <text fg={theme.textWeaker} wrapMode="none" truncate>Esc close</text>
          </box>
        </box>
      )}
    </Show>
  );
}

function MessageView(props: { item: Extract<TranscriptItem, { kind: "message" }> }) {
  const isUser = () => props.item.role === "user";
  return (
    <box flexDirection="column" paddingTop={1}>
      <Show when={props.item.reasoning}>
        <text fg={theme.textWeaker} attributes={2} selectable>
          {props.item.reasoning}
        </text>
      </Show>
      <box flexDirection="row">
        <text fg={isUser() ? theme.userAccent : theme.assistantAccent} attributes={1} selectable>
          {isUser() ? `${GLYPH.user} ` : `${GLYPH.assistant} `}
        </text>
        <box flexGrow={1}>
          <MarkdownBody content={props.item.content} />
        </box>
      </box>
    </box>
  );
}

function StageView(props: { item: Extract<TranscriptItem, { kind: "stage" }> }) {
  const s = () => props.item.stage;
  const running = () => s().status === "running";
  const errored = () => s().status === "error";
  const marker = () => (running() ? "[*]" : errored() ? "[!]" : "[X]");
  const label = () => (s().nodeKind === "router" ? "ROUTER" : "STAGE");
  const time = () => (s().elapsed > 0.1 ? ` (${s().elapsed.toFixed(1)}s)` : "");
  return (
    <box
      flexDirection="column"
      paddingLeft={2}
      paddingRight={1}
      border
      borderStyle="single"
      borderColor={errored() ? theme.error : running() ? theme.borderActive : theme.borderSubtle}
    >
      <box flexDirection="row">
        <text fg={stageColor(s().status)} attributes={running() ? 1 : 0} selectable>
          {marker()} {label()} {s().name.toUpperCase()}
        </text>
        <text fg={theme.textWeaker} selectable>
          {" "}
          {running() ? (s().description || "working") : errored() ? "failed" : "complete"}
          {!running() ? time() : ""}
        </text>
      </box>
      <Show when={s().error}>
        <box paddingLeft={2} paddingTop={1}>
          <text fg={theme.error} selectable>{s().error}</text>
        </box>
      </Show>
    </box>
  );
}

function TranscriptView(props: {
  items: TranscriptItem[];
  draft: () => string;
  draftReasoning: () => string;
  onFocusInput: () => void;
  onOpenSubagent: (id: string) => void;
}) {
  const pairedSubagentForTool = (tool: Extract<TranscriptItem, { kind: "tool" }>) => {
    const callId = tool.tool.toolCallId;
    if (!callId) return undefined;
    return props.items.flatMap((item) => (
      item.kind === "subagent" && item.subagent.toolCallId === callId ? [item.subagent] : []
    ))[0];
  };
  const isMergedSubagent = (item: TranscriptItem) => {
    if (item.kind !== "subagent" || !item.subagent.toolCallId) return false;
    return props.items.some(
      (candidate) =>
        candidate.kind === "tool" &&
        candidate.tool.toolCallId === item.subagent.toolCallId &&
        (candidate.tool.name === "delegate_task" || candidate.tool.name === "task"),
    );
  };
  return (
    <scrollbox
      flexGrow={1}
      paddingLeft={1}
      paddingRight={1}
      stickyScroll
      stickyStart="bottom"
      backgroundColor={theme.background}
      focusable
      on:focused={props.onFocusInput}
      verticalScrollbarOptions={{
        visible: true,
        showArrows: false,
        trackOptions: { foregroundColor: theme.border, backgroundColor: theme.background },
      }}
      horizontalScrollbarOptions={{ visible: false }}
      onMouseDown={props.onFocusInput}
    >
      <For each={props.items}>
        {(item) => (
          <Show
            when={item.kind !== "divider" && !isMergedSubagent(item)}
            fallback={item.kind === "divider" ? <box height={1}><text fg={theme.dividerColor}>{"─".repeat(40)}</text></box> : null}
          >
            <Switch>
              <Match when={item.kind === "message"}>
                <MessageView item={item as Extract<TranscriptItem, { kind: "message" }>} />
              </Match>
              <Match when={item.kind === "tool"}>
                <ToolView
                  item={item as Extract<TranscriptItem, { kind: "tool" }>}
                  pairedSubagent={pairedSubagentForTool(item as Extract<TranscriptItem, { kind: "tool" }>)}
                  onOpenSubagent={props.onOpenSubagent}
                />
              </Match>
              <Match when={item.kind === "subagent"}>
                <SubagentView
                  item={item as Extract<TranscriptItem, { kind: "subagent" }>}
                  onOpen={props.onOpenSubagent}
                />
              </Match>
              <Match when={item.kind === "stage"}>
                <StageView item={item as Extract<TranscriptItem, { kind: "stage" }>} />
              </Match>
              <Match when={item.kind === "error"}>
                <box paddingTop={1}>
                  <text fg={theme.error} attributes={1} selectable>
                    {GLYPH.error} {(item as Extract<TranscriptItem, { kind: "error" }>).text}
                  </text>
                </box>
              </Match>
              <Match when={item.kind === "note"}>
                <box paddingTop={1}>
                  <text fg={theme.textMuted} selectable>{(item as Extract<TranscriptItem, { kind: "note" }>).text}</text>
                </box>
              </Match>
            </Switch>
          </Show>
        )}
      </For>
      <Show when={props.draftReasoning()}>
        <box paddingTop={1}>
          <text fg={theme.textWeaker} attributes={2} selectable>
            {props.draftReasoning()}
          </text>
        </box>
      </Show>
      <Show when={props.draft()}>
        <box flexDirection="row" paddingTop={1}>
          <text fg={theme.assistantAccent} attributes={1} selectable>
            {GLYPH.assistant}{" "}
          </text>
          <box flexGrow={1}>
            <MarkdownBody content={props.draft()} streaming />
          </box>
        </box>
      </Show>
    </scrollbox>
  );
}

function SidebarSection(props: { title: string }) {
  return (
    <box flexDirection="column">
      <text fg={theme.textWeaker} attributes={1}>
        {props.title}
      </text>
      <text fg={theme.dividerColor}>{"─".repeat(SIDEBAR_WIDTH - 4)}</text>
    </box>
  );
}

function Sidebar(props: {
  items: TranscriptItem[];
  workflow: () => string;
  modelName: () => string;
  toolCount: () => number;
  mcpStatuses: () => McpStatusView[];
  todoItems: () => TodoView[];
  stages: () => GraphStageView[];
  busy: () => boolean;
  status: () => string;
  onFocusInput: () => void;
}) {
  const subagents = () => props.items.flatMap((item) => (item.kind === "subagent" ? [item.subagent] : []));
  const currentStage = () => props.stages().find((stage) => stage.status === "running")?.name ?? "";
  return (
    <box
      flexShrink={0}
      width={SIDEBAR_WIDTH}
      height="100%"
      flexDirection="column"
      paddingLeft={2}
      paddingRight={1}
      border={["left"]}
      borderColor={theme.borderSubtle}
      backgroundColor={theme.background}
      onMouseDown={props.onFocusInput}
    >
      <SidebarSection title="SESSION" />
      <box flexDirection="row">
        <text fg={theme.textMuted}>workflow </text>
        <text fg={theme.primary}>{props.workflow()}</text>
      </box>
      <box flexDirection="row">
        <text fg={theme.textMuted}>model </text>
        <text fg={theme.text}>{truncate(props.modelName(), TRUNCATE.model)}</text>
      </box>
      <box flexDirection="row">
        <text fg={theme.textMuted}>tools </text>
        <text fg={theme.text}>{props.toolCount()}</text>
      </box>
      <box paddingTop={1} flexDirection="column">
        <SidebarSection title="MCP" />
        <Show when={props.mcpStatuses().length > 0} fallback={<text fg={theme.textWeaker}>none</text>}>
          <For each={props.mcpStatuses()}>
            {(server) => (
              <box flexDirection="row">
                <text fg={mcpStatusColor(server.connected)}>
                  {server.connected ? GLYPH.ok : GLYPH.pending}{" "}
                </text>
                <text fg={theme.text}>{truncate(server.name, 12)}</text>
                <text fg={server.connected ? theme.success : theme.textWeaker}>
                  {" "}
                  {server.connected ? "yes" : "no"}
                </text>
              </box>
            )}
          </For>
        </Show>
      </box>
      <box paddingTop={1} flexDirection="column">
        <SidebarSection title="STATUS" />
        <Show
          when={props.busy()}
          fallback={<text fg={theme.textWeaker}>ready</text>}
        >
          <box flexDirection="row" gap={1}>
            <spinner frames={SPINNER_FRAMES} interval={80} color={theme.primary} />
            <text fg={theme.textMuted}>{props.status()}</text>
          </box>
        </Show>
      </box>
      <Show when={props.todoItems().length > 0}>
        <box paddingTop={1} flexDirection="column">
          <SidebarSection title="TODO" />
          <For each={props.todoItems().slice(0, 6)}>
            {(todo) => (
              <box flexDirection="row">
                <text fg={todoColor(todo.status)} attributes={todo.status === "in_progress" ? 1 : 0}>
                  {todoMarker(todo.status)}{" "}
                </text>
                <text
                  fg={todo.status === "completed" ? theme.textWeaker : todoColor(todo.status)}
                  attributes={todo.status === "in_progress" ? 1 : 0}
                >
                  {truncate(todo.content, SIDEBAR_WIDTH - 8)}
                </text>
              </box>
            )}
          </For>
          <Show when={props.todoItems().length > 6}>
            <text fg={theme.textWeaker}>+{props.todoItems().length - 6} more</text>
          </Show>
        </box>
      </Show>
      <Show when={subagents().length > 0}>
        <box paddingTop={1} flexDirection="column">
          <SidebarSection title="SUBAGENTS" />
          <For each={subagents().slice(-6)}>
            {(subagent) => (
              <box flexDirection="row">
                <text fg={subagentColor(subagent.status)} attributes={subagent.status === "running" ? 1 : 0}>
                  {subagentMarker(subagent.status)}{" "}
                </text>
                <text
                  fg={subagent.status === "complete" ? theme.textWeaker : subagentColor(subagent.status)}
                  attributes={subagent.status === "running" ? 1 : 0}
                >
                  {truncate(subagent.name, SIDEBAR_WIDTH - 8)}
                </text>
              </box>
            )}
          </For>
          <Show when={subagents().length > 6}>
            <text fg={theme.textWeaker}>+{subagents().length - 6} more</text>
          </Show>
        </box>
      </Show>
      <Show when={props.stages().length > 0}>
        <box paddingTop={1} flexDirection="column">
          <box flexDirection="column">
            <box flexDirection="row">
              <text fg={theme.textWeaker} attributes={1}>STAGES</text>
              <Show when={currentStage()}>
                <text fg={theme.textMuted}> current </text>
                <text fg={theme.primary} attributes={1}>{currentStage()}</text>
              </Show>
            </box>
            <text fg={theme.dividerColor}>{"─".repeat(SIDEBAR_WIDTH - 4)}</text>
          </box>
          <For each={props.stages()}>
            {(stage) => (
              <box flexDirection="row">
                <text fg={stageColor(stage.status)} attributes={stage.status === "running" ? 1 : 0}>
                  {STAGE_GLYPH[stage.status]}{" "}
                </text>
                <text
                  fg={
                    stage.status === "pending"
                      ? theme.textWeaker
                      : stage.status === "running"
                        ? theme.primary
                        : theme.text
                  }
                  attributes={stage.status === "running" ? 1 : 0}
                >
                  {stage.name}
                </text>
              </box>
            )}
          </For>
        </box>
      </Show>
    </box>
  );
}

const SARMA_SPLASH_ART = [
  "███████╗ █████╗ ██████╗ ███╗   ███╗ █████╗ ",
  "██╔════╝██╔══██╗██╔══██╗████╗ ████║██╔══██╗",
  "███████╗███████║██████╔╝██╔████╔██║███████║",
  "╚════██║██╔══██║██╔══██╗██║╚██╔╝██║██╔══██║",
  "███████║██║  ██║██║  ██║██║ ╚═╝ ██║██║  ██║",
  "╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝",
];

export interface AppProps {
  controller: Controller;
  onExit: () => void;
  startupAnimation?: boolean | { durationMs?: number };
  mountInitialization?: boolean;
}

export function StartupSplash(props: { durationMs?: number; onDone?: () => void; label?: string }) {
  const dims = useTerminalDimensions();
  const [frame, setFrame] = createSignal(0);
  let interval: ReturnType<typeof setInterval> | undefined;
  let timeout: ReturnType<typeof setTimeout> | undefined;

  const artWidth = SARMA_SPLASH_ART.reduce((max, line) => Math.max(max, line.length), 0);
  const leftPadding = () => {
    const center = Math.max(0, Math.floor((dims().width - artWidth) / 2));
    return center;
  };
  const topPadding = () => Math.max(1, Math.floor((dims().height - SARMA_SPLASH_ART.length - 2) / 2));
  const dots = () => ".".repeat((frame() % 4) + 1).padEnd(4, " ");
  const label = () => props.label ?? "loading runtime";

  onMount(() => {
    interval = setInterval(() => setFrame((value) => value + 1), 90);
    if (props.durationMs !== undefined && props.onDone) {
      timeout = setTimeout(props.onDone, props.durationMs);
    }
  });

  onCleanup(() => {
    if (interval) clearInterval(interval);
    if (timeout) clearTimeout(timeout);
  });

  return (
    <box
      position="absolute"
      left={0}
      top={0}
      zIndex={4096}
      width={dims().width}
      height={dims().height}
      overflow="hidden"
      backgroundColor={theme.background}
      flexDirection="column"
      paddingTop={topPadding()}
      paddingLeft={leftPadding()}
    >
      <For each={SARMA_SPLASH_ART}>
        {(line) => (
          <text fg={theme.primary} attributes={1} wrapMode="none" truncate>
            {line}
          </text>
        )}
      </For>
      <text fg={theme.primary} attributes={1}>
        SARMA {label()}{dots()}
      </text>
    </box>
  );
}

export function TuiBoot(props: {
  initialize: () => Promise<Controller>;
  onExit: () => void;
  onError: (error: unknown) => void;
}) {
  const [controller, setController] = createSignal<Controller>();

  onMount(() => {
    let cancelled = false;
    const boot = async () => {
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
      const next = await props.initialize();
      if (!cancelled) setController(() => next);
    };
    void boot().catch(props.onError);
    onCleanup(() => {
      cancelled = true;
    });
  });

  return (
    <Show
      when={controller()}
      fallback={<StartupSplash label="initializing" />}
    >
      {(activeController: Accessor<Controller>) => (
        <App
          controller={activeController()}
          onExit={props.onExit}
          mountInitialization={false}
        />
      )}
    </Show>
  );
}

export function App(props: AppProps) {
  const c = props.controller;
  const renderer = useRenderer();
  const [input, setInput] = createSignal("");
  const [inputHistory, setInputHistory] = createSignal<string[]>([]);
  const [selectedSubagentId, setSelectedSubagentId] = createSignal("");
  const [startupVisible, setStartupVisible] = createSignal(Boolean(props.startupAnimation));
  // Double Ctrl+C to exit (kilo pattern): first press arms a 1s window.
  const [exitArmed, setExitArmed] = createSignal(false);
  const [cancelArmed, setCancelArmed] = createSignal(false);
  let exitTimer: ReturnType<typeof setTimeout> | undefined;
  let cancelTimer: ReturnType<typeof setTimeout> | undefined;
  let inputRef: FocusableInputRef | undefined;
  let historyIndex: number | undefined;
  let historyDraft = "";
  let historyAppliedValue: string | undefined;
  let activeSubmittedPrompt = "";

  const focusInput = () => {
    inputRef?.focus?.();
  };

  const startupDurationMs = () =>
    typeof props.startupAnimation === "object" ? props.startupAnimation.durationMs ?? 1100 : 1100;

  const handleWorkflowStopEsc = () => {
    if (cancelArmed()) {
      if (cancelTimer) clearTimeout(cancelTimer);
      setCancelArmed(false);
      if (c.cancelCurrentRun()) {
        if (activeSubmittedPrompt) {
          historyAppliedValue = activeSubmittedPrompt;
          setInput(activeSubmittedPrompt);
          resetHistoryNavigation();
        }
      } else {
        c.note("No active workflow to stop.");
      }
      return;
    }
    setCancelArmed(true);
    c.note("Press Esc again to stop the current workflow.");
    if (cancelTimer) clearTimeout(cancelTimer);
    cancelTimer = setTimeout(() => setCancelArmed(false), 1000);
  };

  const rawEscStopHandler = (sequence: string): boolean => {
    if (sequence !== "\u001b" || overlaysOpen() || !c.busy()) return false;
    handleWorkflowStopEsc();
    return true;
  };

  onMount(() => {
    // Chat-first: land in the chat. Use /config to configure the provider.
    focusInput();
    renderer.prependInputHandler?.(rawEscStopHandler);
    setInputHistory(loadInputHistory());
    if (props.mountInitialization !== false) {
      void c.refreshMcpStatus();
      if (!c.hasModel()) {
        c.note("No model configured yet. Type /config to set one up.");
      }
    }
  });

  onCleanup(() => {
    renderer.removeInputHandler?.(rawEscStopHandler);
    if (exitTimer) clearTimeout(exitTimer);
    if (cancelTimer) clearTimeout(cancelTimer);
  });

  useSelectionHandler((selection) => {
    const text = selection.getSelectedText();
    if (text.trim()) {
      renderer.copyToClipboardOSC52(text);
    }
  });

  const overlaysOpen = () =>
    Boolean(selectedSubagentId()) ||
    c.configOpen() ||
    c.modelPickerOpen() ||
    c.pluginOpen() ||
    c.ragOpen() ||
    c.workflowPickerOpen() ||
    c.graphOpen();

  const selectedSubagent = () => {
    const id = selectedSubagentId();
    if (!id) return undefined;
    return c.items.flatMap((item) => (item.kind === "subagent" && item.subagent.id === id ? [item.subagent] : []))[0];
  };

  const resetHistoryNavigation = () => {
    historyIndex = undefined;
    historyDraft = "";
  };

  const moveInputHistory = (direction: "older" | "newer") => {
    const entries = inputHistory();
    if (!entries.length) return false;

    if (direction === "older") {
      if (historyIndex === undefined) {
        historyDraft = input();
        historyIndex = entries.length - 1;
      } else {
        historyIndex = Math.max(0, historyIndex - 1);
      }
      historyAppliedValue = entries[historyIndex] ?? "";
      setInput(historyAppliedValue);
      return true;
    }

    if (historyIndex === undefined) return false;
    if (historyIndex < entries.length - 1) {
      historyIndex += 1;
      historyAppliedValue = entries[historyIndex] ?? "";
      setInput(historyAppliedValue);
      return true;
    }
    historyAppliedValue = historyDraft;
    setInput(historyAppliedValue);
    resetHistoryNavigation();
    return true;
  };

  useKeyboard((key: TuiKeyEventLike & { preventDefault?: () => void; stopPropagation?: () => void }) => {
    if (isCtrlCKey(key)) {
      key.preventDefault?.();
      key.stopPropagation?.();
      // The config dialog handles its own Esc/close; Ctrl+C always exits.
      if (exitArmed()) {
        if (exitTimer) clearTimeout(exitTimer);
        props.onExit();
        return;
      }
      setExitArmed(true);
      if (exitTimer) clearTimeout(exitTimer);
      exitTimer = setTimeout(() => setExitArmed(false), 1000);
      return;
    }
    const name = (key.name ?? "").toLowerCase();
    if (!overlaysOpen() && c.busy() && isEscapeKey(key)) {
      key.preventDefault?.();
      key.stopPropagation?.();
      handleWorkflowStopEsc();
      return;
    }
    if (!overlaysOpen() && (name === "up" || name === "down")) {
      if (moveInputHistory(name === "up" ? "older" : "newer")) {
        key.preventDefault?.();
        key.stopPropagation?.();
      }
    }
  });

  const handleInput = (value: unknown) => {
    // Slash commands are handled on submit; this just tracks the buffer.
    const next = coerceInputValue(value, input());
    if (historyAppliedValue === next) {
      historyAppliedValue = undefined;
      setInput(next);
      return;
    }
    historyAppliedValue = undefined;
    resetHistoryNavigation();
    setInput(next);
  };

  // opentui's Input intersects two onSubmit signatures (string value and a
  // SubmitEvent). Accept both and read the value from whichever arrives.
  const onSubmit = (arg: unknown) => {
    const raw = coerceInputValue(arg, input());
    const text = raw.trim();
    if (!text) {
      setInput("");
      return;
    }
    if (text.startsWith("/")) {
      setInput("");
      void runSlash(text);
      return;
    }
    // The controller refuses concurrent turns; check first and keep the text in
    // the buffer so a submit during a busy turn isn't silently lost.
    if (c.busy()) {
      c.note("Still working on the previous turn — hold on a moment.");
      return;
    }
    setInputHistory(appendInputHistory(text));
    resetHistoryNavigation();
    setInput("");
    activeSubmittedPrompt = text;
    void c.submit(text).finally(() => {
      if (activeSubmittedPrompt === text) activeSubmittedPrompt = "";
    });
  };

  const runSlash = async (text: string) => {
    const [rawCmd, ...rest] = text.slice(1).split(/\s+/);
    const cmd = (rawCmd ?? "").toLowerCase();
    const arg = rest.join(" ").trim();
    switch (cmd) {
      case "exit":
        props.onExit();
        break;
      case "clear":
        c.newConversation();
        break;
      case "workflow":
        if (!arg) {
          c.openWorkflowPicker();
        } else if (c.workflows().includes(arg)) {
          c.setWorkflow(arg);
          c.note(`switched to workflow: ${arg}`);
        } else {
          c.note(`unknown workflow: ${arg}. available: ${c.workflows().join(", ")}`);
        }
        break;
      case "config":
        c.openConfig();
        break;
      case "model":
        if (arg) c.note(await c.selectModel(arg));
        else c.openModelPicker();
        break;
      case "mcp":
        c.note(await c.mcpReport());
        break;
      case "skills":
        c.note(c.skillsReport());
        break;
      case "status":
        c.note(await c.statusReport());
        break;
      case "graph":
        if (arg === "status") c.note(c.graphReport());
        else c.openGraph();
        break;
      case "models":
        c.note(c.modelsReport());
        break;
      case "sessions":
        c.note(c.sessionsReport());
        break;
      case "resume":
        if (!arg) {
          c.note("usage: /resume <session-id>");
        } else if (!c.resumeSession(arg)) {
          c.note(`session ${arg} not found`);
        }
        break;
      case "plugin":
        if (arg) c.note(await c.pluginCommand(arg));
        else c.openPlugin();
        break;
      case "rag":
        if (arg === "status") c.note(c.ragReport());
        else c.openRag();
        break;
      case "debug":
        c.note(c.debugReport(arg));
        break;
      case "restart":
        c.note(await c.restartRuntime());
        break;
      case "compact":
        c.note(await c.compactContext());
        break;
      case "help":
        c.note(tuiHelpText());
        break;
      default:
        c.note(`unknown command: /${cmd}`);
        break;
    }
  };

  return (
    <box
      flexDirection="row"
      width="100%"
      height="100%"
      overflow="hidden"
      backgroundColor={theme.background}
      focusable
      on:focused={focusInput}
      onMouseDown={focusInput}
    >
      <box
        flexGrow={1}
        flexDirection="column"
        minWidth={0}
        height="100%"
        overflow="hidden"
        backgroundColor={theme.background}
        focusable
        on:focused={focusInput}
        onMouseDown={focusInput}
      >
        <TranscriptView
          items={c.items}
          draft={c.draft}
          draftReasoning={c.draftReasoning}
          onFocusInput={focusInput}
          onOpenSubagent={setSelectedSubagentId}
        />
        <box
          flexShrink={0}
          flexDirection="row"
          paddingLeft={2}
          paddingRight={1}
          paddingTop={1}
          paddingBottom={1}
          border={["top"]}
          borderColor={c.busy() ? theme.borderActive : theme.borderSubtle}
          backgroundColor={theme.backgroundPanel}
          onMouseDown={focusInput}
        >
          <text fg={theme.primary} attributes={1}>
            {c.workflow()} {GLYPH.user}{" "}
          </text>
          <input
            flexGrow={1}
            ref={(r: FocusableInputRef) => (inputRef = r)}
            value={input()}
            onInput={handleInput}
            onSubmit={onSubmit}
            backgroundColor={theme.backgroundPanel}
            focusedBackgroundColor={theme.backgroundPanel}
            placeholder="Ask Sarma to audit..."
          />
        </box>
      </box>
      <Sidebar
        items={c.items}
        workflow={c.workflow}
        modelName={c.modelName}
        toolCount={c.toolCount}
        mcpStatuses={c.mcpStatuses}
        todoItems={c.todoItems}
        stages={c.stages}
        busy={c.busy}
        status={c.status}
        onFocusInput={focusInput}
      />
      <Show when={c.configOpen()}>
        <ConfigForm controller={c} />
      </Show>
      <Show when={c.modelPickerOpen()}>
        <ModelPicker controller={c} />
      </Show>
      <Show when={c.workflowPickerOpen()}>
        <WorkflowPicker controller={c} />
      </Show>
      <Show when={c.graphOpen()}>
        <GraphPanel controller={c} />
      </Show>
      <SubagentDetailPanel subagent={selectedSubagent} items={c.items} onClose={() => setSelectedSubagentId("")} />
      <Show when={c.pluginOpen()}>
        <PluginPanel controller={c} />
      </Show>
      <Show when={c.ragOpen()}>
        <RagPanel controller={c} />
      </Show>
      <Show when={startupVisible()}>
        <StartupSplash durationMs={startupDurationMs()} onDone={() => setStartupVisible(false)} />
      </Show>
    </box>
  );
}
