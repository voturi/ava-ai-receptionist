# AI Receptionist SaaS

## Tooling smoke test

Run a quick tool router smoke test (requires DB access configured):

```bash
python -m backend.scripts.smoke_tools \
  --business-id <uuid> \
  --customer-phone <phone> \
  --topic cancellation
```
