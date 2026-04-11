# ADR 005: Federated Identity - AWS Cognito & Discord

**Date:** 2026-04-06
**Status:** Accepted

## Context
AsheFlow requires a secure Authentication and Role-Based Access Control (RBAC) layer to resolve MVP Gap #3. The application is intended for enterprise adoption but will be highly integrated into the team's existing workflow, which relies heavily on a Discord server. 

We evaluated three main approaches:
1. **Custom JWT (Build from scratch):** High maintenance burden, lacks compliance, introduces significant security risks.
2. **Standard Managed IdP (e.g., pure AWS Cognito):** Enterprise-compliant, but introduces onboarding friction (new passwords for the crew).
3. **Pure OAuth2 (e.g., Discord Auth):** Frictionless for the crew, but ties corporate access directly to a social gaming platform, creating enterprise compliance risks.

## Decision
We will implement an **Identity Federation** architecture. 
- **AWS Cognito** will serve as our central Identity Broker and issuer of JWTs.
- **Discord OAuth2** will be configured as a Federated Identity Provider inside Cognito.

## Consequences (Trade-offs)
### Positive
* **Frictionless Onboarding:** Crew members can log in using their existing Discord accounts. No new passwords to manage.
* **Enterprise Compliance:** The FastAPI backend and AWS infrastructure only interface with standard AWS Cognito JWTs. This satisfies SOC2, auditing, and corporate security requirements.
* **Future-Proof:** If the employer mandates moving away from Discord to Microsoft Teams or Slack, we simply swap the federated identity provider in the AWS Console. **Zero changes to the backend codebase will be required.**

### Negative
* **Configuration Overhead:** Requires initial setup in both the Discord Developer Portal and the AWS Console before tokens can be generated.

## Technical Implementation Notes
* The backend will not handle passwords or OAuth handshakes.
* The backend's only authentication responsibility is validating the cryptographic signature of the AWS Cognito JWT using PyJWT (or `aws-jwt-verify`) against Cognito's public JWKS (JSON Web Key Set).
* Role mapping (e.g., `discord_role_id` -> `asheflow_role`) will be managed via Cognito attributes or a backend sync job.