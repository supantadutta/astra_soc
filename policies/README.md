# Policies

`response.rego` is the OPA-native response-action policy, equivalent to the
built-in Python engine (`apps/api/astrasoc/services/policy/`). The active policy
is stored as `SystemSetting['response_policy']` and is editable via the API.

See [../docs/SECURITY.md](../docs/SECURITY.md).
