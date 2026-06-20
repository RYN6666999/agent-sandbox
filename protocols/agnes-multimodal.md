# 協議：Agnes 多模態 — Agnes Multimodal Protocol

> 讓 AgentOS 內外角色可以透過統一端點呼叫 Agnes 的看圖、產圖、產影片能力。

---

## 角色

| 角色 | 職責 |
|------|------|
| **請求者** | 提供圖片 / prompt，指定任務類型 |
| **AgentOS** | 透過 litellm 呼叫 Agnes API，回傳結果 |

---

## API

### 看圖 — POST /vision/analyze

```json
// Request (二選一)
{"image_url": "https://...", "prompt": "Describe this image"}
{"image_base64": "data:image/jpeg;base64,...", "prompt": "Read the text"}

// Response
{"analysis": "A red apple on a wooden table.", "model": "openai/agnes-2.0-flash"}
```

### 產圖 — POST /image/generate

```json
// Request
{"prompt": "a cute cat wearing a hat", "size": "1024x1024", "n": 1}

// Response
{"url": "https://apihub.agnes-ai.com/...", "prompt": "a cute cat wearing a hat", "model": "openai/agnes-image-2.1-flash"}
```

### 產影片 — POST /video/generate (非同步)

```json
// Request
{"prompt": "a flying eagle over mountains"}

// Response
{"task_id": "vtask_abc123", "status": "submitted", "prompt": "a flying eagle over mountains"}
```

### 查影片狀態 — GET /video/status/{task_id}

```
GET /video/status/vtask_abc123

// Response (processing)
{"status": "processing", "task_id": "vtask_abc123"}

// Response (completed)
{"status": "completed", "url": "https://...", "task_id": "vtask_abc123"}
```

---

## 技術實作

| 層 | 檔案 | 說明 |
|----|------|------|
| 核心 | `orchestrator/agnes.py` | analyze_image / generate_image / generate_video / get_video_status |
| CLI | `scripts/agnes-analyze.py` | 看圖 CLI wrapper |
| CLI | `scripts/agnes-image.py` | 產圖 CLI wrapper |
| CLI | `scripts/agnes-video.py` | 產影片 CLI wrapper（支援 --wait blocking） |
| Registry | `data/settings.json` | executors.agnes-* 三項註冊 |
| API | `api/main.py` | 4 端點 (analyze / image / video / video-status) |
| 測試 | `tests/test_agnes.py` | 20 項測試（mock litellm，不發真實 API） |

### 技術細節

- 使用 litellm 統一呼叫 Agnes API（api_base: `https://apihub.agnes-ai.com/v1`）
- 看圖：agnes-2.0-flash，支援 `image_url`（公開 URL）和 `image_base64` 兩種輸入
- 產圖：agnes-image-2.1-flash，透過 `litellm.image_generation`
- 產影片：agnes-video-v2.0，非同步提交，回傳 task_id
- 影片狀態輪詢：透過 `GET /video/status/{task_id}` 查進度

---

## 非同步影片流程

```
請求者                    AgentOS                           Agnes API
  │                         │                                  │
  │ POST /video/generate     │                                  │
  │────────────────────────→│                                  │
  │                         │── litellm.image_generation ─────→│
  │                         │← {task_id: "vtask_xxx"} ────────│
  │← {task_id, status:"submitted"}                             │
  │                         │                                  │
  │ GET /video/status/vtask_xxx                                 │
  │────────────────────────→│                                  │
  │                         │── GET /video/status/vtask_xxx ──→│
  │                         │← {status:"processing"} ──────────│
  │← {status:"processing"}  │                                  │
  │                         │         ...polling...            │
  │ GET /video/status/vtask_xxx                                 │
  │────────────────────────→│                                  │
  │                         │── GET /video/status/vtask_xxx ──→│
  │                         │← {status:"completed", url:"..."} │
  │← {status:"completed", url:"..."}                           │
```

---

## 錯誤處理

| 情境 | HTTP | Response |
|------|------|----------|
| 成功 | 200 | 正常結果 |
| 參數缺漏 | 200 | `{..., "error": "..."}` |
| litellm 拋錯 | 200 | `{..., "error": "..."}` |
| video task 不存在 | 200 | `{status:"error", error:"..."}` |
| 網路逾時 | 200 | `{..., "error": "timeout"}` |

---

## 紅線

- 不改 `checker.py` / `decision_log.py` / `safety.py` / `clarify.py`
- 不改 `model_registry.py` 既有定義
- 所有 Agnes API 呼叫 mock 測試，不發真實請求
- API key 只從環境變數讀取（不寫死、不紀錄）