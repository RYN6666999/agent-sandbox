import { describe, it, expect, beforeEach } from "vitest";
import { useStore } from "../store";

function reset() {
  useStore.setState({
    tasks: [],
    activeTaskId: null,
    sidebarOpen: true,
    roundsOpen: false,
    settingsOpen: false,
    cost: { total_usd: 0, calls: 0 },
  });
}

describe("store", () => {
  beforeEach(reset);

  it("newTask creates task and sets it active", () => {
    const id = useStore.getState().newTask();
    const t = useStore.getState().activeTask();
    expect(t?.id).toBe(id);
    expect(t?.status).toBe("idle");
    expect(t?.title).toBe("新任務");
  });

  it("updateTask patches only target", () => {
    const id = useStore.getState().newTask();
    useStore.getState().updateTask(id, { status: "running", title: "merge sort" });
    const t = useStore.getState().activeTask();
    expect(t?.status).toBe("running");
    expect(t?.title).toBe("merge sort");
    expect(t?.output).toBe(""); // untouched field stays
  });

  it("deleteTask removes task and switches active to next", () => {
    const id1 = useStore.getState().newTask();
    const id2 = useStore.getState().newTask();
    useStore.getState().deleteTask(id2); // id2 is active
    expect(useStore.getState().activeTaskId).toBe(id1);
    expect(useStore.getState().tasks).toHaveLength(1);
  });

  it("deleteTask last → activeTaskId null", () => {
    const id = useStore.getState().newTask();
    useStore.getState().deleteTask(id);
    expect(useStore.getState().activeTaskId).toBeNull();
  });

  it("updateTask appends messages immutably", () => {
    const id = useStore.getState().newTask();
    const before = useStore.getState().activeTask()!.messages;
    useStore.getState().updateTask(id, {
      messages: [...before, { role: "user", text: "hello" }],
    });
    expect(useStore.getState().activeTask()?.messages).toHaveLength(1);
    expect(before).toHaveLength(0); // original untouched
  });
});
