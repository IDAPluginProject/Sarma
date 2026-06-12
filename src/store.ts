/** Persistent storage for Sarma CLI sessions (per-workspace ./.sarma/db.sqlite). */

import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { randomUUID } from "node:crypto";
import { Database } from "bun:sqlite";
import * as paths from "@/paths";

const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    model_name  TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'idle',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    turn_id         TEXT NOT NULL DEFAULT '',
    role            TEXT NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    tool_name       TEXT,
    reasoning       TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS tool_executions (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    turn_id         TEXT NOT NULL DEFAULT '',
    server_name     TEXT NOT NULL DEFAULT '',
    tool_name       TEXT NOT NULL DEFAULT '',
    args_json       TEXT NOT NULL DEFAULT '',
    result_summary  TEXT,
    status          TEXT NOT NULL DEFAULT 'started',
    error_text      TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS memory_artifacts (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'structured_context',
    content         TEXT NOT NULL DEFAULT '',
    source_count    INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_tools_conv ON tool_executions(conversation_id);
CREATE INDEX IF NOT EXISTS idx_memory_conv ON memory_artifacts(conversation_id);
`;

export const SCHEMA_VERSION = 1;

function nowIso(): string {
  return new Date().toISOString();
}

function uid(): string {
  return randomUUID().replace(/-/g, "").slice(0, 12);
}

export interface ConversationRow {
  id: string;
  title: string;
  model_name: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface MessageRow {
  id: string;
  conversation_id: string;
  turn_id: string;
  role: string;
  content: string;
  tool_name: string | null;
  reasoning: string | null;
  created_at: string;
}

export interface MessageLike {
  id?: string;
  turn_id?: string;
  role?: string;
  content?: string;
  tool_name?: string | null;
  reasoning_content?: string | null;
  created_at?: string;
}

/** SQLite persistence for CLI audit sessions. */
export class Store {
  private static readonly CONVERSATION_UPDATE_FIELDS = new Set([
    "title",
    "model_name",
    "status",
    "updated_at",
  ]);

  private readonly conn: Database;

  constructor() {
    const db = paths.dbPath();
    mkdirSync(dirname(db), { recursive: true });
    this.conn = new Database(db);
    this.conn.exec("PRAGMA journal_mode=WAL");
    this.conn.exec("PRAGMA foreign_keys=ON");
    this.migrateSchema();
  }

  private migrateSchema(): void {
    const row = this.conn.query("PRAGMA user_version").get() as { user_version: number };
    const current = Number(row.user_version);
    if (current === 0) {
      this.conn.exec(SCHEMA_SQL);
      this.conn.exec(`PRAGMA user_version=${SCHEMA_VERSION}`);
      return;
    }
    if (current > SCHEMA_VERSION) {
      throw new Error(
        `Unsupported database schema version ${current}; ` +
          `this Sarma build supports up to ${SCHEMA_VERSION}.`,
      );
    }
    if (current < SCHEMA_VERSION) {
      // Version 1 is the baseline schema; forward migrations go here.
      this.conn.exec(`PRAGMA user_version=${SCHEMA_VERSION}`);
    }
  }

  createConversation(title = "", modelName = ""): string {
    const cid = uid();
    const now = nowIso();
    this.conn
      .query(
        "INSERT INTO conversations (id, title, model_name, status, created_at, updated_at) " +
          "VALUES (?, ?, ?, 'idle', ?, ?)",
      )
      .run(cid, title, modelName, now, now);
    return cid;
  }

  updateConversation(cid: string, fields: Record<string, string>): void {
    const kw: Record<string, string> = { ...fields, updated_at: nowIso() };
    const invalid = Object.keys(kw).filter((k) => !Store.CONVERSATION_UPDATE_FIELDS.has(k));
    if (invalid.length) {
      throw new Error(`Invalid conversation update field(s): ${invalid.sort().join(", ")}`);
    }
    const keys = Object.keys(kw);
    const sets = keys.map((k) => `${k}=?`).join(", ");
    this.conn.query(`UPDATE conversations SET ${sets} WHERE id=?`).run(...keys.map((k) => kw[k]!), cid);
  }

  listConversations(limit = 20): ConversationRow[] {
    return this.conn
      .query("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?")
      .all(limit) as ConversationRow[];
  }

  getConversation(cid: string): ConversationRow | null {
    return (this.conn.query("SELECT * FROM conversations WHERE id=?").get(cid) as ConversationRow) ?? null;
  }

  saveMessage(
    conversationId: string,
    turnId: string,
    role: string,
    content: string,
    toolName: string | null = null,
    reasoning: string | null = null,
  ): string {
    const mid = uid();
    this.conn
      .query(
        "INSERT INTO messages (id, conversation_id, turn_id, role, content, tool_name, reasoning, created_at) " +
          "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
      )
      .run(mid, conversationId, turnId, role, content, toolName, reasoning, nowIso());
    return mid;
  }

  /** Replace persisted replay history after context compaction. */
  replaceMessages(conversationId: string, messages: MessageLike[]): void {
    const now = nowIso();
    const tx = this.conn.transaction((msgs: MessageLike[]) => {
      this.conn.query("DELETE FROM messages WHERE conversation_id=?").run(conversationId);
      const stmt = this.conn.query(
        "INSERT INTO messages " +
          "(id, conversation_id, turn_id, role, content, tool_name, reasoning, created_at) " +
          "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
      );
      for (const m of msgs) {
        stmt.run(
          m.id || uid(),
          conversationId,
          m.turn_id || "",
          m.role || "",
          m.content || "",
          m.tool_name ?? null,
          m.reasoning_content ?? null,
          m.created_at || now,
        );
      }
    });
    tx(messages);
  }

  loadMessages(conversationId: string): MessageRow[] {
    return this.conn
      .query("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at")
      .all(conversationId) as MessageRow[];
  }

  saveMemoryArtifact(
    conversationId: string,
    content: string,
    kind = "structured_context",
    sourceCount = 0,
  ): string {
    const mid = uid();
    this.conn
      .query(
        "INSERT INTO memory_artifacts " +
          "(id, conversation_id, kind, content, source_count, created_at) " +
          "VALUES (?, ?, ?, ?, ?, ?)",
      )
      .run(mid, conversationId, kind, content, Math.trunc(sourceCount), nowIso());
    return mid;
  }

  loadMemoryArtifacts(conversationId: string, limit = 20): Record<string, unknown>[] {
    return this.conn
      .query(
        "SELECT * FROM memory_artifacts WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?",
      )
      .all(conversationId, limit) as Record<string, unknown>[];
  }

  saveToolExecution(
    conversationId: string,
    turnId: string,
    toolName: string,
    argsJson: string,
    serverName = "",
  ): string {
    const tid = uid();
    this.conn
      .query(
        "INSERT INTO tool_executions " +
          "(id, conversation_id, turn_id, server_name, tool_name, args_json, status, started_at) " +
          "VALUES (?, ?, ?, ?, ?, ?, 'started', ?)",
      )
      .run(tid, conversationId, turnId, serverName, toolName, argsJson, nowIso());
    return tid;
  }

  finishToolExecution(
    tid: string,
    status = "succeeded",
    resultSummary: string | null = null,
    errorText: string | null = null,
  ): void {
    this.conn
      .query(
        "UPDATE tool_executions SET status=?, result_summary=?, error_text=?, finished_at=? WHERE id=?",
      )
      .run(status, resultSummary, errorText, nowIso(), tid);
  }

  close(): void {
    this.conn.close();
  }
}
