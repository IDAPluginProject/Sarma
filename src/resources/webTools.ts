/** Built-in web search and URL fetch tools. */

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

/** Build the built-in LangChain URL fetch tool. */
export function buildFetchUrlTool(): StructuredToolInterface {
  const fetchUrl = tool(
    async ({
      url,
      max_chars = 12000,
      timeout = 10.0,
      include_links = true,
    }: {
      url: string;
      max_chars?: number;
      timeout?: number;
      include_links?: boolean;
    }): Promise<string> => fetchUrlContent({ url, maxChars: max_chars, timeout, includeLinks: include_links }),
    {
      name: "fetch_url",
      description:
        "Fetch an HTTP/HTTPS URL and return readable page content. Use this after web_search " +
        "when a result URL needs page text, not just title and snippet.\n\n" +
        "Args:\n  url: HTTP or HTTPS URL to fetch.\n  max_chars: Maximum response text characters.\n" +
        "  timeout: Network timeout in seconds.\n  include_links: Include extracted page links.",
      schema: z.object({
        url: z.string(),
        max_chars: z.number().default(12000),
        timeout: z.number().default(10.0),
        include_links: z.boolean().default(true),
      }),
    },
  );
  return fetchUrl as unknown as StructuredToolInterface;
}

/** Cap on the search-results HTML we buffer (a result page is well under this). */
const MAX_SEARCH_BYTES = 2 * 1024 * 1024;
const MAX_FETCH_BYTES = 4 * 1024 * 1024;
const MAX_FETCH_CHARS = 50000;

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
    if (!response.ok) return `web_search failed: HTTP ${response.status} ${response.statusText}`.trim();
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

export interface FetchUrlOptions {
  url: string;
  maxChars?: number;
  timeout?: number;
  includeLinks?: boolean;
}

export async function fetchUrlContent(options: FetchUrlOptions): Promise<string> {
  const target = options.url.trim();
  if (!target) return "fetch_url requires a non-empty url.";

  let parsed: URL;
  try {
    parsed = new URL(target);
  } catch (exc) {
    return `fetch_url invalid url: ${exc instanceof Error ? exc.message : String(exc)}`;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return "fetch_url invalid url: scheme must be http or https.";
  }

  const maxChars = Math.max(500, Math.min(Math.trunc(options.maxChars || 12000), MAX_FETCH_CHARS));
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.max(1.0, options.timeout ?? 10.0) * 1000);
  let response: Response;
  let body: string;
  try {
    response = await fetch(parsed, {
      headers: {
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
        "User-Agent": "Mozilla/5.0 Sarma/0.1 (compatible; local research agent)",
      },
      signal: controller.signal,
    });
    body = await readCapped(response, MAX_FETCH_BYTES);
  } catch (exc) {
    return `fetch_url failed: ${exc instanceof Error ? exc.message : String(exc)}`;
  } finally {
    clearTimeout(timer);
  }

  const contentType = response.headers.get("content-type") ?? "";
  const isText = isTextContentType(contentType);
  const statusLine = `fetch_url ${response.url}\nstatus=${response.status} ${response.statusText}`.trimEnd();
  const headers = [
    statusLine,
    `content-type=${contentType || "unknown"}`,
  ];
  if (!isText) {
    return [...headers, "", "Response is not a text document; body omitted."].join("\n");
  }

  const page = extractReadablePage(body, response.url, contentType, options.includeLinks ?? true);
  const text = truncateText(page.text, maxChars);
  const out = [...headers];
  if (page.title) out.push(`title=${page.title}`);
  out.push("", text || "[no readable text extracted]");
  if (page.links.length > 0) {
    out.push("", "Links:");
    page.links.slice(0, 20).forEach((link, index) => {
      out.push(`[${index + 1}] ${link.text || link.url}\nURL: ${link.url}`);
    });
  }
  return out.join("\n");
}

function parseDuckduckgoHtml(body: string, limit: number): SearchResult[] {
  const results: SearchResult[] = [];
  const blockRe = /<div[^>]+class="result[^"]*"[^>]*>([\s\S]*?)<\/div>\s*<\/div>/gi;
  let blockMatch: RegExpExecArray | null;
  while ((blockMatch = blockRe.exec(body)) !== null) {
    const block = blockMatch[1]!;
    const titleMatch = /<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/i.exec(block);
    if (!titleMatch) continue;
    const snippetMatch = /<(?:a|div)[^>]+class="[^"]*result__snippet[^"]*"[^>]*>([\s\S]*?)<\/(?:a|div)>/i.exec(block);
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

function isTextContentType(contentType: string): boolean {
  const lower = contentType.toLowerCase();
  return (
    lower === "" ||
    lower.startsWith("text/") ||
    lower.includes("html") ||
    lower.includes("json") ||
    lower.includes("xml") ||
    lower.includes("javascript") ||
    lower.includes("typescript")
  );
}

interface ExtractedLink {
  text: string;
  url: string;
}

interface ReadablePage {
  title: string;
  text: string;
  links: ExtractedLink[];
}

function extractReadablePage(body: string, baseUrl: string, contentType: string, includeLinks: boolean): ReadablePage {
  const isHtml = contentType.toLowerCase().includes("html") || /<html[\s>]/i.test(body) || /<body[\s>]/i.test(body);
  if (!isHtml) {
    return { title: "", text: cleanPlainText(body), links: [] };
  }

  const title = cleanHtml(/<title[^>]*>([\s\S]*?)<\/title>/i.exec(body)?.[1] ?? "");
  const links = includeLinks ? extractLinks(body, baseUrl) : [];
  const text = htmlToReadableText(body);
  return { title, text, links };
}

function htmlToReadableText(html: string): string {
  let text = html
    .replace(/<head[\s\S]*?<\/head>/gi, " ")
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<noscript[\s\S]*?<\/noscript>/gi, " ")
    .replace(/<svg[\s\S]*?<\/svg>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/<(br|hr)\b[^>]*>/gi, "\n")
    .replace(/<\/(p|div|section|article|header|footer|main|aside|nav|li|ul|ol|h[1-6]|tr|table|blockquote)>/gi, "\n")
    .replace(/<[^>]+>/g, " ");
  text = unescapeHtml(text);
  return cleanPlainText(text);
}

function cleanPlainText(value: string): string {
  return value
    .replace(/\r/g, "")
    .split("\n")
    .map((line) => line.split(/[ \t\f\v]+/).filter(Boolean).join(" "))
    .join("\n")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function extractLinks(html: string, baseUrl: string): ExtractedLink[] {
  const links: ExtractedLink[] = [];
  const seen = new Set<string>();
  const linkRe = /<a\b[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/gi;
  let match: RegExpExecArray | null;
  while ((match = linkRe.exec(html)) !== null) {
    const rawHref = unescapeHtml(match[1] ?? "").trim();
    if (!rawHref || rawHref.startsWith("#") || /^javascript:/i.test(rawHref) || /^mailto:/i.test(rawHref)) continue;
    let url: string;
    try {
      url = new URL(rawHref, baseUrl).toString();
    } catch {
      continue;
    }
    if (seen.has(url)) continue;
    seen.add(url);
    links.push({ text: cleanHtml(match[2] ?? ""), url });
    if (links.length >= 50) break;
  }
  return links;
}

function truncateText(value: string, maxChars: number): string {
  if (value.length <= maxChars) return value;
  return value.slice(0, maxChars).trimEnd() + "\n\n[... truncated by fetch_url max_chars ...]";
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
