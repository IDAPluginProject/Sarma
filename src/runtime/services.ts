/** Runtime services passed into LangChain/LangGraph agent builders. */

import { MemorySaver, InMemoryStore } from "@langchain/langgraph";
import type { BaseCheckpointSaver } from "@langchain/langgraph";

/**
 * Session-owned LangChain runtime services.
 *
 * Sarma's durable conversation history remains in the Store. These services
 * are scoped to the live runtime and are recreated on runtime restart.
 */
export class AgentRuntimeServices {
  readonly checkpointer: BaseCheckpointSaver;
  readonly store: InMemoryStore;
  readonly cache: unknown | null;

  constructor(
    checkpointer: BaseCheckpointSaver,
    store: InMemoryStore,
    cache: unknown | null = null,
  ) {
    this.checkpointer = checkpointer;
    this.store = store;
    this.cache = cache;
  }

  static create(): AgentRuntimeServices {
    return new AgentRuntimeServices(
      new MemorySaver(),
      new InMemoryStore(),
      // Cache is intentionally disabled until target-binary identity and
      // mutable IDA state are part of cache keys.
      null,
    );
  }

  /** Options passed to a compiled graph's invoke/stream config. */
  compileKwargs(): { checkpointer: BaseCheckpointSaver; store: InMemoryStore; cache?: unknown } {
    const kwargs: { checkpointer: BaseCheckpointSaver; store: InMemoryStore; cache?: unknown } = {
      checkpointer: this.checkpointer,
      store: this.store,
    };
    if (this.cache !== null) kwargs.cache = this.cache;
    return kwargs;
  }

  /** Options passed to `createAgent` (checkpointer + store + optional cache). */
  createAgentKwargs(): { checkpointer: BaseCheckpointSaver; store: InMemoryStore; cache?: unknown } {
    return this.compileKwargs();
  }
}
