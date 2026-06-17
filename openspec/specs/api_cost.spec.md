---
domain: api
action: api_cost
version: 1
---

## input

```json
{}
```

## success

```json
{
  "total_usd": "float >= 0",
  "calls": "integer >= 0"
}
```

## error

```json
[
  {"case": "db file missing", "expect": "returns {total_usd: 0.0, calls: 0}"}
]
```

## examples

```json
[
  {
    "input": {},
    "output": {"total_usd": 0.000036, "calls": 3}
  },
  {
    "input": "db not yet created",
    "output": {"total_usd": 0.0, "calls": 0}
  }
]
```
