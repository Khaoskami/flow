"""Legal agreement generator with SHA-256 hashing and versioning."""

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
    """Generate a personalized 8-section legal consent agreement.

    Returns:
        Full document text ready for signing.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return f"""ELECTRONIC CONSENT AGREEMENT
Age Verification & Data Processing Authorization
Document Version: {DOCUMENT_VERSION}
Generated: {timestamp}

{'=' * 60}

SECTION 1 — PARTIES

This Agreement is entered into between:

a) THE USER: {user_name} (Discord ID: {user_id}), hereinafter referred to \
as "the User";

b) THE SERVER: {guild_name} (Guild ID: {guild_id}), hereinafter referred to \
as "the Server";

c) THE SERVICE PROVIDER: {org_name}, hereinafter referred to as \
"the Service", operating the AgeGate verification system.

{'=' * 60}

SECTION 2 — DECLARATION OF AGE

The User hereby declares and affirms that:

(i) They are eighteen (18) years of age or older at the time of this \
verification;
(ii) They possess full legal capacity to enter into this agreement;
(iii) The identification document submitted is genuine, unaltered, and \
belongs to the User;
(iv) All information provided during the verification process is truthful \
and accurate to the best of their knowledge.

{'=' * 60}

SECTION 3 — CONSENT TO VERIFICATION

The User consents to the following verification processes:

(a) Automated image analysis of the submitted identification document, \
including but not limited to: resolution validation, metadata analysis, \
error level analysis, edge coherence analysis, noise consistency analysis, \
skin/hand presence detection, and optical character recognition (OCR);

(b) Extraction of date of birth and age calculation from the submitted \
document via OCR;

(c) Temporary encrypted storage of analysis results (NOT the original \
image) for a period of twenty-four (24) hours, after which records are \
automatically and permanently deleted;

(d) Permanent storage of this consent agreement and verification status \
(without personally identifiable information from the identification \
document) in the Service's database;

(e) Sharing of verification status (verified/not verified) across all \
Discord servers utilizing the AgeGate system for the purpose of cross-server \
recognition, eliminating the need for repeated verification.

{'=' * 60}

SECTION 4 — DATA HANDLING & PRIVACY

The Service commits to the following data handling practices:

(a) NO human review of submitted identification images shall occur; all \
processing is fully automated;

(b) NO raw images or photographs of identification documents are stored at \
any point; images exist only in memory during analysis and are immediately \
discarded;

(c) Temporary analysis records are encrypted using AES-128-CBC (Fernet) \
encryption and are automatically purged after 24 hours;

(d) Permanent records contain only: verification status, consent agreement \
text, document hash, signing timestamp, and cross-server membership data; \
NO personally identifiable information from the identification document is \
permanently retained;

(e) The User retains the right to request complete deletion of all their \
data at any time by contacting a server administrator or the Service at \
{contact_email}.

{'=' * 60}

SECTION 5 — CROSS-SERVER RECOGNITION

(a) Upon successful verification and signing of this agreement, the User's \
verified status shall be recognized across all Discord servers utilizing the \
AgeGate system;

(b) The User shall not be required to undergo re-verification when joining \
new servers that use the AgeGate system;

(c) Cross-server recognition may be revoked at any time by the User or by \
an administrator of any participating server;

(d) Revocation of verification on one server does not automatically affect \
the User's status on other servers unless a global revocation is performed.

{'=' * 60}

SECTION 6 — LIMITATION OF LIABILITY

(a) The AgeGate verification system operates on a best-effort basis using \
heuristic image analysis and OCR technology; it does NOT constitute a \
KYC-grade (Know Your Customer) identity verification service;

(b) The Service makes no warranty, express or implied, regarding the \
accuracy, completeness, or reliability of the automated analysis;

(c) The User acknowledges that the system may produce false positives or \
false negatives and agrees to hold the Service harmless from any claims \
arising from verification results;

(d) The User indemnifies the Service, the Server, and their respective \
operators against any claims, damages, or liabilities arising from \
fraudulent or misleading submissions.

{'=' * 60}

SECTION 7 — PENALTIES FOR MISREPRESENTATION

The User acknowledges that providing false information, submitting forged \
or altered identification documents, or otherwise misrepresenting their \
age or identity may result in:

(a) Immediate and permanent ban from the Server and all participating \
servers;

(b) Report to Discord Trust & Safety for violation of Discord's Terms of \
Service;

(c) Potential referral to relevant law enforcement authorities where \
applicable under local jurisdiction;

(d) Revocation of all verification records and cross-server recognition \
status.

{'=' * 60}

SECTION 8 — ELECTRONIC SIGNATURE

By clicking "I Agree — Sign Document" and subsequently confirming with \
"Yes, I'm Sure — Sign Now", the User:

(a) Acknowledges that they have read, understood, and agree to all terms \
and conditions set forth in this agreement;

(b) Acknowledges that this electronic signature constitutes a legally \
binding agreement under applicable electronic signature laws, including \
but not limited to the U.S. ESIGN Act and the EU eIDAS Regulation;

(c) Understands that this agreement is permanent and will be stored \
indefinitely as a record of consent;

(d) Confirms that they are entering into this agreement voluntarily and \
without coercion.

{'=' * 60}
END OF DOCUMENT
Parties: {user_name} ({user_id}) | {guild_name} ({guild_id}) | {org_name}
Document Version: {DOCUMENT_VERSION}
Generated: {timestamp}
"""


def hash_document(document_text: str) -> str:
    """Compute SHA-256 hash of a legal document."""
    return hashlib.sha256(document_text.encode("utf-8")).hexdigest()


def split_for_embeds(text: str, max_length: int = 3900) -> list[str]:
    """Split document text into pages that fit Discord's embed limit.

    Splits at paragraph boundaries (double newlines) when possible,
    falling back to line boundaries.

    Args:
        text: Full document text.
        max_length: Maximum characters per page (leave room for formatting).

    Returns:
        List of text pages.
    """
    pages: list[str] = []
    current = ""

    paragraphs = text.split("\n\n")
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= max_length:
            current = candidate
        else:
            if current:
                pages.append(current.strip())
            if len(para) <= max_length:
                current = para
            else:
                lines = para.split("\n")
                current = ""
                for line in lines:
                    candidate = f"{current}\n{line}" if current else line
                    if len(candidate) <= max_length:
                        current = candidate
                    else:
                        if current:
                            pages.append(current.strip())
                        current = line

    if current.strip():
        pages.append(current.strip())

    return pages if pages else [text[:max_length]]


def generate_summary() -> str:
    """Generate a condensed 6-point summary for the initial embed."""
    return (
        "**1. Age Declaration** — You affirm you are 18+ with legal capacity\n"
        "**2. Consent to Processing** — Automated image analysis, OCR, "
        "encrypted temp storage\n"
        "**3. Privacy** — No human review, no raw image storage, "
        "24h temp record auto-delete\n"
        "**4. Cross-Server** — Verified status recognized on all AgeGate servers\n"
        "**5. Liability** — Best-effort heuristic system, not KYC-grade\n"
        "**6. Misrepresentation** — May result in permanent ban + "
        "Trust & Safety report"
    )
