# NovaDeploy GitOps Platform — Solution Summary

This document summarizes the solution implemented for the NovaDeploy DevOps Lead take-home assignment: a GitOps deployment platform that makes the described incidents structurally impossible through ordering, health-based blocking, and automated enforcement.

---

## 1. Solution Overview

We built a **single-repo GitOps platform** that:

- Deploys all platform and application components via **Argo CD** in a defined order using **sync waves**.
- Ensures dependencies are **healthy** before downstream workloads deploy, using custom Argo CD health checks for External Secrets and the app-of-apps chain.
- Keeps **zero secrets in Git**; credentials are synced from **HashiCorp Vault** into the cluster via **External Secrets Operator (ESO)**.
- Enforces deployment standards in **CI** (kube-linter, deprecated API checks, secret scanning) so bad or unsafe manifests cannot reach the main branch.
- Supports **multi-environment** layout (dev and prod paths; staging can be added the same way) with a shared baseline and per-environment Vault paths.

The design encodes deployment order and health in configuration so that “deploy operators first, then CRDs, then apps” is enforced by the system, not by tribal knowledge.

---

## 2. Architecture

### 2.1 High-level flow

```
                    ┌─────────────────────────────────────────────────────────┐
                    │  Git (single repo)                                      │
                    │  apps/ + platform/                                      │
                    └───────────────────────────┬─────────────────────────────┘
                                                │
                                                ▼
                    ┌─────────────────────────────────────────────────────────┐
                    │  Argo CD (root Application → apps/, exclude root.yaml)   │
                    │  syncPolicy: automated, prune, selfHeal                  │
                    └───────────────────────────┬─────────────────────────────┘
                                                │
              ┌─────────────────────────────────┼─────────────────────────────────┐
              ▼                 ▼                 ▼                 ▼               ▼
        Wave 0            Wave 1             Wave 2             Wave 3          Wave 4
        Namespaces     Vault + cert-mgr    ESO + Reloader   ClusterSecretStore   Demo app
                                                                                  (dev)
```

### 2.2 Sync waves (deployment order)

| Wave | Components | Purpose |
|------|------------|--------|
| **0** | Namespaces | Isolation boundaries first. |
| **1** | Vault, cert-manager | Secret store and TLS; CRDs for Certificate/Issuer. |
| **2** | External Secrets Operator, Stakater Reloader | Secret sync and reload on Secret change. |
| **3** | ClusterSecretStore (Vault) | ESO → Vault connection; must be Ready before apps use ExternalSecrets. |
| **4** | Demo app (ExternalSecret, Postgres, migrate Job, nginx, python-app) | Apps only after secrets and store are healthy. |

Within the demo app (`platform/demo/dev`), waves are: ExternalSecret (0) → Postgres / nginx (1) → migrate Job (2) → python-app (3). Argo CD does not proceed to the next wave until the current wave is **Healthy** (when health checks are configured).

### 2.3 Tools used

| Tool | Role |
|------|------|
| **Argo CD** | GitOps controller; reconciles cluster from Git; sync waves + health drive ordering. |
| **HashiCorp Vault** | External secret store (dev mode); no secrets in Git. |
| **External Secrets Operator (ESO)** | Syncs secrets from Vault into Kubernetes Secrets; CRDs: ExternalSecret, ClusterSecretStore. |
| **cert-manager** | TLS for ESO webhook and other certificates. |
| **Stakater Reloader** | Restarts workloads when referenced Secrets/ConfigMaps change (secret rotation). |

---

## 3. How We Prevent the Four Incidents

### 3.1 Incident #1 — Secret not there (CrashLoopBackOff)

**Problem:** App deployed before the Kubernetes Secret existed; API stayed in CrashLoopBackOff.

**Solution:**

- **Order:** ESO and ClusterSecretStore (waves 2–3) deploy before the demo app (wave 4). Within the demo app, ExternalSecret is wave 0; Postgres and the API are wave 1+.
- **Health-based blocking:** Custom health checks in `platform/argocd/argocd-cm-health.yaml`:
  - **ClusterSecretStore** → Healthy only when `Ready=True` (store validated).
  - **ExternalSecret** → Healthy only when the Secret has been synced (`Ready=True`).
  - **Application** → Healthy when child app sync and resources are healthy (so the root app waits for e.g. vault-secret-store before creating demo-dev).

Argo CD does not apply the next wave until the current one is Healthy. So the demo app (and Postgres) do not deploy until the `app-config` Secret exists. The same ConfigMap ensures the root app waits for the vault-secret-store Application to be Healthy before creating the demo app.

**Artifacts:** `platform/argocd/argocd-cm-health.yaml` (apply once per cluster); README Bootstrap section.

### 3.2 Incident #2 — CRD race (no matches for kind "ServiceMonitor")

**Problem:** Custom resources were applied before the operator had registered its CRDs.

**Solution:**

- Operators that install CRDs (cert-manager, ESO) are in waves 1–2. Resources that *use* those CRDs (ClusterSecretStore, ExternalSecret, and later any ServiceMonitor-style resources) are in waves 3–4. So CRDs exist before any consumer manifests are applied.
- No CRD and consumer are in the same wave; the app-of-apps and health checks ensure wave N is healthy before wave N+1 is applied.

### 3.3 Incident #3 — Phantom edit reverted

**Problem:** A manual `kubectl edit` (e.g. `max_connections`) was never committed; GitOps later reverted it.

**Solution:**

- Root Application has **`selfHeal: true`**. Argo CD continuously reconciles from Git and overwrites cluster state with Git state, so any manual edit is reverted on the next reconciliation.
- Desired state lives in Git; the cluster is not the source of truth. Operators see “drift” in Argo CD (OutOfSync) when someone edits in-cluster.

### 3.4 Incident #4 — Shared secret blast radius

**Problem:** One rotated credential; only one of three services picked up the new value; others used cached old credentials.

**Solution:**

- **Per-service credentials:** Each service can use its own ExternalSecret and Vault path (or distinct keys). Demo uses one ExternalSecret for `app-config`; the pattern scales to one ExternalSecret per service.
- **Reload on change:** Stakater Reloader watches Secrets and restarts only workloads annotated with `reloader.stakater.com/auto: "true"`, so when a Secret is rotated and ESO updates the K8s Secret, only the workloads that use that Secret are restarted and get the new values.

---

## 4. Secrets Management

- **Zero secrets in Git.** All credential data lives in Vault; manifests reference secret names and keys only.
- **Local-friendly:** Vault runs in dev mode in-cluster; no cloud account required. ESO connects via ClusterSecretStore; the `vault-token` Secret is created once (e.g. with root token in dev).
- **Per-environment paths:** e.g. dev uses `secret/data/dev/app`; prod would use a separate path. Each environment’s ExternalSecret points at its own path.
- **Rotation:** Change values in Vault → ESO refreshes the K8s Secret (e.g. 30s refresh) → Reloader restarts annotated Deployments → new pods receive updated env vars. No redeploy of manifests required for rotation.

---

## 5. Standards Enforcement & Validation Pipeline

### 5.1 Pre-merge validation (CI)

Single workflow: **`.github/workflows/policy-check.yml`** runs on push and pull requests to `main`.

| Job | Tool | What it catches |
|-----|------|------------------|
| **kube-linter** | kube-linter + `.kube-linter.yaml` | Containers as root, `:latest` or missing tag, missing CPU/memory requests/limits, `hostNetwork`, `hostPID`, privilege escalation, read-only root filesystem. |
| **deprecated-api** | Pluto | Deprecated or removed Kubernetes API versions in `platform/` and `apps/`. |
| **secret-scan** | Gitleaks | Accidental commits of secrets (tokens, keys, etc.) in the repository. |

Bad manifests or committed secrets block the merge. Standards are documented in the README; new rules can be introduced in warning mode first, then enforced as required checks.

### 5.2 Policy coverage

The pipeline enforces the required standards:

- No containers running as root (runAsNonRoot / runAsUser).
- No images without a tag or using `:latest`.
- Pods must have resource requests and limits.
- No `hostNetwork` or `hostPID`.

Exceptions can be defined in `.kube-linter.yaml` (e.g. by namespace) for legacy or third-party workloads, with a clear rollout strategy (warn first, then enforce).

---

## 6. Repository Structure

```
novadeploy/
├── apps/                          # Argo CD app-of-apps
│   ├── root.yaml                  # Root Application (apps/, exclude root.yaml)
│   ├── demo-dev.yaml              # Demo app (dev) — wave 4
│   ├── demo-prod.yaml             # Demo app (prod) — commented until prod enabled
│   └── appsets/
│       ├── namespaces.yaml        # Wave 0
│       ├── vault.yaml             # Wave 1
│       ├── cert-manager.yaml      # Wave 1
│       ├── external-secrets.yaml  # Wave 2
│       ├── stakater-reloader.yaml # Wave 2
│       └── vault-secret-store.yaml# Wave 3
├── platform/
│   ├── argocd/
│   │   └── argocd-cm-health.yaml  # Health checks for ESO + Application
│   ├── namespaces/
│   ├── vault/
│   ├── cert-manager/
│   ├── external-secrets/          # ESO values + ClusterSecretStore manifest
│   ├── stakater-reloader/
│   └── demo/
│       ├── dev/                   # Dev manifests (ExternalSecret, Postgres, Jobs, Deployments)
│       └── prod/                  # Prod manifests (structure ready)
├── docker_python_app/             # FastAPI + Postgres demo app (migrations, Dockerfile)
├── .github/workflows/
│   └── policy-check.yml           # kube-linter, Pluto, Gitleaks
├── .kube-linter.yaml
├── README.md                      # Entry point, design doc, runbooks, bootstrap
└── solution.md                    # This file
```

---

## 7. Bootstrap and Day-2 Operations

### 7.1 Bootstrap (current)

Assumes a cluster and Argo CD are already installed and this repo is connected:

1. **Enable health-based blocking (recommended):**
   ```bash
   kubectl apply -f platform/argocd/argocd-cm-health.yaml
   kubectl rollout restart deployment argocd-application-controller -n argocd
   ```
2. **Deploy the platform:**
   ```bash
   kubectl apply -f apps/root.yaml
   ```
3. **One-time:** Create the `vault-token` Secret in `external-secrets` and seed Vault at the paths the demo ExternalSecret expects (see README).

Argo CD then syncs the root app and all child apps in wave order; with the health ConfigMap, it will not start the next wave until the current one is Healthy.

### 7.2 Incident runbook

The README includes a **“Secrets not syncing”** runbook: symptoms, checks (ClusterSecretStore, vault-token Secret, ExternalSecret status, Vault data, ESO logs), likely causes, and remediation steps.

---

## 8. Implemented vs Optional / Future

| Area | Implemented | Not implemented (optional or future) |
|------|-------------|--------------------------------------|
| **Deployment safety** | Sync waves, health-based blocking, incident prevention (1–4), selfHeal | — |
| **Secrets** | Zero in Git, Vault + ESO, per-env paths, Reloader for rotation | — |
| **Validation pipeline** | kube-linter, Pluto, Gitleaks | — |
| **Multi-environment** | Dev and prod layout; ApplicationSet pattern for multiple envs | Staging folder; prod app commented; promotion process and “prod more conservative” not yet documented |
| **Bootstrap** | Documented steps (health ConfigMap + root app) | Single command (e.g. `make up` / `./bootstrap.sh`) that creates cluster + installs Argo CD |
| **Design document** | Architecture, deployment safety, one runbook | Scaling considerations (e.g. 10 clusters, 3 regions) |
| **Observability** | Runbook + Argo CD as source of truth | Dedicated “Platform observability” section (health, drift, “what changed”) |
| **Components** | Namespaces, CRDs, cert-manager, ESO, Vault, DB, API (nginx + python-app), Reloader | Policy engine (admission control), monitoring stack, message queue, background worker, RBAC |

---

## 9. Summary

The solution delivers:

- **Deployment ordering and health** so that secrets, CRDs, and operators are ready before apps deploy, addressing Incidents #1 and #2.
- **Git as source of truth** with selfHeal so manual edits are reverted (Incident #3).
- **Per-service secrets and Reloader** so rotation and blast radius are controlled (Incident #4).
- **CI-based enforcement** of security and standards (no root, no `:latest`, resources, no hostNetwork/hostPID, deprecated APIs, secret scanning).
- **Clear structure** for multi-environment (dev/prod paths and ApplicationSets) and a path to staging and “production more conservative” without redesign.

The platform is structured so that the deployment process is encoded in the system rather than in runbooks or tribal knowledge, and so that the described failures are prevented by design, not by process alone.
