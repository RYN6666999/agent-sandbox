# Headroom + AgentOS 整合 — BDD 場景

> 規範版本：v1.0  
> 對應實作：agentos-aris-bridge.py 第 3.b stage、agentos.json pipeline.compress、Caveman SKILL.md input compression  
> 驗證：待加入 pytest 測試

---

## Feature: Headroom Proxy Lifecycle

### Scenario: Bridge auto-starts proxy on launch

```
Given HEADROOM_AUTO_START is "1"
And no Headroom proxy is running on port 8787
When the bridge starts (main_loop)
Then the bridge spawns `headroom proxy --port 8787`
And the proxy health endpoint returns 200 within 10 seconds
And HEADROOM_PROXY_LAUNCHED is set to True
```

### Scenario: Bridge reuses already-running proxy

```
Given HEADROOM_AUTO_START is "1"
And a Headroom proxy is already running on port 8787
When the bridge starts (main_loop)
Then the bridge detects the running proxy via /health
And HEADROOM_PROXY_LAUNCHED is set to True
And no new proxy process is spawned
```

### Scenario: Bridge recovers dead proxy

```
Given HEADROOM_AUTO_START is "1"
And the proxy was running but has been killed
When the bridge's main loop reaches the 60th health tick
Then the bridge detects the proxy is unreachable
And the bridge spawns a new `headroom proxy --port 8787`
And the new proxy's health endpoint returns 200
```

### Scenario: Auto-start disabled

```
Given HEADROOM_AUTO_START is "0"
And no Headroom proxy is running
When the bridge starts (main_loop)
Then the bridge does NOT attempt to start the proxy
And HEADROOM_PROXY_LAUNCHED remains False
And _ensure_headroom_proxy() returns False
```

---

## Feature: Input Compression Pipeline Stage

### Scenario: Large JSON tool output is compressed

```
Given the bridge has processed a route "code" task
And _execute_by_route returns success=True
And the output size is 5000 bytes (> HEADROOM_MIN_COMPRESS_SIZE=2000)
When _compress_stage is called on the result
Then the output is sent to Headroom /v1/compress
And the compressed output replaces result["output"]
And result["_original_output"] contains the original text
And result["_headroom"]["tokens_saved"] > 0
And result["_headroom"]["tokens_before"] > result["_headroom"]["tokens_after"]
And the response context["headroom"] is populated
```

### Scenario: Small output passes through uncompressed

```
Given _execute_by_route returns success=True
And the output size is 500 bytes (< HEADROOM_MIN_COMPRESS_SIZE=2000)
When _compress_stage is called on the result
Then _compress_with_headroom returns {"skipped": True, "reason": "too_small"}
And the result["output"] is unchanged
And result["_headroom"] is not set
```

### Scenario: Failed execution skips compression

```
Given _execute_by_route returns success=False
And the output contains an error message
When _compress_stage is called on the result
Then _compress_stage returns the result immediately
And compression is not attempted
```

### Scenario: Content type routing

```
Given a route "code" task with JSON output > 2000 bytes
When _compress_stage calls _compress_with_headroom
Then the content_type hint is "json_code_search"

Given a route "research" task with text output > 2000 bytes
When _compress_stage calls _compress_with_headroom
Then the content_type hint is "web_search_results"

Given a route "read" task with source code output > 2000 bytes
When _compress_stage calls _compress_with_headroom
Then the content_type hint is "source_code_file"

Given a route "bash" task with shell output > 2000 bytes
When _compress_stage calls _compress_with_headroom
Then the content_type hint is "shell_output"
```

### Scenario: Compression performance on JSON

```
Given a JSON array with 50 entries (1861 tokens)
And the output is sent to /v1/compress
Then the compressed output is <= 928 tokens
And the compression ratio is <= 0.5
And the transform applied is "router:smart_crusher:*"
```

### Scenario: Proxy unreachable during compression

```
Given the Headroom proxy is not running
And _compress_with_headroom is called with text > 2000 bytes
When the HTTP request to /v1/compress fails
Then the function returns {"compressed": text, "skipped": True, "reason": "<error>"}
And the original uncompressed text is returned
And the bridge continues processing without error
```

---

## Feature: Headroom Learn (Failure Mining)

### Scenario: Failure tracking accumulates

```
Given HEADROOM_LEARN_ENABLED is "1"
And HEADROOM_LEARN_FAIL_THRESHOLD is 5
When a route execution fails (success=False)
Then _track_failure increments _learn_fail_count by 1
And the failure reason is logged

When 4 more failures occur (total = 5)
And _learn_fail_count >= HEADROOM_LEARN_FAIL_THRESHOLD
Then _headroom_learn_async is triggered
And `headroom learn --project ~ --target AGENTS.md --apply --agent auto` is spawned
And _learn_fail_count is reset to 0
```

### Scenario: Learn interval throttling

```
Given HEADROOM_LEARN_INTERVAL is 3600 seconds
And _learn_fail_count was reset 5 minutes ago
When a failure occurs (count = 5)
And now - _learn_last_run < HEADROOM_LEARN_INTERVAL
And _learn_fail_count < HEADROOM_LEARN_FAIL_THRESHOLD * 3
Then _headroom_learn_async is NOT triggered
And _learn_last_run is not updated
```

### Scenario: Learn forced on high failure rate

```
Given HEADROOM_LEARN_INTERVAL is 3600
And _learn_last_run was 10 minutes ago
When cumulative failures reach HEADROOM_LEARN_FAIL_THRESHOLD * 3 (15)
And now - _learn_last_run < HEADROOM_LEARN_INTERVAL
Then _headroom_learn_async IS triggered (overrides throttle)
And _learn_fail_count is reset to 0
```

### Scenario: Learn disabled

```
Given HEADROOM_LEARN_ENABLED is "0"
When a route execution fails
Then _track_failure returns immediately
And _learn_fail_count is not incremented
And headroom learn is never spawned
```

### Scenario: Gate denial triggers learning

```
Given a route execution succeeds initially
But the Gate scan blocks the result (dangerous pattern)
When process_entry evaluates gate_verdict = "deny"
And old_success was True but result["success"] is now False
Then _track_failure is called with the gate reason
And _learn_fail_count is incremented
```

---

## Feature: MCP Server Integration

### Scenario: headroom_compress tool available

```
Given the Scream Code MCP client is connected
When tools/list is called on the headroom MCP server
Then the response includes "headroom_compress" in the tools list
And headroom_compress accepts parameters: messages, model
```

### Scenario: headroom_retrieve tool available

```
Given the Scream Code MCP client is connected
When tools/list is called on the headroom MCP server
Then the response includes "headroom_retrieve" in the tools list
And headroom_retrieve accepts parameters: hash_key
```

### Scenario: headroom_stats tool available

```
Given the Scream Code MCP client is connected
When tools/list is called on the headroom MCP server
Then the response includes "headroom_stats" in the tools list
```

### Scenario: MCP server registered in scream-code config

```
Given the file ~/.scream-code/mcp.json exists
When it is parsed as JSON
Then mcpServers.headroom.command is "headroom"
And mcpServers.headroom.args includes "mcp", "serve"
And mcpServers.headroom.transport is "stdio"
```

---

## Feature: Pipeline Orchestration

### Scenario: Pipeline stages execute in order

```
Given an Aris channel entry is received
When process_entry processes it
Then the stages execute in this order:
  1. Route Classification
  2. Brain Context Lookup
  3. Execute
  3.b Headroom Compress
  4. Gate
  5. Log
  5.b Failure Learning (if failed)
And the response is written back to the channel
```

### Scenario: agentos.json declares the compress stage

```
Given the file agentos.json is parsed
Then pipeline.compress contains "headroom"
And pipeline.input contains "headroom"
And aris_bridge.pipeline_stages includes "headroom-compress"
And routes["compression"] includes "headroom"
```

### Scenario: Caveman skill references real Headroom

```
Given the file caveman-ponytail/SKILL.md is parsed
Then the "Input Compression" section title includes "Headroom (real engine)"
And the section describes the proxy URL as http://127.0.0.1:8787
And the section describes MCP tools headroom_compress and headroom_retrieve
And the heuristic fallback is marked as fallback
```

---

## Feature: CCR (Compress-Cache-Retrieve)

### Scenario: Compressed output includes CCR hash

```
Given a large output was compressed via /v1/compress
And the response includes ccr_hashes
When the bridge processes the response
Then result["_headroom"]["ccr_hash"] is populated
And the response context includes the ccr_hash
```

### Scenario: Agent retrieves original via headroom_retrieve

```
Given the agent received compressed output with ccr_hash "abc123"
When the agent calls headroom_retrieve with hash_key "abc123"
Then the MCP server returns the original uncompressed content
And the content matches the original output before compression
```

---

## 邊界條件

| 條件 | 預期行為 |
|------|---------|
| Output 正好 2000 bytes | 不壓縮（< 2000 的條件是 strict，2000 不觸發） |
| Proxy 在 compress 中途斷線 | 回傳 original，繼續 pipeline |
| 非 ASCII 內容（中文/日文） | 壓縮 ratio 不同但 function 不拋錯 |
| 空字串 output | 跳過壓縮 |
| route_key 不在 type_hints 中 | hint = ""，Headroom router 自動偵測 |
| _learn_fail_count 溢位 | Python int 無上限，安全 |
| 同時多個 entry 觸發 learn | 每個 subprocess 獨立，不阻塞 main_loop |
| MCP server 啟動失敗 | 僅影響 Scream agent 的 MCP 工具，不影響 bridge pipeline |