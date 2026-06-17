---
domain: api
action: api_deliver
version: 1
---

## input

```json
{
  "session_id": "string",
  "accepted": "boolean",
  "feedback": "string (optional)"
}
```

## success

```json
{
  "ok": true,
  "accepted": "boolean"
}
```

## error

```json
[
  {"case": "session_id not found", "expect": "404"},
  {"case": "accepted field missing", "expect": "422"}
]
```

## examples

```json
[
  {
    "input": {"session_id": "a1b2c3d4", "accepted": true, "feedback": ""},
    "output": {"ok": true, "accepted": true}
  },
  {
    "input": {"session_id": "a1b2c3d4", "accepted": false, "feedback": "output was wrong"},
    "output": {"ok": true, "accepted": false}
  }
]
```
