/** @jsxImportSource @opentui/solid */
import { For } from "solid-js";
import { useKeyboard, useTerminalDimensions } from "@opentui/solid";
import type { KeyEvent } from "@opentui/core";

import { GLYPH, theme } from "@/tui/theme";
import type { Controller, WorkflowGraphNode } from "@/tui/controller";

function consumeKey(key: KeyEvent): void {
  key.preventDefault();
  key.stopPropagation();
}

function nodeColor(node: WorkflowGraphNode): string {
  switch (node.status) {
    case "complete":
      return theme.success;
    case "running":
      return theme.primary;
    case "error":
      return theme.error;
    case "pending":
      return theme.textWeaker;
    default:
      return theme.textMuted;
  }
}

function nodeGlyph(node: WorkflowGraphNode): string {
  switch (node.status) {
    case "complete":
      return GLYPH.ok;
    case "running":
      return GLYPH.running;
    case "error":
      return GLYPH.error;
    case "pending":
      return GLYPH.pending;
    default:
      return "○";
  }
}

function connector(level: number): string {
  if (level <= 0) return "";
  if (level === 1) return "├─ ";
  if (level === 2) return "│  ├─ ";
  return "│  │  └─ ";
}

function kindLabel(kind: WorkflowGraphNode["kind"]): string {
  switch (kind) {
    case "workflow":
      return "workflow";
    case "primary":
      return "primary agent";
    case "stage":
      return "workflow stage";
    case "router":
      return "structured router";
    case "terminal":
      return "graph boundary";
    case "tools":
      return "tools";
    case "parallel":
      return "parallel fan-out";
    case "delegate":
      return "dynamic subagent";
  }
}

export function GraphPanel(props: { controller: Controller }) {
  const c = props.controller;
  const dims = useTerminalDimensions();
  const graph = () => c.workflowGraph();

  useKeyboard((key: KeyEvent) => {
    if (!c.graphOpen()) return;
    if (key.name === "escape") {
      consumeKey(key);
      return c.closeGraph();
    }
    if (key.sequence === "w") {
      consumeKey(key);
      c.closeGraph();
      return c.openWorkflowPicker();
    }
  });

  return (
    <box
      position="absolute"
      left={0}
      top={0}
      zIndex={2540}
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
        <text fg={theme.primary} attributes={1}>GRAPH </text>
        <text fg={theme.textMuted}>{graph().workflow}</text>
      </box>

      <box flexGrow={1} minHeight={0} overflow="hidden" flexDirection="row">
        <box flexGrow={1} minWidth={0} flexDirection="column" paddingRight={2}>
          <text fg={theme.textWeaker} attributes={1}>Workflow Graph</text>
          <For each={graph().nodes}>
            {(node) => (
              <box flexDirection="column" paddingTop={1}>
                <box flexDirection="row">
                  <text fg={theme.textWeaker}>{connector(node.level)}</text>
                  <text fg={nodeColor(node)} attributes={node.status === "running" ? 1 : 0}>
                    {nodeGlyph(node)} {node.label}
                  </text>
                  <text fg={theme.textWeaker}>  {kindLabel(node.kind)}</text>
                </box>
                <text fg={theme.textWeaker}>
                  {"  ".repeat(Math.max(1, node.level + 1))}
                  {node.detail}
                </text>
              </box>
            )}
          </For>
        </box>

        <box width={34} flexShrink={0} border={["left"]} borderColor={theme.borderSubtle} paddingLeft={2} flexDirection="column">
          <text fg={theme.textWeaker} attributes={1}>State</text>
          <box paddingTop={1}>
            <text fg={graph().currentStage === "(idle)" ? theme.textWeaker : theme.primary}>current: {graph().currentStage}</text>
          </box>
          <box paddingTop={1}>
            <text fg={graph().failedStage === "(none)" ? theme.textWeaker : theme.error}>failed: {graph().failedStage}</text>
          </box>
          <box paddingTop={1}>
            <text fg={theme.textWeaker}>gapfill: {graph().gapfillLoops}</text>
          </box>
          <box>
            <text fg={theme.textWeaker}>feedback: {graph().feedbackLoops}</text>
          </box>
          <box paddingTop={1} flexDirection="column">
            <text fg={theme.textWeaker} attributes={1}>Layers</text>
            <text fg={theme.textWeaker}>workflow: execution plan</text>
            <text fg={theme.textWeaker}>primary: owns turn</text>
            <text fg={theme.textWeaker}>parallel: Ruflo fan-out</text>
            <text fg={theme.textWeaker}>delegate: focused subagent</text>
            <text fg={theme.textWeaker}>stage: ordered work</text>
            <text fg={theme.textWeaker}>router: branch decision</text>
            <text fg={theme.textWeaker}>tools: MCP and built-ins</text>
          </box>
        </box>
      </box>

      <box flexShrink={0} minWidth={0} height={3} overflow="hidden" border={["top"]} borderColor={theme.borderSubtle} paddingTop={1}>
        <text fg={theme.textWeaker} wrapMode="none" truncate>Esc close | w workflow</text>
      </box>
    </box>
  );
}
