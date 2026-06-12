import { expect, test, describe } from "bun:test";
import { createRawCtrlCExitHandler } from "@/tui/index";

describe("TUI entrypoint", () => {
  test("raw Ctrl+C handler exits only on the second press", () => {
    let exits = 0;
    const ctrlC = createRawCtrlCExitHandler(() => exits++);

    expect(ctrlC.handleInput("x")).toBe(false);
    expect(ctrlC.handleInput("\u0003")).toBe(true);
    expect(exits).toBe(0);
    expect(ctrlC.handleInput("\u0003")).toBe(true);
    expect(exits).toBe(1);

    ctrlC.dispose();
  });

  test("raw Ctrl+C handler disarms after the configured window", async () => {
    let exits = 0;
    const ctrlC = createRawCtrlCExitHandler(() => exits++, 5);

    expect(ctrlC.handleInput("\u0003")).toBe(true);
    await new Promise((resolve) => setTimeout(resolve, 15));
    expect(ctrlC.handleInput("\u0003")).toBe(true);
    expect(exits).toBe(0);

    ctrlC.dispose();
  });
});
