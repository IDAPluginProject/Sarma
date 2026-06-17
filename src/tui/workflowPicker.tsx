/** @jsxImportSource @opentui/solid */
import { For, Show, createSignal } from "solid-js";
import { useKeyboard, useTerminalDimensions } from "@opentui/solid";
import type { KeyEvent } from "@opentui/core";

import { theme } from "@/tui/theme";
import type { Controller, WorkflowPickerRow } from "@/tui/controller";

function consumeKey(key: KeyEvent): void {
  key.preventDefault();
  key.stopPropagation();
}

function statusColor(row: WorkflowPickerRow): string {
  return row.current ? theme.success : theme.textWeaker;
}

function statusText(row: WorkflowPickerRow): string {
  if (row.current) return "active";
  if (row.isDefault) return "default";
  return "available";
}

export function WorkflowPicker(props: { controller: Controller }) {
  const c = props.controller;
  const dims = useTerminalDimensions();
  const [status, setStatus] = createSignal("Esc close | Enter select | g graph");
  const rows = () => c.workflowRows();
  const selected = (idx: number) => c.workflowPickerSelectedIndex() === idx;

  const activate = () => {
    const err = c.activateWorkflowPickerSelection();
    if (err) setStatus(`Error: ${err}`);
  };

  useKeyboard((key: KeyEvent) => {
    if (!c.workflowPickerOpen()) return;
    if (key.name === "escape") {
      consumeKey(key);
      return c.closeWorkflowPicker();
    }
    if (key.name === "up") {
      consumeKey(key);
      return c.moveWorkflowPickerSelection(-1);
    }
    if (key.name === "down") {
      consumeKey(key);
      return c.moveWorkflowPickerSelection(1);
    }
    if (key.sequence === "g") {
      consumeKey(key);
      c.closeWorkflowPicker();
      return c.openGraph();
    }
    if (key.name === "return" || key.name === "enter") {
      consumeKey(key);
      return activate();
    }
  });

  return (
    <box
      position="absolute"
      left={0}
      top={0}
      zIndex={2550}
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
        <text fg={theme.primary} attributes={1}>
          WORKFLOW{" "}
        </text>
        <text fg={theme.textMuted}>Select active workflow</text>
      </box>

      <box flexGrow={1} minHeight={0} overflow="hidden" flexDirection="column">
        <Show
          when={rows().length > 0}
          fallback={<text fg={theme.textWeaker}>No workflows configured.</text>}
        >
          <For each={rows()}>
            {(row, i) => (
              <box flexDirection="column" paddingBottom={1}>
                <box flexDirection="row">
                  <text fg={selected(i()) ? theme.primary : theme.text} attributes={selected(i()) ? 1 : 0}>
                    {selected(i()) ? "> " : "  "}
                    {row.current ? "* " : "  "}
                    {row.name}
                  </text>
                  <text fg={statusColor(row)}>  {statusText(row)}</text>
                  <text fg={theme.textWeaker}>  {row.agentCount} agent{row.agentCount === 1 ? "" : "s"}</text>
                </box>
                <text fg={theme.textWeaker}>    {row.description || "(no description)"}</text>
              </box>
            )}
          </For>
        </Show>
      </box>

      <box flexShrink={0} minWidth={0} height={3} overflow="hidden" border={["top"]} borderColor={theme.borderSubtle} paddingTop={1}>
        <text fg={status().startsWith("Error:") ? theme.error : theme.textWeaker} wrapMode="none" truncate>{status()}</text>
      </box>
    </box>
  );
}
