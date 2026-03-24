"""Legal consent agreement generator with SHA-256 integrity hashing."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

DOCUMENT_VERSION = 1


def generate_agreement(
    user_name: str,
    user_id: int,
    guild_name: str,
    guild_id: int,
    org_name: str = "AgeGate Verification Services",
    contact_email: str = "legal@example.com",
) -> str:
    """Generate a legal consent document. Returns document text."""

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    document = f"""══════════════════════════════════════════════════
ELECTRONIC CONSENT & AGE VERIFICATION AGREEMENT
Version {DOCUMENT_VERSION}
══════════════════════════════════════════════════

Generated: {now}

SECTION 1 — PARTIES

This agreement ("Agreement") is entered into between:

  USER:
    Display Name: {user_name}
    Discord User ID: {user_id}

  SERVER:
    Server Name: {guild_name}
    Discord Guild ID: {guild_id}

  SERVICE PROVIDER:
    Organization: {org_name}
    Contact: {contact_email}

SECTION 2 — DECLARATION OF AGE

By signing this Agreement, the User hereby declares and affirms that:

  (a) They are at least eighteen (18) years of age;
  (b) They possess full legal capacity to enter into this Agreement;
  (c) The identification document provided during verification is genuine,
      unaltered, and belongs to the User;
  (d) All information provided during the verification process is truthful
      and accurate to the best of their knowledge.

SECTION 3 — CONSENT TO VERIFICATION

The User consents to the following verification processes:

  (a) Automated image analysis of the submitted identification document,
      including but not limited to: resolution validation, metadata
      analysis, error level analysis, edge coherence analysis, noise
      consistency analysis, skin/hand presence detection, optical
      character recognition (OCR), and document type classification;
  (b) Extraction of date of birth information via OCR for age calculation;
  (c) Temporary encrypted storage of analysis results (metadata and scores
      only — no raw images) for a period not exceeding twenty-four (24)
      hours, after which records are automatically and irrevocably deleted;
  (d) Permanent storage of this signed consent agreement and verification
      status (pass/fail, age detected, confidence scores) in the Service
      Provider's database;
  (e) Sharing of verification status (verified/not verified) across all
      Discord servers utilizing the Service Provider's verification system.

SECTION 4 — DATA HANDLING & PRIVACY

The Service Provider commits to the following data handling practices:

  (a) NO human review of submitted identification images shall occur under
      normal operating conditions;
  (b) NO raw identification images are stored at any time — images exist
      only in volatile memory during the analysis process and are
      explicitly destroyed immediately upon completion;
  (c) Temporary analysis records are encrypted using AES-128-CBC (Fernet)
      encryption and are automatically purged after the retention period;
  (d) Permanent records contain NO personally identifiable information
      extracted from the identification document itself — only the
      verification outcome, confidence scores, and this Agreement;
  (e) The User may request complete deletion of all their data at any time
      by contacting a server administrator who may invoke the data purge
      command, or by contacting the Service Provider at {contact_email}.

SECTION 5 — CROSS-SERVER RECOGNITION

  (a) Upon successful verification and signing of this Agreement, the
      User's verified status shall be recognized across all Discord servers
      utilizing the Service Provider's verification system;
  (b) The User shall not be required to re-verify their identity when
      joining additional servers using this system;
  (c) Cross-server recognition may be revoked by any server administrator
      or by the User's own request;
  (d) Revocation in one server does not automatically revoke verification
      in other servers unless a global purge is performed.

SECTION 6 — LIMITATION OF LIABILITY

  (a) The verification system employs heuristic analysis techniques and is
      provided on a "best effort" basis. It does not constitute a KYC
      (Know Your Customer) compliant identity verification system;
  (b) The Service Provider makes no warranty, express or implied, regarding
      the accuracy or completeness of the verification process;
  (c) The User agrees to indemnify and hold harmless the Service Provider,
      server administrators, and Discord Inc. from any claims, damages, or
      liabilities arising from the use of this verification system;
  (d) This system is intended as a reasonable-effort age gate and should
      not be relied upon as the sole mechanism for legal compliance in
      jurisdictions requiring formal identity verification.

SECTION 7 — PENALTIES FOR MISREPRESENTATION

The User acknowledges that providing false information, submitting forged
or altered identification documents, or otherwise misrepresenting their
age or identity may result in:

  (a) Immediate and permanent ban from all servers utilizing this system;
  (b) Reporting to Discord's Trust & Safety team;
  (c) Referral to appropriate law enforcement authorities where the
      misrepresentation involves potential harm to minors or constitutes
      a criminal offense under applicable law.

SECTION 8 — ELECTRONIC SIGNATURE

By clicking "I Agree — Sign Document" and confirming, the User:

  (a) Acknowledges having read and understood all sections of this Agreement;
  (b) Agrees to be bound by all terms and conditions herein;
  (c) Understands that this constitutes a legally binding electronic
      signature under applicable electronic signature laws (including but
      not limited to the U.S. ESIGN Act, EU eIDAS Regulation, and
      comparable legislation in other jurisdictions);
  (d) Confirms that this Agreement is entered into freely, voluntarily,
      and without coercion.

══════════════════════════════════════════════════
Document Version: {DOCUMENT_VERSION}
Generated By: {org_name}
══════════════════════════════════════════════════"""

    return document


def hash_document(text: str) -> str:
    """Compute SHA-256 hash of document text."""
    return hashlib.sha256(text.encode()).hexdigest()


def generate_summary() -> str:
    """Generate a brief summary of the consent agreement sections."""
    return (
        "**This agreement covers:**\n"
        "1. **Parties** — Your identity and the server\n"
        "2. **Age Declaration** — Confirming you are 18+\n"
        "3. **Consent to Verification** — What analysis is performed\n"
        "4. **Data Handling & Privacy** — How your data is protected\n"
        "5. **Cross-Server Recognition** — Verify once, recognized everywhere\n"
        "6. **Limitation of Liability** — Service provided as-is\n"
        "7. **Penalties for Misrepresentation** — Consequences of fraud\n"
        "8. **Electronic Signature** — Legally binding consent\n\n"
        "📖 Please read all sections before signing."
    )


def split_for_embeds(text: str, max_length: int = 1800) -> list[str]:
    """Split document text into pages suitable for Discord embeds."""
    sections = text.split("\nSECTION ")
    pages: list[str] = []
    current_page = ""

    for i, section in enumerate(sections):
        chunk = section if i == 0 else f"SECTION {section}"

        if len(current_page) + len(chunk) + 1 > max_length:
            if current_page:
                pages.append(current_page.strip())
            current_page = chunk
        else:
            current_page += "\n" + chunk if current_page else chunk

    if current_page.strip():
        pages.append(current_page.strip())

    return pages if pages else [text[:max_length]]
