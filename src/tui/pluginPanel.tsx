/** @jsxImportSource @opentui/solid */
import { For, Show, createSignal } from "solid-js";
import { useKeyboard, useTerminalDimensions } from "@opentui/solid";
import type { KeyEvent } from "@opentui/core";

import { theme } from "@/tui/theme";
import type { Controller, PluginMcpDraft, PluginSection } from "@/tui/controller";

interface FieldDef<T> {
  key: keyof T;
  label: string;
  hint: string;
  placeholder?: string;
}

const MCP_TRANSPORTS = ["http", "sse", "stdio"] as const;
const SKILL_MODES = ["upload", "search"] as const;

const MCP_COMMON_FIELDS: FieldDef<PluginMcpDraft>[] = [
  { key: "name", label: "Name", hint: "mcp.toml [[mcp_servers]].name", placeholder: "ida" },
  { key: "transport", label: "Transport", hint: "left/right select http, sse, or stdio", placeholder: "http" },
];

const MCP_HTTP_FIELDS: FieldDef<PluginMcpDraft>[] = [
  { key: "url", label: "URL", hint: "http/sse MCP endpoint", placeholder: "http://127.0.0.1:5000/mcp" },
  { key: "headers", label: "Headers", hint: "optional JSON object", placeholder: "{\"Authorization\":\"Bearer ...\"}" },
];

const MCP_STDIO_FIELDS: FieldDef<PluginMcpDraft>[] = [
  { key: "command", label: "Command", hint: "stdio executable", placeholder: "python" },
  { key: "args", label: "Args", hint: "optional JSON array", placeholder: "[\"server.py\"]" },
  { key: "env", label: "Env", hint: "optional JSON object", placeholder: "{\"TOKEN\":\"...\"}" },
];

const MCP_ENABLED_FIELD: FieldDef<PluginMcpDraft> = {
  key: "enabled",
  label: "Enabled",
  hint: "left/right toggle",
  placeholder: "true",
};

const MCP_SCOPE_FIELD: FieldDef<PluginMcpDraft> = {
  key: "scope",
  label: "Scope",
  hint: "left/right select workspace or global config",
  placeholder: "local",
};

function boolText(value: boolean): string {
  return value ? "enabled" : "disabled";
}

function mcpFields(draft: PluginMcpDraft): FieldDef<PluginMcpDraft>[] {
  const transportFields = draft.transport === "stdio" ? MCP_STDIO_FIELDS : MCP_HTTP_FIELDS;
  return [...MCP_COMMON_FIELDS, ...transportFields, MCP_ENABLED_FIELD, MCP_SCOPE_FIELD];
}

function sectionColor(active: boolean): string {
  return active ? theme.primary : theme.textMuted;
}

function consumeKey(key: KeyEvent): void {
  key.preventDefault();
  key.stopPropagation();
}

function PluginShell(props: { controller: Controller; status: () => string; children: unknown }) {
  const dims = useTerminalDimensions();
  return (
    <box
      position="absolute"
      left={0}
      top={0}
      zIndex={2800}
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
        <text fg={theme.primary} attributes={1}>PLUGIN </text>
        <text fg={theme.textMuted}>{props.controller.pluginSection() === "mcp" ? "MCP" : "Skills"}</text>
      </box>
      {props.children as never}
      <box flexShrink={0} minWidth={0} height={3} overflow="hidden" border={["top"]} borderColor={theme.borderSubtle} paddingTop={1}>
        <text fg={props.status().startsWith("Error:") ? theme.error : theme.textWeaker} wrapMode="none" truncate>
          {props.status() || "Esc close | left/right section | up/down select | Space toggle | n search/add | e edit"}
        </text>
      </box>
    </box>
  );
}

function BrowseView(props: { controller: Controller; setStatus: (text: string) => void }) {
  const c = props.controller;
  const mcpRows = () => c.pluginMcpRows();
  const skillRows = () => c.pluginSkillRows();
  const selected = (idx: number) => c.pluginSelectedIndex() === idx;
  const activeSection = (section: PluginSection) => c.pluginSection() === section;

  const toggle = async () => {
    const err = await c.toggleSelectedPlugin();
    props.setStatus(err ? `Error: ${err}` : "Plugin updated.");
  };

  useKeyboard((key: KeyEvent) => {
    if (!c.pluginOpen() || c.pluginStep() !== "browse") return;
    if (key.name === "escape") {
      consumeKey(key);
      return c.closePlugin();
    }
    if (key.name === "left") {
      consumeKey(key);
      return c.setPluginSection("mcp");
    }
    if (key.name === "right") {
      consumeKey(key);
      return c.setPluginSection("skills");
    }
    if (key.sequence === "m") {
      consumeKey(key);
      return c.setPluginSection("mcp");
    }
    if (key.sequence === "s") {
      consumeKey(key);
      return c.setPluginSection("skills");
    }
    if (key.name === "up") {
      consumeKey(key);
      return c.movePluginSelection(-1);
    }
    if (key.name === "down") {
      consumeKey(key);
      return c.movePluginSelection(1);
    }
    if (key.sequence === "n" && c.pluginSection() === "mcp") {
      consumeKey(key);
      return c.newPluginMcp();
    }
    if (key.sequence === "n" && c.pluginSection() === "skills") {
      consumeKey(key);
      return c.newPluginSkill();
    }
    if (key.sequence === "e" && c.pluginSection() === "mcp") {
      consumeKey(key);
      return c.editPluginMcp();
    }
    if (key.name === "return" || key.name === "enter" || key.name === "space") {
      consumeKey(key);
      return void toggle();
    }
  });

  return (
    <box flexGrow={1} minHeight={0} overflow="hidden" flexDirection="row">
      <box width={18} flexShrink={0} border={["right"]} borderColor={theme.borderSubtle} paddingRight={1} flexDirection="column">
        <text fg={sectionColor(activeSection("mcp"))} attributes={activeSection("mcp") ? 1 : 0}>MCP</text>
        <text fg={sectionColor(activeSection("skills"))} attributes={activeSection("skills") ? 1 : 0}>Skills</text>
      </box>

      <box flexGrow={1} minWidth={0} overflow="hidden" paddingLeft={2} flexDirection="column">
        <Show
          when={c.pluginSection() === "mcp"}
          fallback={
            <box flexDirection="column">
              <text fg={theme.textWeaker} attributes={1}>Installed Skills</text>
              <Show when={skillRows().length > 0} fallback={<text fg={theme.textWeaker}>No skills installed. Press n to upload or search.</text>}>
                <For each={skillRows()}>
                  {(row, i) => (
                    <box flexDirection="column" paddingBottom={1}>
                      <box flexDirection="row">
                        <text fg={selected(i()) ? theme.primary : theme.text} attributes={selected(i()) ? 1 : 0}>
                          {selected(i()) ? "> " : "  "}{row.name}
                        </text>
                        <text fg={row.enabled ? theme.success : theme.textWeaker}>  {boolText(row.enabled)}</text>
                      </box>
                      <text fg={theme.textWeaker}>    workflow {c.workflow()}</text>
                    </box>
                  )}
                </For>
              </Show>
            </box>
          }
        >
          <box flexDirection="column">
            <text fg={theme.textWeaker} attributes={1}>MCP Servers</text>
            <Show when={mcpRows().length > 0} fallback={<text fg={theme.textWeaker}>No MCP servers. Press n to add one.</text>}>
              <For each={mcpRows()}>
                {(row, i) => (
                  <box flexDirection="column" paddingBottom={1}>
                    <box flexDirection="row">
                      <text fg={selected(i()) ? theme.primary : theme.text} attributes={selected(i()) ? 1 : 0}>
                        {selected(i()) ? "> " : "  "}{row.name}
                      </text>
                      <text fg={row.enabled ? theme.success : theme.textWeaker}>  {boolText(row.enabled)}</text>
                      <text fg={theme.textWeaker}>  {row.transport}</text>
                    </box>
                    <text fg={theme.textWeaker}>    {row.target || "(unset)"}</text>
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

function McpFields(props: { controller: Controller; setStatus: (text: string) => void }) {
  const c = props.controller;
  const [focusIdx, setFocusIdx] = createSignal(0);
  const [saving, setSaving] = createSignal(false);
  const [testing, setTesting] = createSignal(false);
  const fields = () => mcpFields(c.pluginMcpDraft);
  const move = (delta: number) => setFocusIdx((idx) => (idx + delta + fields().length) % fields().length);
  const focusedField = () => fields()[focusIdx()];
  const toggleEnabled = () => c.setPluginMcpField("enabled", c.pluginMcpDraft.enabled === "true" ? "false" : "true");
  const toggleScope = () => c.setPluginMcpField("scope", c.pluginMcpDraft.scope === "global" ? "local" : "global");
  const transportIndex = () => Math.max(0, MCP_TRANSPORTS.indexOf(c.pluginMcpDraft.transport as typeof MCP_TRANSPORTS[number]));
  const cycleTransport = (delta: number) => {
    const next = (transportIndex() + delta + MCP_TRANSPORTS.length) % MCP_TRANSPORTS.length;
    c.setPluginMcpField("transport", MCP_TRANSPORTS[next]!);
  };

  const save = async () => {
    if (saving()) return;
    setSaving(true);
    const err = await c.savePluginMcp();
    setSaving(false);
    props.setStatus(err ? `Error: ${err}` : "MCP saved.");
  };

  const test = async () => {
    if (testing()) return;
    setTesting(true);
    props.setStatus("Testing MCP...");
    const result = await c.testPluginMcp();
    setTesting(false);
    props.setStatus(result.startsWith("MCP test OK:") || result === "MCP test failed" ? result : `Error: ${result}`);
  };

  useKeyboard((key: KeyEvent) => {
    if (!c.pluginOpen() || c.pluginStep() !== "mcp-fields") return;
    if (key.name === "escape") {
      consumeKey(key);
      return c.backToPluginBrowse();
    }
    if (key.name === "tab") {
      consumeKey(key);
      return move(key.shift ? -1 : 1);
    }
    if (key.ctrl && key.name === "t") {
      consumeKey(key);
      return void test();
    }
    if (focusedField()?.key === "transport") {
      if (key.name === "left") {
        consumeKey(key);
        return cycleTransport(-1);
      }
      if (key.name === "right") {
        consumeKey(key);
        return cycleTransport(1);
      }
      if (key.name === "return" || key.name === "enter") {
        consumeKey(key);
        props.setStatus(`Transport selected: ${c.pluginMcpDraft.transport}. Press Ctrl-S to save.`);
        return;
      }
    }
    if (focusedField()?.key === "enabled") {
      if (key.name === "left" || key.name === "right") {
        consumeKey(key);
        return toggleEnabled();
      }
      if (key.name === "return" || key.name === "enter") {
        consumeKey(key);
        return void save();
      }
    }
    if (focusedField()?.key === "scope") {
      if (key.name === "left" || key.name === "right") {
        consumeKey(key);
        return toggleScope();
      }
      if (key.name === "return" || key.name === "enter") {
        consumeKey(key);
        return void save();
      }
    }
    if (key.name === "up") {
      consumeKey(key);
      return move(-1);
    }
    if (key.name === "down") {
      consumeKey(key);
      return move(1);
    }
    if ((key.ctrl && key.name === "s") || key.name === "return" || key.name === "enter") {
      consumeKey(key);
      return void save();
    }
  });

  return (
    <box flexGrow={1} minHeight={0} minWidth={0} overflow="hidden" flexDirection="column">
      <text fg={theme.textWeaker} attributes={1}>MCP Server</text>
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
                  when={field.key === "transport"}
                  fallback={
                    <Show
                      when={field.key === "enabled"}
                      fallback={
                        <Show
                          when={field.key === "scope"}
                          fallback={
                            <input
                              value={c.pluginMcpDraft[field.key]}
                              focused={active()}
                              onInput={(v: string) => c.setPluginMcpField(field.key, v)}
                              placeholder={field.placeholder ?? ""}
                              focusedBackgroundColor={theme.backgroundElement}
                            />
                          }
                        >
                          <box flexDirection="row">
                            <text fg={theme.textWeaker}>{"< "}</text>
                            <text fg={c.pluginMcpDraft.scope !== "global" ? theme.primary : theme.textWeaker} attributes={c.pluginMcpDraft.scope !== "global" ? 1 : 0}>
                              {c.pluginMcpDraft.scope !== "global" ? "[local]" : "local"}{"  "}
                            </text>
                            <text fg={c.pluginMcpDraft.scope === "global" ? theme.primary : theme.textWeaker} attributes={c.pluginMcpDraft.scope === "global" ? 1 : 0}>
                              {c.pluginMcpDraft.scope === "global" ? "[global]" : "global"}
                            </text>
                            <text fg={theme.textWeaker}>{" >"}</text>
                          </box>
                        </Show>
                      }
                    >
                      <box flexDirection="row">
                        <text fg={theme.textWeaker}>{"< "}</text>
                        <text fg={c.pluginMcpDraft.enabled === "true" ? theme.primary : theme.textWeaker} attributes={c.pluginMcpDraft.enabled === "true" ? 1 : 0}>
                          {c.pluginMcpDraft.enabled === "true" ? "[enabled]" : "enabled"}{"  "}
                        </text>
                        <text fg={c.pluginMcpDraft.enabled === "false" ? theme.primary : theme.textWeaker} attributes={c.pluginMcpDraft.enabled === "false" ? 1 : 0}>
                          {c.pluginMcpDraft.enabled === "false" ? "[disabled]" : "disabled"}
                        </text>
                        <text fg={theme.textWeaker}>{" >"}</text>
                      </box>
                    </Show>
                  }
                >
                  <box flexDirection="row">
                    <text fg={theme.textWeaker}>{"< "}</text>
                    <For each={MCP_TRANSPORTS}>
                      {(transport) => {
                        const selected = () => transport === c.pluginMcpDraft.transport;
                        return (
                          <text fg={selected() ? theme.primary : theme.textWeaker} attributes={selected() ? 1 : 0}>
                            {selected() ? `[${transport}]` : transport}{"  "}
                          </text>
                        );
                      }}
                    </For>
                    <text fg={theme.textWeaker}>{">"}</text>
                  </box>
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
        <text fg={theme.textWeaker}>  checks connection and tool count</text>
      </box>
      <box paddingTop={1}>
        <text fg={theme.textWeaker}>HTTP uses streamable HTTP. Headers/env must be JSON when provided.</text>
      </box>
    </box>
  );
}

function SkillFields(props: { controller: Controller; setStatus: (text: string) => void }) {
  const c = props.controller;
  const [focusIdx, setFocusIdx] = createSignal(0);
  const [searching, setSearching] = createSignal(false);
  const [installing, setInstalling] = createSignal(false);
  const rows = () => c.pluginSkillSearchRows();
  const isSearch = () => c.pluginSkillDraft.mode === "search";
  const resultStart = () => 5;
  const uploadActionIndex = () => 5;
  const searchActionIndex = () => 4;
  const itemCount = () => (isSearch() ? resultStart() + rows().length : uploadActionIndex() + 1);
  const move = (delta: number) => setFocusIdx((idx) => (idx + delta + itemCount()) % itemCount());
  const setMode = (mode: "upload" | "search") => {
    c.setPluginSkillField("mode", mode);
    setFocusIdx(0);
  };
  const toggleMode = () => setMode(isSearch() ? "upload" : "search");
  const toggleEnabled = () => c.setPluginSkillField("enabled", c.pluginSkillDraft.enabled === "true" ? "false" : "true");
  const toggleScope = () => c.setPluginSkillField("scope", c.pluginSkillDraft.scope === "global" ? "local" : "global");

  const upload = async () => {
    if (installing()) return;
    setInstalling(true);
    props.setStatus("Uploading skill...");
    const err = await c.savePluginSkill();
    setInstalling(false);
    props.setStatus(err ? `Error: ${err}` : "Skill uploaded.");
  };

  const search = async () => {
    if (searching()) return;
    setSearching(true);
    props.setStatus("Searching SkillHub...");
    const err = await c.searchPluginSkills();
    setSearching(false);
    props.setStatus(err ? `Error: ${err}` : `Found ${rows().length} skill${rows().length === 1 ? "" : "s"}.`);
    if (!err && rows().length > 0) setFocusIdx(resultStart());
  };

  const install = async (name: string) => {
    if (installing()) return;
    setInstalling(true);
    props.setStatus(`Installing ${name}...`);
    const err = await c.installPluginSkill(name);
    setInstalling(false);
    props.setStatus(err ? `Error: ${err}` : `Installed ${name}.`);
  };

  useKeyboard((key: KeyEvent) => {
    if (!c.pluginOpen() || c.pluginStep() !== "skill-fields") return;
    if (key.name === "escape") {
      consumeKey(key);
      return c.backToPluginBrowse();
    }
    if (key.name === "tab") {
      consumeKey(key);
      return move(key.shift ? -1 : 1);
    }
    if (key.name === "up") {
      consumeKey(key);
      return move(-1);
    }
    if (key.name === "down") {
      consumeKey(key);
      return move(1);
    }
    if (focusIdx() === 0 && (key.name === "left" || key.name === "right" || key.name === "space")) {
      consumeKey(key);
      return toggleMode();
    }
    if (focusIdx() === (isSearch() ? 2 : 3) && (key.name === "left" || key.name === "right" || key.name === "space")) {
      consumeKey(key);
      return toggleEnabled();
    }
    if (focusIdx() === (isSearch() ? 3 : 4) && (key.name === "left" || key.name === "right" || key.name === "space")) {
      consumeKey(key);
      return toggleScope();
    }
    if ((key.ctrl && key.name === "s") || key.name === "return" || key.name === "enter") {
      consumeKey(key);
      if (focusIdx() === 0) return toggleMode();
      if (!isSearch()) {
        if (focusIdx() === 3) return toggleEnabled();
        if (focusIdx() === 4) return toggleScope();
        return void upload();
      }
      if (focusIdx() === 1 || focusIdx() === searchActionIndex()) return void search();
      if (focusIdx() === 2) return toggleEnabled();
      if (focusIdx() === 3) return toggleScope();
      const row = rows()[focusIdx() - resultStart()];
      if (row) return void install(row.name);
    }
  });

  return (
    <box flexGrow={1} minHeight={0} flexDirection="column">
      <text fg={theme.textWeaker} attributes={1}>Skill Install</text>
      <box flexDirection="column" paddingTop={1}>
        <box flexDirection="row">
          <text fg={focusIdx() === 0 ? theme.primary : theme.textMuted} attributes={focusIdx() === 0 ? 1 : 0}>
            {focusIdx() === 0 ? "> " : "  "}Mode
          </text>
          <text fg={theme.textWeaker}>  upload a local zip or search SkillHub</text>
        </box>
        <box paddingLeft={2} flexDirection="row">
          <text fg={theme.textWeaker}>{"< "}</text>
          <For each={SKILL_MODES}>
            {(mode) => {
              const selected = () => c.pluginSkillDraft.mode === mode;
              return (
                <text fg={selected() ? theme.primary : theme.textWeaker} attributes={selected() ? 1 : 0}>
                  {selected() ? `[${mode}]` : mode}{"  "}
                </text>
              );
            }}
          </For>
          <text fg={theme.textWeaker}>{">"}</text>
        </box>
      </box>
      <Show
        when={isSearch()}
        fallback={
          <>
            <SkillTextField
              active={focusIdx() === 1}
              label="Zip Path"
              hint="local .zip containing one SKILL.md"
              value={c.pluginSkillDraft.path}
              placeholder="C:\\path\\skills.zip"
              onInput={(v) => c.setPluginSkillField("path", v)}
            />
            <SkillTextField
              active={focusIdx() === 2}
              label="Name"
              hint="optional; required when SKILL.md is at zip root"
              value={c.pluginSkillDraft.name}
              placeholder="idapython"
              onInput={(v) => c.setPluginSkillField("name", v)}
            />
            <SkillToggleRows
              controller={c}
              enableFocused={focusIdx() === 3}
              scopeFocused={focusIdx() === 4}
            />
            <box paddingTop={1} flexDirection="row">
              <text fg={installing() ? theme.primary : theme.textWeaker} attributes={1}>
                {focusIdx() === uploadActionIndex() ? "> " : "  "}[ Enter Upload ]
              </text>
              <text fg={theme.textWeaker}>  validates and installs the local skill zip</text>
            </box>
          </>
        }
      >
        <>
          <SkillTextField
            active={focusIdx() === 1}
            label="Query"
            hint="search SkillHub by name or description"
            value={c.pluginSkillSearchQuery()}
            placeholder="idapython"
            onInput={(v) => c.setPluginSkillSearchQuery(v)}
          />
          <SkillToggleRows
            controller={c}
            enableFocused={focusIdx() === 2}
            scopeFocused={focusIdx() === 3}
          />
          <box paddingTop={1} flexDirection="row">
            <text fg={searching() ? theme.primary : theme.textWeaker} attributes={1}>
              {focusIdx() === searchActionIndex() ? "> " : "  "}[ Enter Search ]
            </text>
            <text fg={theme.textWeaker}>  select a result and press Enter to install</text>
          </box>
          <Show when={rows().length > 0}>
            <box paddingTop={1} flexDirection="column">
              <text fg={theme.textWeaker} attributes={1}>Results</text>
              <For each={rows()}>
                {(row, i) => {
                  const active = () => focusIdx() === i() + resultStart();
                  return (
                    <box flexDirection="column" paddingBottom={1}>
                      <box flexDirection="row">
                        <text fg={active() ? theme.primary : theme.text} attributes={active() ? 1 : 0}>
                          {active() ? "> " : "  "}{row.name}
                        </text>
                        <text fg={row.installed ? theme.success : theme.textWeaker}>  {row.installed ? "installed" : "available"}</text>
                        <text fg={row.enabled ? theme.success : theme.textWeaker}>  {row.enabled ? "enabled" : "disabled"}</text>
                      </box>
                      <Show when={row.description}>
                        <text fg={theme.textWeaker}>    {row.description}</text>
                      </Show>
                    </box>
                  );
                }}
              </For>
            </box>
          </Show>
        </>
      </Show>
      <Show when={installing()}>
        <box paddingTop={1}><text fg={theme.primary}>installing...</text></box>
      </Show>
      <box paddingTop={1}>
        <text fg={theme.textWeaker}>Upload installs zip content into .sarma/skills/name. Search installs SkillHub results.</text>
      </box>
    </box>
  );
}

function SkillTextField(props: {
  active: boolean;
  label: string;
  hint: string;
  value: string;
  placeholder: string;
  onInput: (value: string) => void;
}) {
  return (
    <box flexDirection="column" paddingTop={1}>
      <box flexDirection="row">
        <text fg={props.active ? theme.primary : theme.textMuted} attributes={props.active ? 1 : 0}>
          {props.active ? "> " : "  "}{props.label}
        </text>
        <text fg={theme.textWeaker}>  {props.hint}</text>
      </box>
      <box paddingLeft={2}>
        <input
          value={props.value}
          focused={props.active}
          onInput={props.onInput}
          placeholder={props.placeholder}
          focusedBackgroundColor={theme.backgroundElement}
        />
      </box>
    </box>
  );
}

function SkillToggleRows(props: { controller: Controller; enableFocused: boolean; scopeFocused: boolean }) {
  const c = props.controller;
  return (
    <>
      <box flexDirection="column" paddingTop={1}>
        <box flexDirection="row">
          <text fg={props.enableFocused ? theme.primary : theme.textMuted} attributes={props.enableFocused ? 1 : 0}>
            {props.enableFocused ? "> " : "  "}Enable
          </text>
          <text fg={theme.textWeaker}>  enable for current workflow after install</text>
        </box>
        <box paddingLeft={2} flexDirection="row">
          <text fg={theme.textWeaker}>{"< "}</text>
          <text fg={c.pluginSkillDraft.enabled === "true" ? theme.primary : theme.textWeaker} attributes={c.pluginSkillDraft.enabled === "true" ? 1 : 0}>
            {c.pluginSkillDraft.enabled === "true" ? "[enabled]" : "enabled"}{"  "}
          </text>
          <text fg={c.pluginSkillDraft.enabled === "false" ? theme.primary : theme.textWeaker} attributes={c.pluginSkillDraft.enabled === "false" ? 1 : 0}>
            {c.pluginSkillDraft.enabled === "false" ? "[disabled]" : "disabled"}
          </text>
          <text fg={theme.textWeaker}>{" >"}</text>
        </box>
      </box>
      <box flexDirection="column" paddingTop={1}>
        <box flexDirection="row">
          <text fg={props.scopeFocused ? theme.primary : theme.textMuted} attributes={props.scopeFocused ? 1 : 0}>
            {props.scopeFocused ? "> " : "  "}Scope
          </text>
          <text fg={theme.textWeaker}>  install into workspace or global skills directory</text>
        </box>
        <box paddingLeft={2} flexDirection="row">
          <text fg={theme.textWeaker}>{"< "}</text>
          <text fg={c.pluginSkillDraft.scope !== "global" ? theme.primary : theme.textWeaker} attributes={c.pluginSkillDraft.scope !== "global" ? 1 : 0}>
            {c.pluginSkillDraft.scope !== "global" ? "[local]" : "local"}{"  "}
          </text>
          <text fg={c.pluginSkillDraft.scope === "global" ? theme.primary : theme.textWeaker} attributes={c.pluginSkillDraft.scope === "global" ? 1 : 0}>
            {c.pluginSkillDraft.scope === "global" ? "[global]" : "global"}
          </text>
          <text fg={theme.textWeaker}>{" >"}</text>
        </box>
      </box>
    </>
  );
}

export function PluginPanel(props: { controller: Controller }) {
  const [status, setStatus] = createSignal("");
  return (
    <PluginShell controller={props.controller} status={status}>
      <Show
        when={props.controller.pluginStep() === "browse"}
        fallback={
          <Show
            when={props.controller.pluginStep() === "mcp-fields"}
            fallback={<SkillFields controller={props.controller} setStatus={setStatus} />}
          >
            <McpFields controller={props.controller} setStatus={setStatus} />
          </Show>
        }
      >
        <BrowseView controller={props.controller} setStatus={setStatus} />
      </Show>
    </PluginShell>
  );
}
