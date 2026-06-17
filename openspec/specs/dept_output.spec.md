---
domain: core
action: dept_output
version: 1
---

## input

```json
{
  "dept": "string (dept name)",
  "artifacts": ["object"],
  "status": "done | blocked",
  "contract_ref": "string (InterfaceContract id)"
}
```

## success

```json
{
  "dept": "backend",
  "artifacts": [{"type": "code", "path": "cashflow.py", "content": "..."}],
  "status": "done",
  "contract_ref": "backend->frontend@1.0.0"
}
```

## error

```json
[
  {"case": "dept is empty", "expect": "ValidationError"},
  {"case": "status is not done or blocked", "expect": "ValidationError"},
  {"case": "contract_ref is empty", "expect": "ValidationError"},
  {"case": "artifacts is not a list", "expect": "ValidationError"}
]
```

## examples

```json
[
  {
    "input": {
      "dept": "frontend",
      "artifacts": [{"type": "html", "content": "<div/>"}],
      "status": "done",
      "contract_ref": "backend->frontend@1.0.0"
    },
    "output": "valid DeptOutput"
  },
  {
    "input": {"dept": "frontend", "artifacts": [], "status": "shipped", "contract_ref": "x"},
    "output": "ValidationError: status must be done or blocked"
  }
]
```
