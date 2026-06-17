/** @jsxImportSource @opentui/solid */
import { For, Show, createSignal } from "solid-js";
import { useKeyboard, useTerminalDimensions } from "@opentui/solid";
import type { KeyEvent } from "@opentui/core";

import { theme } from "@/tui/theme";
import type { Controller, RagKnowledgeBaseDraft, RagModelDraft, RagSearchDraft, RagSection } from "@/tui/controller";

interface FieldDef<T> {
  key: keyof T;
  label: string;
  hint: string;
  placeholder?: string;
}

const RAG_MODEL_FIELDS: FieldDef<RagModelDraft>[] = [
  { key: "embeddingBackend", label: "Backend", hint: "left/right select huggingface or api", placeholder: "huggingface" },
  { key: "embeddingModel", label: "Model", hint: "embedding model name", placeholder: "text-embedding-3-small" },
  { key: "embeddingApiBase", label: "API base", hint: "optional OpenAI-compatible embeddings endpoint", placeholder: "https://api.openai.com/v1" },
  { key: "embeddingApiKey", label: "API key", hint: "stored in global rag.toml", placeholder: "sk-..." },
  { key: "embeddingLocalPath", label: "Local path", hint: "optional local embedding model path", placeholder: "~/.sarma/rag/models/..." },
  { key: "chunkSize", label: "Chunk size", hint: "positive number, accepts K/M suffix", placeholder: "1200" },
  { key: "chunkOverlap", label: "Overlap", hint: "smaller than chunk size", placeholder: "150" },
];

const RAG_KB_COMMON_FIELDS: FieldDef<RagKnowledgeBaseDraft>[] = [
  { key: "name", label: "Name", hint: "knowledge base name", placeholder: "docs" },
  { key: "backend", label: "Backend", hint: "left/right select sarma_native or chroma_http", placeholder: "sarma_native" },
  { key: "docsPath", label: "Docs path", hint: "path to source docs for local chunking", placeholder: "docs" },
];

const RAG_KB_NATIVE_FIELDS: FieldDef<RagKnowledgeBaseDraft>[] = [
  { key: "chromaPath", label: "DB path", hint: "optional existing Sarma chunk DB path", placeholder: ".sarma/rag/chroma/docs" },
];

const RAG_KB_HTTP_FIELDS: FieldDef<RagKnowledgeBaseDraft>[] = [
  { key: "chromaUrl", label: "Chroma URL", hint: "remote Chroma server URL", placeholder: "http://127.0.0.1:8000" },
  { key: "collectionName", label: "Collection", hint: "remote collection name", placeholder: "docs" },
  { key: "headers", label: "Headers", hint: "optional JSON object", placeholder: "{\"Authorization\":\"Bearer ...\"}" },
];

const RAG_KB_TAIL_FIELDS: FieldDef<RagKnowledgeBaseDraft>[] = [
  { key: "enabled", label: "Enabled", hint: "left/right toggle", placeholder: "true" },
  { key: "scope", label: "Scope", hint: "left/right select workspace or global rag.toml", placeholder: "local" },
];

const RAG_SEARCH_FIELDS: FieldDef<RagSearchDraft>[] = [
  { key: "query", label: "Query", hint: "search terms", placeholder: "SQL injection auth" },
  { key: "knowledgeBase", label: "KB", hint: "optional knowledge base name", placeholder: "docs" },
  { key: "topK", label: "Top K", hint: "1-10 results", placeholder: "5" },
];

function consumeKey(key: KeyEvent): void {
  key.preventDefault();
  key.stopPropagation();
}

function sectionColor(active: boolean): string {
  return active ? theme.primary : theme.textMuted;
}

function boolText(value: boolean): string {
  return value ? "enabled" : "disabled";
}

function kbFields(draft: RagKnowledgeBaseDraft): FieldDef<RagKnowledgeBaseDraft>[] {
  return [
    ...RAG_KB_COMMON_FIELDS,
    ...(draft.backend === "chroma_http" ? RAG_KB_HTTP_FIELDS : RAG_KB_NATIVE_FIELDS),
    ...RAG_KB_TAIL_FIELDS,
  ];
}

function RagShell(props: { controller: Controller; status: () => string; children: unknown }) {
  const dims = useTerminalDimensions();
  return (
    <box
      position="absolute"
      left={0}
      top={0}
      zIndex={2700}
      width={dims().width}
      height={dims().height}
      overflow="hidden"
      backgroundColor={theme.background}
      border
      borderStyle="single"
      borderColor={theme.borderActive}
      flexDirection="column"
      paddingLeft={1}
      paddingRight={1}
      paddingTop={1}
      paddingBottom={1}
    >
      <box flexDirection="row" paddingBottom={1}>
        <text fg={theme.primary} attributes={1}>RAG </text>
        <text fg={theme.textMuted}>{props.controller.ragSection()}</text>
      </box>
      {props.children as never}
      <box flexShrink={0} minWidth={0} height={3} overflow="hidden" border={["top"]} borderColor={theme.borderSubtle} paddingTop={1}>
        <text fg={props.status().startsWith("Error:") ? theme.error : theme.textWeaker} wrapMode="none" truncate>
          {props.status() || "Esc close | left/right section | up/down select | n new | e edit | Space toggle | c chunk"}
        </text>
      </box>
    </box>
  );
}

function BrowseView(props: { controller: Controller; setStatus: (text: string) => void }) {
  const c = props.controller;
  const rows = () => c.ragKnowledgeBaseRows();
  const activeSection = (section: RagSection) => c.ragSection() === section;
  const selected = (idx: number) => c.ragSelectedIndex() === idx;

  const run = async (action: () => Promise<string | null>, ok: string) => {
    const err = await action();
    props.setStatus(err ? `Error: ${err}` : ok);
  };

  useKeyboard((key: KeyEvent) => {
    if (!c.ragOpen() || c.ragStep() !== "browse") return;
    if (key.name === "escape") {
      consumeKey(key);
      return c.closeRag();
    }
    if (key.name === "left") {
      consumeKey(key);
      return c.setRagSection(c.ragSection() === "search" ? "knowledge" : "model");
    }
    if (key.name === "right") {
      consumeKey(key);
      return c.setRagSection(c.ragSection() === "model" ? "knowledge" : "search");
    }
    if (key.sequence === "m") return c.setRagSection("model");
    if (key.sequence === "k") return c.setRagSection("knowledge");
    if (key.sequence === "s") return c.setRagSection("search");
    if (key.name === "up") {
      consumeKey(key);
      return c.moveRagSelection(-1);
    }
    if (key.name === "down") {
      consumeKey(key);
      return c.moveRagSelection(1);
    }
    if (key.sequence === "n" && c.ragSection() === "knowledge") {
      consumeKey(key);
      return c.newRagKnowledgeBase();
    }
    if (key.sequence === "d" && c.ragSection() === "knowledge") {
      consumeKey(key);
      return void run(c.deleteSelectedRagKnowledgeBase, "Knowledge base deleted.");
    }
    if (key.sequence === "c" && c.ragSection() === "knowledge") {
      consumeKey(key);
      props.setStatus("Chunking knowledge base...");
      return void run(c.chunkSelectedRagKnowledgeBase, "Knowledge base chunked.");
    }
    if (key.name === "space" && c.ragSection() === "knowledge") {
      consumeKey(key);
      return void run(c.toggleSelectedRagKnowledgeBase, "Knowledge base updated.");
    }
    if (key.name === "return" || key.name === "enter" || key.sequence === "e") {
      consumeKey(key);
      if (c.ragSection() === "model") return c.editRagModelSettings();
      if (c.ragSection() === "knowledge") return c.editRagKnowledgeBase();
      return c.editRagSearch();
    }
  });

  return (
    <box flexGrow={1} minHeight={0} overflow="hidden" flexDirection="row">
      <box width={18} flexShrink={0} border={["right"]} borderColor={theme.borderSubtle} paddingRight={1} flexDirection="column">
        <text fg={sectionColor(activeSection("model"))} attributes={activeSection("model") ? 1 : 0}>Model</text>
        <text fg={sectionColor(activeSection("knowledge"))} attributes={activeSection("knowledge") ? 1 : 0}>Knowledge</text>
        <text fg={sectionColor(activeSection("search"))} attributes={activeSection("search") ? 1 : 0}>Search</text>
      </box>
      <box flexGrow={1} minWidth={0} paddingLeft={2} flexDirection="column">
        <Show
          when={c.ragSection() === "knowledge"}
          fallback={
            <Show
              when={c.ragSection() === "model"}
              fallback={
                <box flexDirection="column">
                  <text fg={theme.textWeaker} attributes={1}>Search RAG</text>
                  <text fg={theme.textMuted}>Press Enter to edit query and run search.</text>
                </box>
              }
            >
              <box flexDirection="column">
                <text fg={theme.textWeaker} attributes={1}>Embedding</text>
                <text fg={theme.text}>backend {c.ragModelDraft.embeddingBackend}</text>
                <text fg={theme.text}>model {c.ragModelDraft.embeddingModel || "(unset)"}</text>
                <text fg={theme.textWeaker}>chunk {c.ragModelDraft.chunkSize} overlap {c.ragModelDraft.chunkOverlap}</text>
                <text fg={theme.textMuted}>Press Enter to edit global RAG model settings.</text>
              </box>
            </Show>
          }
        >
          <box flexDirection="column">
            <text fg={theme.textWeaker} attributes={1}>Knowledge Bases</text>
            <Show when={rows().length > 0} fallback={<text fg={theme.textWeaker}>No knowledge bases. Press n to add one.</text>}>
              <For each={rows()}>
                {(row, i) => (
                  <box flexDirection="column" paddingBottom={1}>
                    <box flexDirection="row">
                      <text fg={selected(i()) ? theme.primary : theme.text} attributes={selected(i()) ? 1 : 0}>
                        {selected(i()) ? "> " : "  "}{row.name}
                      </text>
                      <text fg={row.enabled ? theme.success : theme.textWeaker}>  {boolText(row.enabled)}</text>
                      <text fg={theme.textWeaker}>  {row.backend}</text>
                    </box>
                    <text fg={theme.textWeaker}>    {row.target}</text>
                    <text fg={theme.textWeaker}>    docs {row.docsPath}</text>
                  </box>
                )}
              </For>
            </Show>
          </box>
        </Show>
      </box>
    </box>
  );
}

function TogglePair(props: { left: string; right: string; value: string; onToggle: () => void }) {
  const leftActive = () => props.value !== props.right;
  return (
    <box flexDirection="row">
      <text fg={theme.textWeaker}>{"< "}</text>
      <text fg={leftActive() ? theme.primary : theme.textWeaker} attributes={leftActive() ? 1 : 0}>
        {leftActive() ? `[${props.left}]` : props.left}{"  "}
      </text>
      <text fg={!leftActive() ? theme.primary : theme.textWeaker} attributes={!leftActive() ? 1 : 0}>
        {!leftActive() ? `[${props.right}]` : props.right}
      </text>
      <text fg={theme.textWeaker}>{" >"}</text>
    </box>
  );
}

function ModelFields(props: { controller: Controller; setStatus: (text: string) => void }) {
  const c = props.controller;
  const [focusIdx, setFocusIdx] = createSignal(0);
  const [saving, setSaving] = createSignal(false);
  const move = (delta: number) => setFocusIdx((idx) => (idx + delta + RAG_MODEL_FIELDS.length) % RAG_MODEL_FIELDS.length);
  const focused = () => RAG_MODEL_FIELDS[focusIdx()];
  const save = async () => {
    if (saving()) return;
    setSaving(true);
    const err = await c.saveRagModelSettings();
    setSaving(false);
    props.setStatus(err ? `Error: ${err}` : "RAG model settings saved.");
  };

  useKeyboard((key: KeyEvent) => {
    if (!c.ragOpen() || c.ragStep() !== "model-fields") return;
    if (key.name === "escape") return consumeKey(key), c.backToRagBrowse();
    if (key.name === "tab") return consumeKey(key), move(key.shift ? -1 : 1);
    if (key.name === "up") return consumeKey(key), move(-1);
    if (key.name === "down") return consumeKey(key), move(1);
    if (focused()?.key === "embeddingBackend" && (key.name === "left" || key.name === "right")) {
      consumeKey(key);
      return c.setRagModelField("embeddingBackend", c.ragModelDraft.embeddingBackend === "api" ? "huggingface" : "api");
    }
    if ((key.ctrl && key.name === "s") || key.name === "return" || key.name === "enter") return consumeKey(key), void save();
  });

  return (
    <box flexGrow={1} minHeight={0} flexDirection="column">
      <text fg={theme.textWeaker} attributes={1}>RAG Model</text>
      <For each={RAG_MODEL_FIELDS}>
        {(field, i) => {
          const active = () => focusIdx() === i();
          return (
            <box flexDirection="column" paddingTop={1}>
              <box flexDirection="row">
                <text fg={active() ? theme.primary : theme.textMuted} attributes={active() ? 1 : 0}>
                  {active() ? "> " : "  "}{field.label}
                </text>
                <text fg={theme.textWeaker}>  {field.hint}</text>
              </box>
              <box paddingLeft={2}>
                <Show
                  when={field.key === "embeddingBackend"}
                  fallback={
                    <input
                      value={c.ragModelDraft[field.key]}
                      focused={active()}
                      onInput={(v: string) => c.setRagModelField(field.key, v)}
                      placeholder={field.placeholder ?? ""}
                      focusedBackgroundColor={theme.backgroundElement}
                    />
                  }
                >
                  <TogglePair
                    left="huggingface"
                    right="api"
                    value={c.ragModelDraft.embeddingBackend}
                    onToggle={() => c.setRagModelField("embeddingBackend", c.ragModelDraft.embeddingBackend === "api" ? "huggingface" : "api")}
                  />
                </Show>
              </box>
            </box>
          );
        }}
      </For>
      <Show when={saving()}><box paddingTop={1}><text fg={theme.primary}>saving...</text></box></Show>
    </box>
  );
}

function KnowledgeBaseFields(props: { controller: Controller; setStatus: (text: string) => void }) {
  const c = props.controller;
  const [focusIdx, setFocusIdx] = createSignal(0);
  const [saving, setSaving] = createSignal(false);
  const fields = () => kbFields(c.ragKnowledgeBaseDraft);
  const move = (delta: number) => setFocusIdx((idx) => (idx + delta + fields().length) % fields().length);
  const focused = () => fields()[focusIdx()];
  const save = async () => {
    if (saving()) return;
    setSaving(true);
    const err = await c.saveRagKnowledgeBase();
    setSaving(false);
    props.setStatus(err ? `Error: ${err}` : "Knowledge base saved.");
  };

  const toggle = (key: keyof RagKnowledgeBaseDraft) => {
    if (key === "backend") c.setRagKnowledgeBaseField("backend", c.ragKnowledgeBaseDraft.backend === "chroma_http" ? "sarma_native" : "chroma_http");
    if (key === "enabled") c.setRagKnowledgeBaseField("enabled", c.ragKnowledgeBaseDraft.enabled === "true" ? "false" : "true");
    if (key === "scope") c.setRagKnowledgeBaseField("scope", c.ragKnowledgeBaseDraft.scope === "global" ? "local" : "global");
  };

  useKeyboard((key: KeyEvent) => {
    if (!c.ragOpen() || c.ragStep() !== "kb-fields") return;
    if (key.name === "escape") return consumeKey(key), c.backToRagBrowse();
    if (key.name === "tab") return consumeKey(key), move(key.shift ? -1 : 1);
    if (key.name === "up") return consumeKey(key), move(-1);
    if (key.name === "down") return consumeKey(key), move(1);
    const fk = focused()?.key;
    if ((fk === "backend" || fk === "enabled" || fk === "scope") && (key.name === "left" || key.name === "right")) {
      consumeKey(key);
      return toggle(fk);
    }
    if ((key.ctrl && key.name === "s") || key.name === "return" || key.name === "enter") return consumeKey(key), void save();
  });

  return (
    <box flexGrow={1} minHeight={0} flexDirection="column">
      <text fg={theme.textWeaker} attributes={1}>Knowledge Base</text>
      <For each={fields()}>
        {(field, i) => {
          const active = () => focusIdx() === i();
          return (
            <box flexDirection="column" paddingTop={1}>
              <box flexDirection="row">
                <text fg={active() ? theme.primary : theme.textMuted} attributes={active() ? 1 : 0}>
                  {active() ? "> " : "  "}{field.label}
                </text>
                <text fg={theme.textWeaker}>  {field.hint}</text>
              </box>
              <box paddingLeft={2}>
                <Show
                  when={field.key === "backend" || field.key === "enabled" || field.key === "scope"}
                  fallback={
                    <input
                      value={c.ragKnowledgeBaseDraft[field.key]}
                      focused={active()}
                      onInput={(v: string) => c.setRagKnowledgeBaseField(field.key, v)}
                      placeholder={field.placeholder ?? ""}
                      focusedBackgroundColor={theme.backgroundElement}
                    />
                  }
                >
                  <Show
                    when={field.key === "backend"}
                    fallback={
                      <Show
                        when={field.key === "enabled"}
                        fallback={<TogglePair left="local" right="global" value={c.ragKnowledgeBaseDraft.scope} onToggle={() => toggle("scope")} />}
                      >
                        <TogglePair left="enabled" right="disabled" value={c.ragKnowledgeBaseDraft.enabled === "true" ? "enabled" : "disabled"} onToggle={() => toggle("enabled")} />
                      </Show>
                    }
                  >
                    <TogglePair left="sarma_native" right="chroma_http" value={c.ragKnowledgeBaseDraft.backend} onToggle={() => toggle("backend")} />
                  </Show>
                </Show>
              </box>
            </box>
          );
        }}
      </For>
      <Show when={saving()}><box paddingTop={1}><text fg={theme.primary}>saving...</text></box></Show>
    </box>
  );
}

function SearchFields(props: { controller: Controller; setStatus: (text: string) => void }) {
  const c = props.controller;
  const [focusIdx, setFocusIdx] = createSignal(0);
  const [running, setRunning] = createSignal(false);
  const move = (delta: number) => setFocusIdx((idx) => (idx + delta + RAG_SEARCH_FIELDS.length) % RAG_SEARCH_FIELDS.length);
  const run = async () => {
    if (running()) return;
    setRunning(true);
    props.setStatus("Searching RAG...");
    const err = await c.runRagSearch();
    setRunning(false);
    props.setStatus(err ? `Error: ${err}` : "Search results added to transcript.");
  };

  useKeyboard((key: KeyEvent) => {
    if (!c.ragOpen() || c.ragStep() !== "search-fields") return;
    if (key.name === "escape") return consumeKey(key), c.backToRagBrowse();
    if (key.name === "tab") return consumeKey(key), move(key.shift ? -1 : 1);
    if (key.name === "up") return consumeKey(key), move(-1);
    if (key.name === "down") return consumeKey(key), move(1);
    if ((key.ctrl && key.name === "s") || key.name === "return" || key.name === "enter") return consumeKey(key), void run();
  });

  return (
    <box flexGrow={1} minHeight={0} flexDirection="column">
      <text fg={theme.textWeaker} attributes={1}>RAG Search</text>
      <For each={RAG_SEARCH_FIELDS}>
        {(field, i) => {
          const active = () => focusIdx() === i();
          return (
            <box flexDirection="column" paddingTop={1}>
              <box flexDirection="row">
                <text fg={active() ? theme.primary : theme.textMuted} attributes={active() ? 1 : 0}>
                  {active() ? "> " : "  "}{field.label}
                </text>
                <text fg={theme.textWeaker}>  {field.hint}</text>
              </box>
              <box paddingLeft={2}>
                <input
                  value={c.ragSearchDraft[field.key]}
                  focused={active()}
                  onInput={(v: string) => c.setRagSearchField(field.key, v)}
                  placeholder={field.placeholder ?? ""}
                  focusedBackgroundColor={theme.backgroundElement}
                />
              </box>
            </box>
          );
        }}
      </For>
      <Show when={running()}><box paddingTop={1}><text fg={theme.primary}>searching...</text></box></Show>
    </box>
  );
}

export function RagPanel(props: { controller: Controller }) {
  const [status, setStatus] = createSignal("");
  return (
    <RagShell controller={props.controller} status={status}>
      <Show
        when={props.controller.ragStep() === "browse"}
        fallback={
          <Show
            when={props.controller.ragStep() === "model-fields"}
            fallback={
              <Show
                when={props.controller.ragStep() === "kb-fields"}
                fallback={<SearchFields controller={props.controller} setStatus={setStatus} />}
              >
                <KnowledgeBaseFields controller={props.controller} setStatus={setStatus} />
              </Show>
            }
          >
            <ModelFields controller={props.controller} setStatus={setStatus} />
          </Show>
        }
      >
        <BrowseView controller={props.controller} setStatus={setStatus} />
      </Show>
    </RagShell>
  );
}
