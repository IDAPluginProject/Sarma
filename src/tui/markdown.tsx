/** @jsxImportSource @opentui/solid */
import { For, Show, createMemo } from "solid-js";
import { marked, type Token, type Tokens } from "marked";

import { theme } from "@/tui/theme";

interface MarkdownBodyProps {
  content: string;
  streaming?: boolean;
}

function parseMarkdown(content: string, streaming = false): Token[] {
  const source = streaming ? closeStreamingFences(content) : content;
  try {
    return marked.lexer(source) as Token[];
  } catch {
    return [{ type: "paragraph", raw: content, text: content, tokens: [{ type: "text", raw: content, text: content }] }];
  }
}

function closeStreamingFences(content: string): string {
  const fences = content.match(/^\s*(```|~~~)/gm);
  if (!fences || fences.length % 2 === 0) return content;
  const marker = fences[fences.length - 1]!.trim().startsWith("~") ? "~~~" : "```";
  return `${content}\n${marker}`;
}

function inlineText(tokens: Token[] | undefined, fallback = ""): string {
  if (!tokens || tokens.length === 0) return fallback;
  return tokens.map(tokenText).join("");
}

function tokenText(token: Token): string {
  switch (token.type) {
    case "text": {
      const t = token as Tokens.Text;
      return t.tokens ? inlineText(t.tokens, t.text) : t.text;
    }
    case "escape":
      return (token as Tokens.Escape).text;
    case "codespan":
      return (token as Tokens.Codespan).text;
    case "strong":
      return inlineText((token as Tokens.Strong).tokens, (token as Tokens.Strong).text);
    case "em":
      return inlineText((token as Tokens.Em).tokens, (token as Tokens.Em).text);
    case "del":
      return inlineText((token as Tokens.Del).tokens, (token as Tokens.Del).text);
    case "link": {
      const link = token as Tokens.Link;
      const label = inlineText(link.tokens, link.text);
      return link.href && link.href !== label ? `${label} (${link.href})` : label;
    }
    case "image": {
      const image = token as Tokens.Image;
      return image.href ? `${image.text || "image"} (${image.href})` : image.text;
    }
    case "br":
      return "\n";
    default: {
      const generic = token as { tokens?: Token[]; text?: string; raw?: string };
      if (generic.tokens) return inlineText(generic.tokens, generic.text ?? "");
      return generic.text ?? generic.raw ?? "";
    }
  }
}

function blockText(tokens: Token[]): string {
  return tokens
    .map((token) => {
      if (token.type === "paragraph") {
        const paragraph = token as Tokens.Paragraph;
        return inlineText(paragraph.tokens, paragraph.text);
      }
      if (token.type === "text") return tokenText(token);
      return tokenText(token);
    })
    .join("\n");
}

function HeadingBlock(props: { token: Tokens.Heading }) {
  const marker = () => (props.token.depth <= 2 ? "" : `${"#".repeat(props.token.depth)} `);
  return (
    <box minWidth={0} overflow="hidden">
      <text fg={theme.primary} attributes={1} selectable wrapMode="word">
        {marker()}
        {inlineText(props.token.tokens, props.token.text)}
      </text>
    </box>
  );
}

function ParagraphBlock(props: { token: Tokens.Paragraph | Tokens.Text }) {
  const text = () =>
    props.token.type === "paragraph"
      ? inlineText(props.token.tokens, props.token.text)
      : inlineText(props.token.tokens, props.token.text);
  return (
    <box minWidth={0} overflow="hidden">
      <text fg={theme.text} selectable wrapMode="word">
        {text()}
      </text>
    </box>
  );
}

function CodeBlock(props: { token: Tokens.Code }) {
  const lang = () => (props.token.lang ? ` ${props.token.lang} ` : "");
  return (
    <box flexDirection="column" minWidth={0} overflow="hidden" paddingLeft={1} paddingRight={1} backgroundColor={theme.backgroundElement}>
      <Show when={lang()}>
        <text fg={theme.textWeaker} attributes={2} selectable wrapMode="none" truncate>
          {lang()}
        </text>
      </Show>
      <text fg={theme.text} selectable wrapMode="char">
        {props.token.text}
      </text>
    </box>
  );
}

function ListBlock(props: { token: Tokens.List }) {
  const start = () => (typeof props.token.start === "number" ? props.token.start : 1);
  return (
    <box flexDirection="column">
      <For each={props.token.items}>
        {(item, index) => {
          const marker = () =>
            props.token.ordered ? `${start() + index()}. ` : item.task ? `[${item.checked ? "x" : " "}] ` : "- ";
          return (
            <box flexDirection="row" minWidth={0} overflow="hidden" paddingLeft={1}>
              <text fg={theme.primary} selectable wrapMode="none" truncate>
                {marker()}
              </text>
              <box flexGrow={1} minWidth={0}>
                <text fg={theme.text} selectable wrapMode="word">
                  {blockText(item.tokens) || item.text}
                </text>
              </box>
            </box>
          );
        }}
      </For>
    </box>
  );
}

function QuoteBlock(props: { token: Tokens.Blockquote }) {
  const text = () =>
    blockText(props.token.tokens)
      .split("\n")
      .map((line) => `> ${line}`)
      .join("\n");
  return (
    <box minWidth={0} overflow="hidden">
      <text fg={theme.warning} attributes={2} selectable wrapMode="word">
        {text()}
      </text>
    </box>
  );
}

function TableBlock(props: { token: Tokens.Table }) {
  const rows = () => {
    const header = props.token.header.map((cell) => inlineText(cell.tokens, cell.text)).join(" | ");
    const body = props.token.rows.map((row) => row.map((cell) => inlineText(cell.tokens, cell.text)).join(" | "));
    return [header, ...body].join("\n");
  };
  return (
    <box minWidth={0} overflow="hidden">
      <text fg={theme.text} selectable wrapMode="word">
        {rows()}
      </text>
    </box>
  );
}

function HrBlock() {
  return (
    <box minWidth={0} overflow="hidden">
      <text fg={theme.dividerColor} selectable wrapMode="none" truncate>
        {"-".repeat(40)}
      </text>
    </box>
  );
}

function HtmlBlock(props: { token: Tokens.HTML | Tokens.Tag }) {
  const text = () => props.token.text.replace(/<[^>]*>/g, "").trim();
  return (
    <Show when={text()}>
      <box minWidth={0} overflow="hidden">
        <text fg={theme.text} selectable wrapMode="word">
          {text()}
        </text>
      </box>
    </Show>
  );
}

function MarkdownBlock(props: { token: Token }) {
  return (
    <Show when={props.token.type !== "space"}>
      <SwitchBlock token={props.token} />
    </Show>
  );
}

function SwitchBlock(props: { token: Token }) {
  switch (props.token.type) {
    case "heading":
      return <HeadingBlock token={props.token as Tokens.Heading} />;
    case "paragraph":
      return <ParagraphBlock token={props.token as Tokens.Paragraph} />;
    case "text":
      return <ParagraphBlock token={props.token as Tokens.Text} />;
    case "code":
      return <CodeBlock token={props.token as Tokens.Code} />;
    case "list":
      return <ListBlock token={props.token as Tokens.List} />;
    case "blockquote":
      return <QuoteBlock token={props.token as Tokens.Blockquote} />;
    case "table":
      return <TableBlock token={props.token as Tokens.Table} />;
    case "hr":
      return <HrBlock />;
    case "html":
      return <HtmlBlock token={props.token as Tokens.HTML | Tokens.Tag} />;
    default:
      return <ParagraphBlock token={{ type: "text", raw: props.token.raw, text: tokenText(props.token) }} />;
  }
}

export function MarkdownBody(props: MarkdownBodyProps) {
  const tokens = createMemo(() => parseMarkdown(props.content, props.streaming));
  return (
    <box flexDirection="column" flexGrow={1} minWidth={0} overflow="hidden">
      <For each={tokens()}>{(token) => <MarkdownBlock token={token} />}</For>
    </box>
  );
}
