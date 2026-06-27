# Lessons Learned

> Append-only failure log. Recorded automatically by the heartbeat/loop system
> when a task escalates or hits a known anti-pattern.
>
> Each entry documents what failed, why, and what to do instead.
> This complements the brain (which stores successful patterns) by preserving
> negative experiences so they are not repeated.

## Format

```markdown
- **date**: YYYY-MM-DD
  **task**: <one-line description>
  **lesson**: <what went wrong>
  **fix**: <what to do instead>
  **source**: <component that reported this>
```

---

## Entries

*No failures recorded yet.*
