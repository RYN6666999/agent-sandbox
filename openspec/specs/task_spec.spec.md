---
domain: core
action: task_spec
version: 1
---

## input

```json
{
  "why": "string, non-empty",
  "io_example": {
    "input": "any",
    "expected_output": "any"
  },
  "taste": ["string"],
  "boundaries": ["string"]
}
```

## success

```json
{
  "why": "calculate monthly cash flow for a rental property",
  "io_example": {
    "input": "rent=30000, mortgage=18000, expenses=3000",
    "expected_output": "net_cashflow=9000"
  },
  "taste": ["should show breakdown by category", "must handle negative cashflow"],
  "boundaries": ["no tax calculation", "stop if input data is missing"]
}
```

## error

```json
[
  {"case": "why is empty string", "expect": "ValidationError"},
  {"case": "io_example missing expected_output", "expect": "ValidationError"},
  {"case": "taste is not a list", "expect": "ValidationError"},
  {"case": "boundaries is null", "expect": "ValidationError"}
]
```

## examples

```json
[
  {
    "input": {
      "why": "build a cashflow calculator",
      "io_example": {"input": "rent=30000", "expected_output": "cashflow=9000"},
      "taste": ["show breakdown"],
      "boundaries": ["no tax"]
    },
    "output": "valid TaskSpec"
  },
  {
    "input": {"why": "", "io_example": {}, "taste": [], "boundaries": []},
    "output": "ValidationError: why must not be empty"
  }
]
```
