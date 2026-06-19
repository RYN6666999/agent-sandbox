import { create } from "zustand";

export type AppStatus = "idle" | "aligning" | "running" | "done" | "escalate" | "error";

export interface Question { key: string; q: string; }
export interface HistoryEntry { round: number; score: number; passed: boolean; feedback: string; }

export interface TaskSession {
  id: string;
  title: string;
  sessionId: string | null;
  status: AppStatus;
  questions: Question[];
  answers: Record<string, string>;
  output: string;
  history: HistoryEntry[];
  finalScore: number | null;
  logs: string[];
  messages: {
    role: "user" | "system";
    text: string;
    model?: string;
    overrideOption?: boolean;
    overrideUsed?: boolean;
    originalTask?: string;
  }[];
  createdAt: number;
}

interface AppState {
  tasks: TaskSession[];
  activeTaskId: string | null;
  sidebarOpen: boolean;
  roundsOpen: boolean;
  settingsOpen: boolean;
  cost: { total_usd: number; calls: number };

  setSidebarOpen: (open: boolean) => void;
  setRoundsOpen: (open: boolean) => void;
  setSettingsOpen: (open: boolean) => void;
  setCost: (c: { total_usd: number; calls: number }) => void;

  newTask: () => string;
  setActiveTask: (id: string) => void;
  deleteTask: (id: string) => void;
  updateTask: (id: string, patch: Partial<TaskSession>) => void;

  activeTask: () => TaskSession | null;
}

function makeTask(id: string): TaskSession {
  return {
    id,
    title: "新任務",
    sessionId: null,
    status: "idle",
    questions: [],
    answers: {},
    output: "",
    history: [],
    finalScore: null,
    logs: [],
    messages: [],
    createdAt: Date.now(),
  };
}

export const useStore = create<AppState>((set, get) => ({
  tasks: [],
  activeTaskId: null,
  sidebarOpen: true,
  roundsOpen: false,
  settingsOpen: false,
  cost: { total_usd: 0, calls: 0 },

  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  setRoundsOpen: (roundsOpen) => set({ roundsOpen }),
  setSettingsOpen: (settingsOpen) => set({ settingsOpen }),
  setCost: (cost) => set({ cost }),

  newTask: () => {
    const id = Math.random().toString(36).slice(2, 10);
    const task = makeTask(id);
    set((s) => ({ tasks: [task, ...s.tasks], activeTaskId: id }));
    return id;
  },

  setActiveTask: (id) => set({ activeTaskId: id }),

  deleteTask: (id) => set((s) => {
    const tasks = s.tasks.filter((t) => t.id !== id);
    const activeTaskId = s.activeTaskId === id ? (tasks[0]?.id ?? null) : s.activeTaskId;
    return { tasks, activeTaskId };
  }),

  updateTask: (id, patch) => set((s) => ({
    tasks: s.tasks.map((t) => t.id === id ? { ...t, ...patch } : t),
  })),

  activeTask: () => {
    const { tasks, activeTaskId } = get();
    return tasks.find((t) => t.id === activeTaskId) ?? null;
  },
}));
