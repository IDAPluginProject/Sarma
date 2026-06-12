/** Shared enums for the Sarma IDE application. */

/** Type discriminator for StreamEvent instances. */
export const StreamEventType = {
  TOKEN: "token",
  TOOL_START: "tool_start",
  TOOL_RESULT: "tool_result",
  TOOL_ERROR: "tool_error",
  RUN_STARTED: "run_started",
  RUN_COMPLETED: "run_completed",
  RUN_FAILED: "run_failed",
  SKILL_TRIGGERED: "skill_triggered",
  STAGE_START: "stage_start",
  STAGE_COMPLETE: "stage_complete",
  STAGE_ERROR: "stage_error",
  SUBAGENT_START: "subagent_start",
  SUBAGENT_COMPLETE: "subagent_complete",
  SUBAGENT_ERROR: "subagent_error",
  CUSTOM_PROGRESS: "custom_progress",
} as const;

export type StreamEventType = (typeof StreamEventType)[keyof typeof StreamEventType];
