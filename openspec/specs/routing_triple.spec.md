---
domain: core
action: routing_triple
version: 1
---

## input

```json
{
  "model": "string (model alias)",
  "skills": ["string"],
  "mcp_tools": ["string"],
  "confidence": "float 0.0-1.0"
}
```

## success

```json
{
  "model": "gemini-flash",
  "skills": ["ponytail"],
  "mcp_tools": ["file", "execute"],
  "confidence": 0.9
}
```

## error

```json
[
  {"case": "model is empty", "expect": "ValidationError"},
  {"case": "confidence > 1.0", "expect": "ValidationError"},
  {"case": "confidence < 0.0", "expect": "ValidationError"},
  {"case": "skills is not a list", "expect": "ValidationError"}
]
```

## examples

```json
[
  {
    "input": {"model": "agnes", "skills": ["ponytail", "caveman"], "mcp_tools": [], "confidence": 0.7},
    "output": "valid RoutingTriple"
  },
  {
    "input": {"model": "", "skills": [], "mcp_tools": [], "confidence": 0.5},
    "output": "ValidationError: model must not be empty"
  },
  {
    "input": {"model": "agnes", "skills": [], "mcp_tools": [], "confidence": 1.5},
    "output": "ValidationError: confidence must be <= 1.0"
  }
]
```
