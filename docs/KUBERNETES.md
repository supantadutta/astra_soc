# Kubernetes / GitOps

## Raw manifests
```bash
kubectl apply -f infrastructure/kubernetes/astrasoc.yaml
```
Creates a namespace, config/secret, api + web Deployments/Services, and an
Ingress routing `/api` → api and `/` → web. Replace the demo secret and use a
PVC + managed Postgres for production.

## Helm
```bash
helm install astrasoc infrastructure/helm/astrasoc \
  --set secrets.jwtSecret=$(openssl rand -hex 32)
```
Values cover images, replicas, resources, ingress host, JWT secret, and optional
Postgres/Redis toggles.

## ArgoCD (GitOps)
`infrastructure/argocd/application.yaml` defines an Application that syncs the
Helm chart from the repo with automated prune + self-heal. Apply it in the
`argocd` namespace.

## Probes & scaling
The API exposes `/health` (liveness/readiness). Scale api/web replicas
independently; back rate-limiting with Redis for multi-node.
