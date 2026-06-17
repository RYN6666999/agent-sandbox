---
domain: api
action: api_submit
version: 1
---

## input

```json
{
  "task": "string, non-empty"
}
```

## success

```json
{
  "session_id": "string (8-char hex)",
  "questions": [
    {"key": "string", "q": "string"}
  ]
}
```

## error

```json
[
  {"case": "task is empty string", "expect": "422"},
  {"case": "task field missing", "expect": "422"}
]
```

## examples

```json
[
  {
    "input": {"task": "build cashflow calculator"},
    "output": {"session_id": "a1b2c3d4", "questions": [{"key": "why", "q": "為什麼要做？"}]}
  },
  {
    "input": {"task": ""},
    "output": "422 Unprocessable Entity"
  }
]
```
