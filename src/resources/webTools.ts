/** Built-in web search tool. */

import { tool } from "@langchain/core/tools";
import { z } from "zod";
import type { StructuredToolInterface } from "@langchain/core/tools";

interface SearchResult {
  title: string;
  url: string;
  snippet: string;
}

/** Build the built-in LangChain web search tool. */
export function buildWebSearchTool(): StructuredToolInterface {
  const webSearch = tool(
    async ({
      query,
      max_results = 5,
      timeout = 10.0,
    }: {
      query: string;
      max_results?: number;
      timeout?: number;
    }): Promise<string> => searchWeb(query, max_results, timeout),
    {
      name: "web_search",
      description:
        "Search the public web and return compact result titles, URLs, and snippets.\n\n" +
        "Args:\n  query: Search query.\n  max_results: Maximum number of results.\n" +
        "  timeout: Network timeout in seconds.",
      schema: z.object({
        query: z.string(),
        max_results: z.number().default(5),
        timeout: z.number().default(10.0),
      }),
    },
  );
  return webSearch as unknown as StructuredToolInterface;
}

/** Cap on the search-results HTML we buffer (a result page is well under this). */
const MAX_SEARCH_BYTES = 2 * 1024 * 1024;

/**
 * Read a fetch Response body as text, stopping once `maxBytes` is buffered.
 *
 * `response.text()` buffers the entire body with no ceiling, so a hostile or
 * misbehaving endpoint could exhaust memory. We stream the reader and abort
 * once we have enough to parse the first page of results.
 */
async function readCapped(response: Response, maxBytes: number): Promise<string> {
  const reader = response.body?.getReader();
  if (!reader) return response.text();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value) {
        chunks.push(value);
        total += value.length;
        if (total >= maxBytes) break;
      }
    }
  } finally {
    // Release the stream so the underlying socket can close promptly.
    await reader.cancel().catch(() => {});
  }
  const merged = new Uint8Array(Math.min(total, maxBytes));
  let offset = 0;
  for (const chunk of chunks) {
    if (offset >= merged.length) break;
    const slice = chunk.subarray(0, merged.length - offset);
    merged.set(slice, offset);
    offset += slice.length;
  }
  return new TextDecoder().decode(merged);
}

export async function searchWeb(query: string, maxResults = 5, timeout = 10.0): Promise<string> {
  const q = query.trim();
  if (!q) return "web_search requires a non-empty query.";
  const limit = Math.max(1, Math.min(Math.trunc(maxResults || 5), 10));
  const url = "https://duckduckgo.com/html/?" + new URLSearchParams({ q }).toString();

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.max(1.0, timeout) * 1000);
  let body: string;
  try {
    const response = await fetch(url, {
      headers: { "User-Agent": "Mozilla/5.0 Sarma/0.1 (compatible; local research agent)" },
      signal: controller.signal,
    });
    body = await readCapped(response, MAX_SEARCH_BYTES);
  } catch (exc) {
    return `web_search failed: ${exc instanceof Error ? exc.message : String(exc)}`;
  } finally {
    clearTimeout(timer);
  }

  const results = parseDuckduckgoHtml(body, limit);
  if (results.length === 0) return "web_search found no results.";
  const lines = ["Web search results:"];
  results.forEach((item, index) => {
    lines.push(`\n[${index + 1}] ${item.title}\nURL: ${item.url}\n${item.snippet}`);
  });
  return lines.join("\n");
}

function parseDuckduckgoHtml(body: string, limit: number): SearchResult[] {
  const results: SearchResult[] = [];
  const blockRe = /<div[^>]+class="result[^"]*"[^>]*>([\s\S]*?)<\/div>\s*<\/div>/gi;
  let blockMatch: RegExpExecArray | null;
  while ((blockMatch = blockRe.exec(body)) !== null) {
    const block = blockMatch[1]!;
    const titleMatch = /<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/i.exec(block);
    if (!titleMatch) continue;
    const snippetMatch = /<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)<\/a>/i.exec(block);
    const result: SearchResult = {
      title: cleanHtml(titleMatch[2]!),
      url: cleanUrl(titleMatch[1]!),
      snippet: snippetMatch ? cleanHtml(snippetMatch[1]!) : "",
    };
    if (result.title && result.url) results.push(result);
    if (results.length >= limit) break;
  }
  return results;
}

function unescapeHtml(value: string): string {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#x2F;/gi, "/")
    .replace(/&nbsp;/g, " ");
}

function cleanHtml(value: string): string {
  const text = unescapeHtml(value.replace(/<[^>]+>/g, " "));
  return text.split(/\s+/).filter(Boolean).join(" ");
}

function cleanUrl(value: string): string {
  const url = unescapeHtml(value);
  try {
    const parsed = new URL(url, "https://duckduckgo.com");
    const uddg = parsed.searchParams.get("uddg");
    if (uddg) return uddg;
    return url.startsWith("//") ? `https:${url}` : url;
  } catch {
    return url;
  }
}
