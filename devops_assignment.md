# DevOps Lead — Take-Home Assignment

## Building a GitOps Deployment Platform

> **Timeline:** We expect this to take roughly **10–15 hours**. You have **one week** from receipt to submit.

---

## 1) Scenario

You are joining **NovaDeploy**, a logistics SaaS company that provides fleet tracking and route optimization for delivery companies. NovaDeploy runs several microservices on Kubernetes across multiple environments (dev, staging, production).

The platform has grown organically over two years. What started as a single team deploying one service has become four teams deploying eight services — and the cracks are showing. The past quarter has surfaced a pattern of operational failures that leadership wants solved structurally, not with more runbooks.

### Recent Incidents

**Incident #1 — The Secret That Wasn't There (45-minute outage)**

A new API service was deployed to production. It referenced a Kubernetes Secret for its database credentials. The Secret was supposed to be synced from the external secret store, but the sync operator hadn't finished reconciling yet. The API entered CrashLoopBackOff for 45 minutes until an engineer noticed and manually triggered the sync. Root cause: nothing enforced that the secret existed before the application deployed.

**Incident #2 — The CRD Race (30-minute error loop)**

An engineer added a new monitoring operator that defines Custom Resource Definitions. In the same deployment, they also added custom resources that depend on those CRDs. The custom resources were applied before the CRDs were registered — Kubernetes rejected them with `no matches for kind "ServiceMonitor"`. The operator eventually came up and the resources were retried, but for 30 minutes the GitOps controller was in a degraded state, masking a real issue with an unrelated service.

**Incident #3 — The Phantom Edit (discovered 2 weeks late)**

A production database was running with `max_connections: 200` in the Kubernetes manifest in Git. During a traffic spike, an engineer ran `kubectl edit` to increase it to 500. The change was never committed to Git. Two weeks later, a routine GitOps reconciliation reverted the setting to 200, causing connection exhaustion during peak hours. No one knew the edit had happened, and no one knew it was reverted.

**Incident #4 — The Shared Secret (3-service blast radius)**

Three microservices shared a single database credential stored as a Kubernetes Secret. When the credential was rotated in the secret store, only one service picked up the new value. The other two continued using the cached old credential until their pods were restarted 6 hours later. During that window, two services were intermittently failing auth. No one could tell which services were affected or why.

### Scaling Pressure

NovaDeploy is growing from 3 to 12 engineers. Today, deployments require tribal knowledge — senior engineers know to "deploy the operators first, wait for CRDs, then deploy the services." This works with 3 people. It will not work with 12. The deployment process needs to be encoded in the system, not in people's heads.

**Your task:** Build a deployment platform that makes these incidents structurally impossible, not just unlikely.

---

## 2) The Platform

### Services to Deploy

Your platform must deploy and manage the following components on a **local Kubernetes cluster** (Kind, k3s, or minikube). These are representative of what NovaDeploy runs — you do not need to deploy production-grade versions, but the deployment relationships must be real.

| Component | What It Does | Depends On |
|---|---|---|
| **Namespaces & RBAC** | Isolation boundaries, service accounts | Nothing (cluster primitive) |
| **CRDs** | Schema definitions for operators | Nothing (cluster primitive) |
| **cert-manager** | TLS certificate automation | CRDs for Certificate, Issuer |
| **Secret sync operator** | Syncs secrets from external store to K8s Secrets | CRDs for ExternalSecret, SecretStore; cert-manager (webhook TLS) |
| **Policy engine** | Admission control (block misconfigurations) | CRDs for the policy engine's custom resources |
| **Monitoring stack** | Metrics collection, alerting, dashboards | CRDs for ServiceMonitor, PodMonitor, PrometheusRule |
| **Database** | PostgreSQL (or equivalent) for the API service | Namespace; credentials synced from secret store |
| **Message queue** | Redis or NATS for async processing | Namespace |
| **API service** | HTTP API (any app: nginx, httpbin, podinfo, or your own) | Database credentials available; message queue running |
| **Background worker** | Async job processor | Message queue running; database credentials available |

> **Note:** The "Depends On" column describes runtime dependencies — what must exist and be healthy for each component to start correctly. How you encode and enforce these dependencies is a design decision you should make.

You may substitute equivalent components (e.g., Vault for a secret sync operator, OPA for Kyverno), add components, or simplify where it makes sense. We evaluate the platform design, not the specific tools.

### Application Workloads

The API service and background worker can be **any application** — deploy nginx, httpbin, podinfo, or something you build. We do not evaluate application code. We evaluate how you deploy, manage, and observe it.

### Constraints

- **Local only** — Everything runs on a local Kind/k3s/minikube cluster. No cloud provider accounts required.
- **GitOps** — A GitOps controller (Flux, ArgoCD, or equivalent) reconciles desired state from Git to the cluster. No manual `kubectl apply` for deployed resources.
- **Single repo** — All platform configuration lives in one Git repository.

---

## 3) Requirements

Each requirement below describes a **problem to solve**. How you solve it is your design decision.

### A. Deployment Safety

The incidents in Section 1 must be structurally prevented by your platform design. Specifically:

- An application cannot deploy before its dependencies (secrets, databases, operators, CRDs) are healthy.
- A component that defines CRDs cannot be deployed simultaneously with components that consume those CRDs.
- The system must not silently proceed if a dependency fails — failures must be visible and block downstream deployments.
- The deployment ordering must be encoded in configuration, not in documentation or human memory.

Demonstrate that your platform prevents at least Incidents #1 and #2. Explain how it would handle them.

Consider: What does "healthy" mean for different resource types — a Deployment, a CRD, a Job, an operator? What happens if something takes 5 minutes to become ready? What happens if a phase partially succeeds — some resources healthy, others not?

---

### B. Multi-Environment Management

NovaDeploy runs dev, staging, and production from the same codebase. Support all three environments without duplicating manifests.

- Environments must share a common baseline but differ in operationally meaningful ways (resource allocation, safety controls, reconciliation behavior).
- Production must be treated more conservatively than dev — define what "more conservatively" means for your platform.
- A change should be promotable from dev to staging to prod through a defined process.

Consider: How do you prevent configuration drift between environments? If a change works in staging but breaks prod, how do you diagnose what differed? How do you balance environment parity (things should behave the same) with intentional differences (prod needs more safety)?

---

### C. Secrets Management

**Zero secrets in Git.** Each service must receive its own credentials from an external store, resolved at deploy time or runtime.

- The approach must work locally without a cloud provider account.
- Applications reference secrets by name; actual values come from an external source.
- Incident #4 (shared credential blast radius) must be addressed — services should have isolated credentials where possible.

Consider: How do you handle secret rotation without redeploying? What happens if the secret backend is unavailable — do applications crash or continue with cached values? How do you audit who accessed what?

---

### D. Standards Enforcement

Deployment standards must be enforced automatically, not just through code review.

At minimum, your platform should prevent the following from reaching the cluster:

- Containers running as root
- Images with no tag or using `:latest`
- Pods without resource requests and limits
- Pods using `hostNetwork` or `hostPID`

The enforcement mechanism is your choice. Explain your approach to rolling out new standards without breaking existing workloads.

Consider: What is the difference between blocking a misconfiguration at admission time vs. catching it in CI? How do you handle legitimate exceptions? How would you introduce a new policy to an existing platform with running workloads?

---

### E. Observability

An operator should be able to determine from the platform:

- Is the platform healthy right now?
- Are any deployments failing or stuck?
- Has anything drifted from the desired state in Git?
- What changed in the last hour?

The focus is on **platform observability** — monitoring the deployment system itself, not application-level APM.

Consider: How do you distinguish "not yet deployed" from "deployment failed"? How do you know a deployment is "stuck" vs. "slow"? If someone runs `kubectl edit` in production (Incident #3), how does the platform detect and respond?

---

### F. Validation Pipeline

Bad manifests should not reach the main branch. Implement pre-merge validation that catches:

- Malformed or invalid YAML/Kubernetes manifests
- Deprecated APIs
- Security misconfigurations
- Secrets accidentally committed to the repository

This can be GitHub Actions, a Makefile with validation targets, pre-commit hooks, or any CI mechanism. The coverage matters more than the specific tool.

Consider: How does a new container image version flow from an application build into the deployment manifests? What is the feedback loop when a developer's change fails validation?

---

### G. Bootstrap

A reviewer runs **one command** and has the full platform running on a local cluster. Everything — cluster creation, GitOps controller installation, and full platform reconciliation — should be automated.

Consider: The GitOps controller cannot deploy itself via GitOps because it doesn't exist yet. How do you solve this bootstrap problem? What happens if someone runs the bootstrap command a second time — does it break anything?

---

### H. Design Document

Include a written document (README or separate file) covering:

1. **Architecture overview** — How is your platform structured? Include a diagram.
2. **Deployment safety strategy** — How does your design prevent the incidents described in Section 1?
3. **Incident runbook** — Pick one failure scenario (e.g., "a deployment is stuck," "secrets are not syncing," "the GitOps controller is not reconciling"). Write a brief runbook: what to check, likely root causes, remediation steps.
4. **Scaling considerations** — If NovaDeploy grows to 10 clusters across 3 regions, what changes in your platform design?

---

## 4) Out of Scope

Do not spend time on these:

- Application code quality or functionality
- Application-level observability (APM, distributed tracing for the app)
- HTTPS / TLS termination
- DNS configuration
- Real cloud deployment (AWS / Azure / GCP) — everything runs locally
- Authentication / authorization for applications
- Service mesh
- Multi-cluster networking
- Backup and disaster recovery

Focus on **deployment safety, multi-environment management, platform observability, and operational trustworthiness.**

---

## 5) Submission Guidelines

Provide:

- **Git repository** (public or shared access)
- **README** as the main entry point — explain how to build, run, and evaluate
- **Single bootstrap command** — `make up`, `./bootstrap.sh`, or equivalent
- **Architecture diagram** (any format — ASCII, Mermaid, draw.io, Excalidraw)
- **Design document** (Section H above)
- **Key design decisions and trade-offs** — explain why, not just what
- **AI tools used** (if any) — mention them and explain how you used them effectively
- **Commit history** — incremental, well-structured commits that show your thought process

**You do NOT need to implement everything perfectly.** A well-designed platform with clear reasoning about deployment safety and environment management is preferred over a complete but shallow implementation that checks every box without depth.

---

## 6) Evaluation Criteria

| Area | Weight | What We Evaluate |
|---|---|---|
| Deployment Safety & Ordering | 25% | Does the design prevent the stated failures? Are dependencies explicit and enforced? |
| Implementation Quality | 20% | Do manifests work? Is the GitOps setup idiomatic? Is the repo well-structured? |
| Multi-Environment Design | 15% | Shared baseline with intentional differences, promotion strategy, drift prevention |
| Security & Secrets | 15% | Zero secrets in Git, per-service credentials, admission control, policy rollout |
| Operational Thinking | 10% | Failure modes considered, observability of the platform, recovery procedures |
| CI/CD Pipeline | 10% | Pre-merge validation coverage, manifest checks, security scanning |
| Communication | 5% | README quality, commit discipline, decision rationale, diagram clarity |

**Commit discipline matters.** We value clear, incremental commits with meaningful messages. Your commit history is part of the evaluation.

---

## 7) Guidance

If you get stuck, these prompts may help. They are hints, not requirements — there is no single correct approach.

- Think about what **order** things need to deploy in, and what mechanism **enforces** that order.
- Consider what happens if a deployment **fails mid-way** through a sequence. Does the rest of the sequence continue?
- Most GitOps controllers have features for **dependency management and health checking** — explore what your chosen controller offers.
- Think about how you would **roll back production but not dev** — does your environment design support independent lifecycle management?
- Consider the difference between **preventing a problem** (admission control, CI checks) and **detecting a problem** (monitoring, alerting). A mature platform does both.
- The bootstrap problem (deploying the deployer) is a real challenge. Most solutions involve a small amount of imperative setup followed by declarative management.

---

## Final Note

This assignment mirrors the real challenges of building and operating a deployment platform for a production Kubernetes environment.

We are not testing how fast you can write YAML. We are testing whether you can design a deployment platform that is safe, observable, and operationally trustworthy — and whether you can explain the reasoning behind your design.
