export const PROVIDERS = {
  genspark: {
    url: "https://www.genspark.ai/agents?type=ai_chat",
    inputSelector: "textarea.search-input",
    submitSelector: "textarea.search-input",
    responseTimeoutMs: 120_000,
  },
  gemini: {
    url: "https://gemini.google.com/",
    inputSelector: 'div[aria-label*="提示詞"], textarea[placeholder*="Gemini"]',
    submitSelector: 'div[aria-label*="提示詞"], textarea[placeholder*="Gemini"]',
    responseTimeoutMs: 60_000,
  },
};