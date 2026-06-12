import { expect, test } from "bun:test";
import { StateGraph, START, END, Command, MemorySaver } from "@langchain/langgraph";
import { createAgent, todoListMiddleware } from "langchain";
import { tool } from "@langchain/core/tools";

// Phase 0 smoke test: confirm the LangChain.js / LangGraph.js toolchain
// resolves and the core symbols Sarma's audit engine depends on exist.
test("core langchain.ts symbols are importable", () => {
  expect(typeof StateGraph).toBe("function");
  expect(typeof Command).toBe("function");
  expect(typeof createAgent).toBe("function");
  expect(typeof tool).toBe("function");
  expect(typeof todoListMiddleware).toBe("function");
  expect(START).toBeDefined();
  expect(END).toBeDefined();
  expect(typeof MemorySaver).toBe("function");
});
