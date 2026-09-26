# Kubernetes

Three options, all with the same shape: a horizontally scaled API (rolling
strategy), a horizontally scalable web tier, PostgreSQL, and an ingress that
routes `/api` to the API and everything else to the web tier.

## Helm (recommended)

Create the secret out of band (External Secrets, Vault Agent, sealed-secrets or
`kubectl`):

```bash
kubectl create namespace astrasoc
kubectl -n astrasoc create secret generic astrasoc-secrets \
  --from-literal=ASTRASOC_JWT_SECRET="$(openssl rand -base64 48)" \
  --from-literal=ASTRASOC_AUDIT_KEY="$(openssl rand -base64 48)" \
  --from-literal=POSTGRES_PASSWORD="$(openssl rand -hex 24)" \
  --from-literal=ASTRASOC_BOOTSTRAP_ADMIN_EMAIL=secops-admin@your-company.com \
  --from-literal=ASTRASOC_BOOTSTRAP_ADMIN_PASSWORD='<a strong password>'

helm install astrasoc infrastructure/helm/astrasoc -n astrasoc \
  --set secrets.existingSecret=astrasoc-secrets \
  --set ingress.host=soc.your-company.com \
  --set image.tag=0.2.0
```

Use a hex (URL-safe) `POSTGRES_PASSWORD`: the bundled database URL embeds it.

Key values (`values.yaml` documents them all):

| Value | Default | Notes |
|-------|---------|-------|
| `secrets.existingSecret` | `""` | Recommended. Otherwise pass `secrets.jwtSecret`, `secrets.auditKey`, … with `--set`. The chart **refuses to render** without secrets or with identical JWT/audit keys. |
| `postgresql.enabled` | `true` | Bundled single-instance PostgreSQL with a PVC, for pilots. For production, set `false` and provide `ASTRASOC_DATABASE_URL` for a managed, backed-up PostgreSQL. |
| `api.replicas` | `2` | Rolling updates (`maxUnavailable: 0`), a PodDisruptionBudget and default pod anti-affinity when > 1. Replicas coordinate through PostgreSQL. |
| `web.replicas` | `2` | Stateless. |
| `api.trustedProxies` | `10.0.0.0/8` | Your ingress controller's pod network. |
| `api.extraEnv` | `{}` | Any other `ASTRASOC_*` setting (egress allowlist, auth rate limit, …). |
| `vault.addr` | `""` | Enables `vault://` resolution (token from the secret, key `ASTRASOC_VAULT_TOKEN`). |
| `ingress.annotations` | nginx: buffering off, 1 h read timeout, 5 MB body | Required for the live event stream. |

Replicas started together take turns migrating the schema (advisory lock).
Pods run as non-root with a `RuntimeDefault` seccomp profile, with all
capabilities dropped, no privilege escalation and no service-account token.
The API has a read-only root filesystem. Probes: startup and liveness on
`/api/v1/health/live`, readiness on `/api/v1/health/ready`. Config changes roll
the API automatically (config checksum annotation).

## Plain manifests

`infrastructure/kubernetes/astrasoc.yaml`: the same topology without Helm. Create
the secret as above, edit the host / CORS origin / image tags, then
`kubectl apply -f`.

## ArgoCD

`infrastructure/argocd/application.yaml` deploys the chart with a pinned image
tag and `secrets.existingSecret`. No secret values live in Git.

## Images

CI builds both images on every push (`.github/workflows/ci.yml`). Publish them
to your registry and set `image.registry` / `image.tag`.
