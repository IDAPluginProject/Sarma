/** @jsxImportSource @opentui/solid */
/**
 * Full-screen configuration workspace for the chat TUI.
 *
 * This mirrors the Python Textual config screen more closely than the old
 * "edit active model" dialog: Models are list-backed and Workflow agent
 * routing is configured in its own section.
 */

import { For, Show, createSignal } from "solid-js";
import { useKeyboard, useTerminalDimensions } from "@opentui/solid";

import { theme } from "@/tui/theme";
import type { AgentDraft, ConfigSection, Controller, ModelDraft } from "@/tui/controller";
import { API_MODES, API_MODE_LABELS } from "@/tui/controller";

interface FieldDef<T> {
  key: keyof T;
  label: string;
  hint: string;
  secret?: boolean;
  placeholder?: string;
}

const MODEL_FIELDS: FieldDef<ModelDraft>[] = [
  { key: "name", label: "Profile", hint: "models.toml [[models]].name", placeholder: "default" },
  { key: "modelName", label: "Model ID", hint: "provider model id", placeholder: "gpt-4o-mini, claude-sonnet-4-6" },
  { key: "apiMode", label: "API mode", hint: "openai_compatible | openai_responses | anthropic", placeholder: "openai_compatible" },
  { key: "baseUrl", label: "Base URL", hint: "blank uses provider default", placeholder: "https://api.openai.com/v1" },
  { key: "apiKey", label: "API key", hint: "stored in models.toml", secret: true, placeholder: "sk-..." },
  { key: "maxContextTokens", label: "Context", hint: "accepts 200K, 1M", placeholder: "128000" },
  { key: "enabled", label: "Enabled", hint: "true or false", placeholder: "true" },
];

const AGENT_FIELDS: FieldDef<AgentDraft>[] = [
  { key: "model", label: "Model", hint: "left/right select model profile", placeholder: "default" },
  { key: "mcp", label: "MCP", hint: "comma list, * for all", placeholder: "*" },
  { key: "skills", label: "Skills", hint: "comma list, blank for none", placeholder: "idapython, docs" },
];

function mask(value: string): string {
  if (!value) return "";
  if (value.length <= 4) return "*".repeat(value.length);
  return "*".repeat(Math.max(0, value.length - 4)) + value.slice(-4);
}

function sectionLabel(section: ConfigSection): string {
  return section === "models" ? "Models" : "Workflow";
}

function ConfigShell(props: { controller: Controller; status: () => string; children: unknown }) {
  const dims = useTerminalDimensions();
  return (
    <box
      position="absolute"
      left={0}
      top={0}
      zIndex={3000}
      width={dims().width}
      height={dims().height}
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
        <text fg={theme.primary} attributes={1}>CONFIG </text>
        <text fg={theme.textMuted}>{sectionLabel(props.controller.configSection())}</text>
      </box>
      {props.children as never}
      <box flexShrink={0} border={["top"]} borderColor={theme.borderSubtle} paddingTop={1}>
        <text fg={props.status().startsWith("Error:") ? theme.error : theme.textWeaker}>
          {props.status() || "Esc close | Ctrl-S save | Enter edit | n new | d delete | a active | left/right section"}
        </text>
      </box>
    </box>
  );
}

function BrowseView(props: { controller: Controller; setStatus: (text: string) => void }) {
  const c = props.controller;
  const modelRows = () => c.configModelRows();
  const workflowRows = () => c.configWorkflowRows();
  const agentRows = () => c.configAgentRows();
  const selected = (idx: number) => c.configSelectedIndex() === idx;
  const selectedWorkflow = (idx: number) => c.configWorkflowSelectedIndex() === idx;
  const selectedAgent = (idx: number) => c.configAgentSelectedIndex() === idx;
  const workflowPaneActive = () => c.configWorkflowPane() === "workflows";
  const agentPaneActive = () => c.configWorkflowPane() === "agents";

  const sectionColor = (section: ConfigSection) => c.configSection() === section ? theme.primary : theme.textMuted;

  const runDelete = async () => {
    const err = await c.deleteConfigModel();
    props.setStatus(err ? `Error: ${err}` : "Model deleted.");
  };

  const runActivate = async () => {
    const err = await c.activateConfigModel();
    props.setStatus(err ? `Error: ${err}` : "Active model updated.");
  };

  useKeyboard((key: { name?: string; ctrl?: boolean; sequence?: string }) => {
    if (!c.configOpen() || c.configStep() !== "browse") return;
    if (key.name === "escape") return c.closeConfig();
    if (key.name === "left") {
      if (c.configSection() === "workflow" && agentPaneActive()) return c.setConfigWorkflowPane("workflows");
      return c.setConfigSection("models");
    }
    if (key.name === "right") {
      if (c.configSection() === "workflow" && workflowPaneActive()) return c.setConfigWorkflowPane("agents");
      return c.setConfigSection("workflow");
    }
    if (key.sequence === "m") return c.setConfigSection("models");
    if (key.sequence === "w") return c.setConfigSection("workflow");
    if (key.name === "tab" && c.configSection() === "workflow") {
      c.setConfigWorkflowPane(agentPaneActive() ? "workflows" : "agents");
      return;
    }
    if (key.name === "up") return c.moveConfigSelection(-1);
    if (key.name === "down") return c.moveConfigSelection(1);
    if (key.sequence === "n" && c.configSection() === "models") return c.newConfigModel();
    if (key.sequence === "d" && c.configSection() === "models") return void runDelete();
    if (key.sequence === "a" && c.configSection() === "models") return void runActivate();
    if (key.name === "return" || key.name === "enter" || key.sequence === "e") {
      if (c.configSection() === "models") c.editConfigModel();
      else if (workflowPaneActive()) c.setConfigWorkflowPane("agents");
      else c.editConfigAgent();
    }
  });

  return (
    <box flexGrow={1} minHeight={0} flexDirection="row">
      <box width={18} flexShrink={0} border={["right"]} borderColor={theme.borderSubtle} paddingRight={1} flexDirection="column">
        <text fg={sectionColor("models")} attributes={c.configSection() === "models" ? 1 : 0}>Models</text>
        <text fg={sectionColor("workflow")} attributes={c.configSection() === "workflow" ? 1 : 0}>Workflow</text>
      </box>

      <box width={36} flexShrink={0} border={["right"]} borderColor={theme.borderSubtle} paddingLeft={1} paddingRight={1} flexDirection="column">
        <Show
          when={c.configSection() === "models"}
          fallback={
            <box flexDirection="column">
              <text fg={workflowPaneActive() ? theme.primary : theme.textWeaker} attributes={1}>Workflows</text>
              <For each={workflowRows()}>
                {(row, i) => (
                  <box flexDirection="column" paddingBottom={1}>
                    <text
                      fg={selectedWorkflow(i()) ? theme.primary : theme.text}
                      attributes={selectedWorkflow(i()) ? 1 : 0}
                    >
                      {workflowPaneActive() && selectedWorkflow(i()) ? "> " : "  "}{row.current ? "* " : "  "}{row.name}
                    </text>
                    <text fg={theme.textWeaker}>  {row.agentCount} agent{row.agentCount === 1 ? "" : "s"}</text>
                  </box>
                )}
              </For>
            </box>
          }
        >
          <For each={modelRows()}>
            {(row, i) => (
              <box flexDirection="column" paddingBottom={1}>
                <text fg={selected(i()) ? theme.primary : theme.text} attributes={selected(i()) ? 1 : 0}>
                  {selected(i()) ? "> " : "  "}{row.active ? "* " : "  "}{row.name}
                </text>
                <text fg={row.enabled ? theme.textWeaker : theme.error}>
                  {"  "}{row.modelName || "(unset)"} [{row.apiMode}, {row.enabled ? "enabled" : "disabled"}]
                </text>
              </box>
            )}
          </For>
        </Show>
      </box>

      <box flexGrow={1} minWidth={0} paddingLeft={2} flexDirection="column">
        <Show
          when={c.configSection() === "models"}
          fallback={
            <box flexDirection="column">
              <text fg={agentPaneActive() ? theme.primary : theme.textWeaker} attributes={1}>Agents</text>
              <For each={agentRows()}>
                {(row, i) => (
                  <box flexDirection="column" paddingBottom={1}>
                    <text
                      fg={selectedAgent(i()) ? theme.primary : theme.text}
                      attributes={selectedAgent(i()) ? 1 : 0}
                    >
                      {agentPaneActive() && selectedAgent(i()) ? "> " : "  "}{row.name}
                    </text>
                    <text fg={theme.textWeaker}>  model {row.model} | mcp {row.mcp} | skills {row.skills}</text>
                  </box>
                )}
              </For>
              <box paddingTop={1}>
                <text fg={theme.textWeaker}>Tab or right focuses agents. Enter edits selected agent.</text>
              </box>
            </box>
          }
        >
          <box flexDirection="column">
            <text fg={theme.textWeaker} attributes={1}>Model Profiles</text>
            <text fg={theme.text}>Enter edit selected model. n creates a blank model.</text>
            <text fg={theme.text}>a selects the active model used by /model and default agents.</text>
            <text fg={theme.textWeaker}>Saving a model does not switch active model automatically.</text>
          </box>
        </Show>
      </box>
    </box>
  );
}

function ModelFields(props: { controller: Controller; setStatus: (text: string) => void }) {
  const c = props.controller;
  const [focusIdx, setFocusIdx] = createSignal(0);
  const [saving, setSaving] = createSignal(false);
  const [testing, setTesting] = createSignal(false);
  const move = (delta: number) => setFocusIdx((idx) => (idx + delta + MODEL_FIELDS.length) % MODEL_FIELDS.length);
  const focusedField = () => MODEL_FIELDS[focusIdx()];
  const apiModeIndex = () => Math.max(0, API_MODES.indexOf(c.modelDraft.apiMode));
  const cycleApiMode = (delta: number) => {
    const next = (apiModeIndex() + delta + API_MODES.length) % API_MODES.length;
    c.setModelField("apiMode", API_MODES[next]!);
  };

  const save = async () => {
    if (saving()) return;
    setSaving(true);
    const err = await c.saveModel();
    setSaving(false);
    props.setStatus(err ? `Error: ${err}` : "Model saved.");
  };

  const test = async () => {
    if (testing()) return;
    setTesting(true);
    props.setStatus("Testing model...");
    const result = await c.testModel();
    setTesting(false);
    props.setStatus(result.startsWith("Model test OK:") ? result : `Error: ${result}`);
  };

  useKeyboard((key: { name?: string; shift?: boolean; ctrl?: boolean }) => {
    if (!c.configOpen() || c.configStep() !== "model-fields") return;
    if (key.name === "escape") return c.backToInterface();
    if (key.name === "tab") return move(key.shift ? -1 : 1);
    if (key.ctrl && key.name === "t") return void test();
    if (focusedField()?.key === "apiMode") {
      if (key.name === "left") return cycleApiMode(-1);
      if (key.name === "right") return cycleApiMode(1);
      if (key.name === "return" || key.name === "enter") {
        props.setStatus(`API mode selected: ${c.modelDraft.apiMode}. Press Ctrl-S to save.`);
        return;
      }
    }
    if (key.name === "up") return move(-1);
    if (key.name === "down") return move(1);
    if ((key.ctrl && key.name === "s") || key.name === "return" || key.name === "enter") return void save();
  });

  return (
    <box flexGrow={1} minHeight={0} flexDirection="column">
      <text fg={theme.textWeaker} attributes={1}>Model Profile</text>
      <For each={MODEL_FIELDS}>
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
                  when={field.key === "apiMode"}
                  fallback={
                    <Show
                      when={field.secret && !active()}
                      fallback={
                        <input
                          value={c.modelDraft[field.key]}
                          focused={active()}
                          onInput={(v: string) => c.setModelField(field.key, v)}
                          placeholder={field.placeholder ?? ""}
                          focusedBackgroundColor={theme.backgroundElement}
                        />
                      }
                    >
                      <text fg={theme.text}>{mask(c.modelDraft[field.key]) || field.placeholder}</text>
                    </Show>
                  }
                >
                  <Show
                    when={active()}
                    fallback={<text fg={theme.text}>{API_MODE_LABELS[c.modelDraft.apiMode] ?? c.modelDraft.apiMode}</text>}
                  >
                    <box flexDirection="row">
                      <text fg={theme.textWeaker}>{"< "}</text>
                      <For each={API_MODES}>
                        {(mode) => {
                          const selected = () => mode === c.modelDraft.apiMode;
                          const label = API_MODE_LABELS[mode] ?? mode;
                          return (
                            <text fg={selected() ? theme.primary : theme.textWeaker} attributes={selected() ? 1 : 0}>
                              {selected() ? `[${label}]` : label}{"  "}
                            </text>
                          );
                        }}
                      </For>
                      <text fg={theme.textWeaker}>{">"}</text>
                    </box>
                  </Show>
                </Show>
              </box>
            </box>
          );
        }}
      </For>
      <Show when={saving()}>
        <box paddingTop={1}><text fg={theme.primary}>saving...</text></box>
      </Show>
      <box paddingTop={1} flexDirection="row">
        <text fg={testing() ? theme.primary : theme.textWeaker} attributes={1}>[ Ctrl-T Test ]</text>
        <text fg={theme.textWeaker}>  validates this draft before using it in chat</text>
      </box>
    </box>
  );
}

function AgentFields(props: { controller: Controller; setStatus: (text: string) => void }) {
  const c = props.controller;
  const [focusIdx, setFocusIdx] = createSignal(0);
  const [saving, setSaving] = createSignal(false);
  const move = (delta: number) => setFocusIdx((idx) => (idx + delta + AGENT_FIELDS.length) % AGENT_FIELDS.length);
  const focusedField = () => AGENT_FIELDS[focusIdx()];
  const modelChoices = () => {
    const names = c.configModelRows().map((row) => row.name).filter(Boolean);
    return ["default", ...names.filter((name) => name !== "default")];
  };
  const modelChoiceIndex = () => Math.max(0, modelChoices().indexOf(c.agentDraft.model || "default"));
  const cycleAgentModel = (delta: number) => {
    const choices = modelChoices();
    if (choices.length === 0) return;
    const next = (modelChoiceIndex() + delta + choices.length) % choices.length;
    c.setAgentField("model", choices[next]!);
  };

  const save = async () => {
    if (saving()) return;
    setSaving(true);
    const err = await c.saveAgent();
    setSaving(false);
    props.setStatus(err ? `Error: ${err}` : "Workflow agent saved.");
  };

  useKeyboard((key: { name?: string; shift?: boolean; ctrl?: boolean }) => {
    if (!c.configOpen() || c.configStep() !== "agent-fields") return;
    if (key.name === "escape") return c.backToInterface();
    if (key.name === "tab") return move(key.shift ? -1 : 1);
    if (focusedField()?.key === "model") {
      if (key.name === "left") return cycleAgentModel(-1);
      if (key.name === "right") return cycleAgentModel(1);
      if (key.name === "return" || key.name === "enter") {
        props.setStatus(`Model selected: ${c.agentDraft.model || "default"}. Press Ctrl-S to save.`);
        return;
      }
    }
    if (key.name === "up") return move(-1);
    if (key.name === "down") return move(1);
    if ((key.ctrl && key.name === "s") || key.name === "return" || key.name === "enter") return void save();
  });

  return (
    <box flexGrow={1} minHeight={0} flexDirection="column">
      <text fg={theme.textWeaker} attributes={1}>Workflow Agent: {c.agentDraft.name}</text>
      <For each={AGENT_FIELDS}>
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
                  when={field.key === "model"}
                  fallback={
                    <input
                      value={c.agentDraft[field.key]}
                      focused={active()}
                      onInput={(v: string) => c.setAgentField(field.key, v)}
                      placeholder={field.placeholder ?? ""}
                      focusedBackgroundColor={theme.backgroundElement}
                    />
                  }
                >
                  <Show
                    when={active()}
                    fallback={<text fg={theme.text}>{c.agentDraft.model || "default"}</text>}
                  >
                    <box flexDirection="row">
                      <text fg={theme.textWeaker}>{"< "}</text>
                      <For each={modelChoices()}>
                        {(name) => {
                          const selected = () => name === (c.agentDraft.model || "default");
                          return (
                            <text fg={selected() ? theme.primary : theme.textWeaker} attributes={selected() ? 1 : 0}>
                              {selected() ? `[${name}]` : name}{"  "}
                            </text>
                          );
                        }}
                      </For>
                      <text fg={theme.textWeaker}>{">"}</text>
                    </box>
                  </Show>
                </Show>
              </box>
            </box>
          );
        }}
      </For>
      <Show when={saving()}>
        <box paddingTop={1}><text fg={theme.primary}>saving...</text></box>
      </Show>
    </box>
  );
}

export function ConfigForm(props: { controller: Controller }) {
  const [status, setStatus] = createSignal("");
  return (
    <ConfigShell controller={props.controller} status={status}>
      <Show
        when={props.controller.configStep() === "browse"}
        fallback={
          <Show
            when={props.controller.configStep() === "model-fields"}
            fallback={<AgentFields controller={props.controller} setStatus={setStatus} />}
          >
            <ModelFields controller={props.controller} setStatus={setStatus} />
          </Show>
        }
      >
        <BrowseView controller={props.controller} setStatus={setStatus} />
      </Show>
    </ConfigShell>
  );
}
