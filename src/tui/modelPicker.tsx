/** @jsxImportSource @opentui/solid */
import { For, Show, createSignal } from "solid-js";
import { useKeyboard, useTerminalDimensions } from "@opentui/solid";

import { theme } from "@/tui/theme";
import type { ConfigModelRow, Controller } from "@/tui/controller";

function statusColor(row: ConfigModelRow): string {
  if (row.active) return theme.success;
  if (!row.enabled || !row.modelName.trim()) return theme.error;
  return theme.textWeaker;
}

function statusText(row: ConfigModelRow): string {
  if (row.active) return "active";
  if (!row.enabled) return "disabled";
  if (!row.modelName.trim()) return "missing model id";
  return "available";
}

export function ModelPicker(props: { controller: Controller }) {
  const c = props.controller;
  const dims = useTerminalDimensions();
  const [status, setStatus] = createSignal("Esc close | Enter select | c config");
  const rows = () => c.configModelRows();
  const selected = (idx: number) => c.modelPickerSelectedIndex() === idx;

  const activate = async () => {
    const err = await c.activateModelPickerSelection();
    if (err) setStatus(`Error: ${err}`);
  };

  const openConfig = () => {
    c.closeModelPicker();
    c.openConfig();
  };

  useKeyboard((key: { name?: string; sequence?: string }) => {
    if (!c.modelPickerOpen()) return;
    if (key.name === "escape") return c.closeModelPicker();
    if (key.name === "up") return c.moveModelPickerSelection(-1);
    if (key.name === "down") return c.moveModelPickerSelection(1);
    if (key.sequence === "c") return openConfig();
    if (key.name === "return" || key.name === "enter") return void activate();
  });

  return (
    <box
      position="absolute"
      left={0}
      top={0}
      zIndex={2500}
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
        <text fg={theme.primary} attributes={1}>
          MODEL{" "}
        </text>
        <text fg={theme.textMuted}>Select active provider profile</text>
      </box>

      <box flexGrow={1} minHeight={0} flexDirection="column">
        <Show
          when={rows().length > 0}
          fallback={
            <box flexDirection="column">
              <text fg={theme.text}>No model profiles configured.</text>
              <text fg={theme.textWeaker}>Press c to open /config and add one.</text>
            </box>
          }
        >
          <For each={rows()}>
            {(row, i) => (
              <box flexDirection="column" paddingBottom={1}>
                <box flexDirection="row">
                  <text fg={selected(i()) ? theme.primary : theme.text} attributes={selected(i()) ? 1 : 0}>
                    {selected(i()) ? "> " : "  "}
                    {row.active ? "* " : "  "}
                    {row.name}
                  </text>
                  <text fg={statusColor(row)}>  {statusText(row)}</text>
                </box>
                <text fg={row.enabled && row.modelName.trim() ? theme.textWeaker : theme.error}>
                  {"    "}
                  {row.modelName || "(unset)"}
                  {"  "}
                  [{row.apiMode}]
                </text>
              </box>
            )}
          </For>
        </Show>
      </box>

      <box flexShrink={0} border={["top"]} borderColor={theme.borderSubtle} paddingTop={1}>
        <text fg={status().startsWith("Error:") ? theme.error : theme.textWeaker}>{status()}</text>
      </box>
    </box>
  );
}
