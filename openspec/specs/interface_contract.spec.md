---
domain: core
action: interface_contract
version: 1
---

## input

```json
{
  "producer": "string (dept name)",
  "consumer": "string (dept name)",
  "output_schema": "object (JSON schema)",
  "version": "string semver"
}
```

## success

```json
{
  "producer": "backend",
  "consumer": "frontend",
  "schema": {
    "type": "object",
    "properties": {
      "cashflow": {"type": "number"},
      "breakdown": {"type": "array"}
    },
    "required": ["cashflow"]
  },
  "version": "1.0.0"
}
```

## error

```json
[
  {"case": "producer is empty", "expect": "ValidationError"},
  {"case": "consumer is empty", "expect": "ValidationError"},
  {"case": "schema is not a dict", "expect": "ValidationError"},
  {"case": "producer equals consumer", "expect": "ValidationError"}
]
```

## examples

```json
[
  {
    "input": {
      "producer": "backend",
      "consumer": "frontend",
      "schema": {"type": "object", "properties": {"result": {"type": "string"}}},
      "version": "1.0.0"
    },
    "output": "valid InterfaceContract"
  },
  {
    "input": {"producer": "backend", "consumer": "backend", "schema": {}, "version": "1.0.0"},
    "output": "ValidationError: producer and consumer must differ"
  }
]
```
