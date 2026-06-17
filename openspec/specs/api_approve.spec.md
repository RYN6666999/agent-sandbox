---
domain: api
action: api_approve
version: 1
---

## input

```json
{
  "session_id": "string",
  "spec": {
    "why": "string",
    "io": "string (input → expected_output)",
    "taste": "string (comma-separated)",
    "boundary": "string (comma-separated)",
    "stop_metric": "string",
    "max_rounds": "string (digit)"
  }
}
```

## success

```json
{
  "ok": true,
  "session_id": "string"
}
```

## error

```json
[
  {"case": "session_id not found", "expect": "404"},
  {"case": "session_id missing", "expect": "422"}
]
```

## examples

```json
[
  {
    "input": {
      "session_id": "a1b2c3d4",
      "spec": {"why": "build cashflow", "io": "rent=30000 → cashflow=9000", "taste": "show breakdown", "boundary": "no tax", "stop_metric": "contains cashflow figure", "max_rounds": "5"}
    },
    "output": {"ok": true, "session_id": "a1b2c3d4"}
  },
  {
    "input": {"session_id": "nonexistent", "spec": {}},
    "output": "404 session not found"
  }
]
```
