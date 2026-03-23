"""10-layer image analysis pipeline for ID verification."""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageFilter
from PIL.ExifTags import TAGS
from scipy import ndimage

try:
    import pytesseract
except ImportError:
    pytesseract = None  # type: ignore[assignment]


@dataclass
class AnalysisResult:
    """Result from the 10-layer analysis pipeline."""

    passed: bool = False
    rejection_reason: str = ""
    image_hash: str = ""
    # Scores
    tamper_score: float = 0.0
    exif_score: float = 0.0
    ela_score: float = 0.0
    edge_score: float = 0.0
    noise_score: float = 0.0
    skin_coverage: float = 0.0
    ocr_confidence: float = 0.0
    # Extracted data
    age_detected: int | None = None
    dob_extracted: str | None = None
    username_found: bool = False
    date_found: bool = False
    document_valid: bool = False
    # Flags
    flags: list[str] = field(default_factory=list)
    # Per-layer pass/fail
    checks: dict[str, bool] = field(default_factory=dict)


# Editing software signatures to detect in EXIF
_EDITOR_SIGNATURES = [
    "photoshop", "gimp", "canva", "pixlr", "affinity", "lightroom",
    "snapseed", "picsart", "adobe", "figma", "illustrator", "sketch",
    "inkscape", "corel", "krita",
]

# Government ID keywords
_ID_KEYWORDS = [
    "republic", "license", "licence", "passport", "identity", "identification",
    "date of birth", "expiry", "expires", "expiration", "national",
    "government", "driver", "driving", "issued", "issuing", "authority",
    "card", "department", "ministry", "bureau", "registry",
]

# Invalid document keywords
_INVALID_DOC_KEYWORDS = [
    "student", "school", "membership", "library", "gym", "university",
    "college", "club", "employee", "company", "corporate", "visitor",
]

# OCR error substitution table
_OCR_SUBS = str.maketrans("01|!$58", "OlliSsB")

# DOB label patterns
_DOB_LABELS = re.compile(
    r"(?:date\s*of\s*birth|d\.?o\.?b\.?|born|geboortedatum|"
    r"fecha\s*de\s*nacimiento|date\s*de\s*naissance)",
    re.IGNORECASE,
)


class ImageAnalyzer:
    """10-layer image analysis for ID verification."""

    def __init__(
        self,
        tamper_threshold: float = 0.60,
        ocr_confidence_min: float = 0.35,
        min_age: int = 18,
    ) -> None:
        self.tamper_threshold = tamper_threshold
        self.ocr_confidence_min = ocr_confidence_min
        self.min_age = min_age

    async def analyze(
        self, image_bytes: bytes, username: str
    ) -> AnalysisResult:
        """Run the full 10-layer analysis pipeline.

        Args:
            image_bytes: Raw image file bytes.
            username: Discord username to verify on the handwritten note.

        Returns:
            AnalysisResult with pass/fail and all scores.
        """
        result = AnalysisResult()
        result.image_hash = hashlib.sha256(image_bytes).hexdigest()

        try:
            img = Image.open(io.BytesIO(image_bytes))
        except Exception:
            result.rejection_reason = "Could not open image file."
            return result

        # Layer 1 — Resolution
        if not self._check_resolution(img, result):
            return result

        # Layer 2 — EXIF metadata
        result.exif_score = self._analyze_exif(img, result)

        # Layer 3 — Error Level Analysis
        result.ela_score = self._error_level_analysis(img, result)

        # Layer 4 — Edge Coherence
        result.edge_score = self._edge_coherence(img, result)

        # Layer 5 — Noise Consistency
        result.noise_score = self._noise_consistency(img, result)

        # Layer 6 — Composite tamper gate
        if not self._tamper_gate(result):
            return result

        # Layer 7 — Skin/hand detection
        if not self._detect_skin(img, result):
            return result

        # Layers 8-10 require OCR
        if pytesseract is None:
            result.flags.append("OCR_UNAVAILABLE")
            result.rejection_reason = "OCR engine not available."
            return result

        ocr_text = self._run_ocr(img, result)
        if ocr_text is None:
            return result

        # Layer 8 — Username verification
        if not self._verify_username(ocr_text, username, result):
            return result

        # Layer 9 — Date verification
        if not self._verify_date(ocr_text, result):
            return result

        # Layer 10 — Document type + DOB + age
        if not self._validate_document(ocr_text, result):
            return result

        result.passed = True
        return result

    # ── Layer 1: Resolution ────────────────────────────────────

    def _check_resolution(self, img: Image.Image, result: AnalysisResult) -> bool:
        w, h = img.size
        result.checks["resolution"] = w >= 640 and h >= 480
        if not result.checks["resolution"]:
            result.rejection_reason = (
                f"Image resolution too low ({w}×{h}). Minimum 640×480 required."
            )
            result.flags.append("LOW_RESOLUTION")
        return result.checks["resolution"]

    # ── Layer 2: EXIF Metadata ─────────────────────────────────

    def _analyze_exif(self, img: Image.Image, result: AnalysisResult) -> float:
        score = 0.0
        try:
            exif = img._getexif()  # noqa: SLF001
        except Exception:
            exif = None

        if exif is None:
            score = 0.25  # Possible screenshot
            result.flags.append("NO_EXIF")
        else:
            tag_values = []
            for tag_id, value in exif.items():
                tag_name = TAGS.get(tag_id, str(tag_id))
                tag_values.append(f"{tag_name}: {value}")

            combined = " ".join(str(v).lower() for v in tag_values)
            for sig in _EDITOR_SIGNATURES:
                if sig in combined:
                    score += 0.3
                    result.flags.append(f"EDITOR_DETECTED:{sig.upper()}")

            # DPI mismatch check
            dpi = img.info.get("dpi")
            if dpi and isinstance(dpi, tuple) and len(dpi) == 2:
                if abs(dpi[0] - dpi[1]) > 10:
                    score += 0.2
                    result.flags.append("DPI_MISMATCH")

        result.checks["exif"] = score < 0.5
        return min(score, 1.0)

    # ── Layer 3: Error Level Analysis ──────────────────────────

    def _error_level_analysis(self, img: Image.Image, result: AnalysisResult) -> float:
        try:
            rgb = img.convert("RGB")
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG", quality=90)
            buf.seek(0)
            resaved = Image.open(buf).convert("RGB")

            orig_arr = np.array(rgb, dtype=np.float32)
            resaved_arr = np.array(resaved, dtype=np.float32)
            diff = np.abs(orig_arr - resaved_arr)

            block_size = 32
            h, w = diff.shape[:2]
            block_means = []
            for y in range(0, h - block_size, block_size):
                for x in range(0, w - block_size, block_size):
                    block = diff[y : y + block_size, x : x + block_size]
                    block_means.append(np.mean(block))

            if block_means:
                variance = np.var(block_means)
                mean_error = np.mean(block_means)
                norm_var = min(variance / 100.0, 1.0)
                mean_penalty = min(mean_error / 50.0, 0.5)
                score = norm_var * 0.7 + mean_penalty * 0.3
            else:
                score = 0.0
        except Exception:
            score = 0.0

        result.checks["ela"] = score < 0.7
        return min(score, 1.0)

    # ── Layer 4: Edge Coherence ────────────────────────────────

    def _edge_coherence(self, img: Image.Image, result: AnalysisResult) -> float:
        try:
            gray = np.array(img.convert("L"), dtype=np.float32)
            edges = np.array(img.convert("L").filter(ImageFilter.FIND_EDGES),
                             dtype=np.float32)

            block_size = 48
            h, w = edges.shape
            densities = []
            for y in range(0, h - block_size, block_size):
                for x in range(0, w - block_size, block_size):
                    block = edges[y : y + block_size, x : x + block_size]
                    densities.append(np.mean(block))

            if densities and np.mean(densities) > 0:
                cv = np.std(densities) / np.mean(densities)
                score = max(0.0, (cv - 0.6)) / 1.4
            else:
                score = 0.0
        except Exception:
            score = 0.0

        result.checks["edge_coherence"] = score < 0.7
        return min(score, 1.0)

    # ── Layer 5: Noise Consistency ─────────────────────────────

    def _noise_consistency(self, img: Image.Image, result: AnalysisResult) -> float:
        try:
            gray = np.array(img.convert("L"), dtype=np.float64)
            smoothed = ndimage.uniform_filter(gray, size=5)
            noise = gray - smoothed

            block_size = 32
            h, w = noise.shape
            variances = []
            for y in range(0, h - block_size, block_size):
                for x in range(0, w - block_size, block_size):
                    block = noise[y : y + block_size, x : x + block_size]
                    variances.append(np.var(block))

            if variances and np.mean(variances) > 0:
                cv = np.std(variances) / np.mean(variances)
                if cv > 2.0:
                    score = 0.0  # Clean — natural noise variation
                elif cv < 0.3:
                    score = 0.9  # Highly suspicious — uniform noise
                else:
                    score = max(0.0, 1.0 - (cv - 0.3) / 1.7)
            else:
                score = 0.5
        except Exception:
            score = 0.5

        result.checks["noise"] = score < 0.7
        return min(score, 1.0)

    # ── Layer 6: Composite Tamper Gate ─────────────────────────

    def _tamper_gate(self, result: AnalysisResult) -> bool:
        composite = (
            result.ela_score * 0.35
            + result.edge_score * 0.25
            + result.noise_score * 0.25
            + result.exif_score * 0.15
        )
        result.tamper_score = round(composite, 4)
        result.checks["tamper_gate"] = composite <= self.tamper_threshold
        if not result.checks["tamper_gate"]:
            result.rejection_reason = (
                f"Image failed integrity checks (tamper score: "
                f"{composite:.2f}, threshold: {self.tamper_threshold:.2f})."
            )
            result.flags.append("TAMPER_DETECTED")
        return result.checks["tamper_gate"]

    # ── Layer 7: Skin/Hand Detection ───────────────────────────

    def _detect_skin(self, img: Image.Image, result: AnalysisResult) -> bool:
        try:
            hsv = np.array(img.convert("HSV"), dtype=np.float32)
            h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

            # 4 overlapping HSV ranges for diverse skin tones
            masks = [
                (h >= 0) & (h <= 25) & (s >= 40) & (s <= 200) & (v >= 80),
                (h >= 0) & (h <= 15) & (s >= 20) & (s <= 150) & (v >= 100),
                (h >= 10) & (h <= 35) & (s >= 30) & (s <= 180) & (v >= 60),
                (h >= 0) & (h <= 20) & (s >= 50) & (s <= 230) & (v >= 40),
            ]
            combined_mask = masks[0]
            for m in masks[1:]:
                combined_mask = combined_mask | m

            skin_fraction = np.sum(combined_mask) / combined_mask.size
            result.skin_coverage = round(float(skin_fraction), 4)

            # Cluster validation
            if skin_fraction >= 0.015:
                labeled, num_features = ndimage.label(combined_mask)
                if num_features > 0:
                    sizes = ndimage.sum(combined_mask, labeled,
                                        range(1, num_features + 1))
                    largest = max(sizes) / combined_mask.size
                    if largest < 0.003:
                        skin_fraction *= 0.3
                        result.flags.append("SCATTERED_SKIN_PIXELS")

            result.checks["skin_detection"] = skin_fraction >= 0.015
            if not result.checks["skin_detection"]:
                result.rejection_reason = (
                    "No hand detected in the photo. Please hold your ID "
                    "in your hand as shown in the guide."
                )
                result.flags.append("NO_HAND_DETECTED")
        except Exception:
            result.checks["skin_detection"] = False
            result.rejection_reason = "Could not analyze skin presence."

        return result.checks.get("skin_detection", False)

    # ── OCR Helper ─────────────────────────────────────────────

    def _run_ocr(self, img: Image.Image, result: AnalysisResult) -> str | None:
        try:
            data = pytesseract.image_to_data(
                img, output_type=pytesseract.Output.DICT, config="--psm 3"
            )
            confidences = [
                int(c) for c in data["conf"] if str(c).lstrip("-").isdigit()
            ]
            valid = [c for c in confidences if c > 0]
            avg_conf = sum(valid) / len(valid) / 100.0 if valid else 0.0
            text = " ".join(
                t for t, c in zip(data["text"], confidences)
                if c > 0 and t.strip()
            )

            # Fallback to PSM 6
            if avg_conf < self.ocr_confidence_min:
                data2 = pytesseract.image_to_data(
                    img, output_type=pytesseract.Output.DICT, config="--psm 6"
                )
                confs2 = [
                    int(c) for c in data2["conf"] if str(c).lstrip("-").isdigit()
                ]
                valid2 = [c for c in confs2 if c > 0]
                avg2 = sum(valid2) / len(valid2) / 100.0 if valid2 else 0.0
                if avg2 > avg_conf:
                    avg_conf = avg2
                    text = " ".join(
                        t for t, c in zip(data2["text"], confs2)
                        if c > 0 and t.strip()
                    )

            result.ocr_confidence = round(avg_conf, 4)
            result.checks["ocr"] = avg_conf >= self.ocr_confidence_min

            if not result.checks["ocr"]:
                result.rejection_reason = (
                    f"OCR confidence too low ({avg_conf:.0%}). "
                    "Please take a clearer photo with better lighting."
                )
                result.flags.append("LOW_OCR_CONFIDENCE")
                return None

            return text
        except Exception as e:
            result.rejection_reason = f"OCR processing failed: {e}"
            result.flags.append("OCR_ERROR")
            return None

    # ── Layer 8: Username Verification ─────────────────────────

    def _verify_username(
        self, text: str, username: str, result: AnalysisResult
    ) -> bool:
        text_lower = text.lower()
        user_lower = username.lower()

        # Strategy 1: Exact substring
        if user_lower in text_lower:
            result.username_found = True
            result.checks["username"] = True
            return True

        # Strategy 2: Normalized with OCR error subs
        normalized_text = text_lower.translate(_OCR_SUBS)
        normalized_user = user_lower.translate(_OCR_SUBS)
        if normalized_user in normalized_text:
            result.username_found = True
            result.checks["username"] = True
            return True

        # Strategy 3: Levenshtein sliding window (for usernames >= 5 chars)
        if len(user_lower) >= 5:
            tolerance = max(1, len(user_lower) // 4)
            words = text_lower.split()
            full_text = text_lower
            for i in range(len(full_text) - len(user_lower) + 1):
                window = full_text[i : i + len(user_lower)]
                if _levenshtein(window, user_lower) <= tolerance:
                    result.username_found = True
                    result.checks["username"] = True
                    return True

        result.checks["username"] = False
        result.rejection_reason = (
            f"Could not find username '{username}' in the photo. "
            "Please write it clearly on the paper note."
        )
        result.flags.append("USERNAME_NOT_FOUND")
        return False

    # ── Layer 9: Date Verification ─────────────────────────────

    def _verify_date(self, text: str, result: AnalysisResult) -> bool:
        today = datetime.now(timezone.utc)
        d, m, y = today.day, today.month, today.year
        month_names = [
            "", "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ]
        month_short = [
            "", "jan", "feb", "mar", "apr", "may", "jun",
            "jul", "aug", "sep", "oct", "nov", "dec",
        ]

        variants = [
            f"{d:02d}/{m:02d}/{y}", f"{m:02d}/{d:02d}/{y}",
            f"{y}-{m:02d}-{d:02d}", f"{d:02d}.{m:02d}.{y}",
            f"{d:02d}-{m:02d}-{y}", f"{d}/{m}/{y}",
            f"{m}/{d}/{y}",
            f"{month_names[m]} {d}, {y}", f"{d} {month_names[m]} {y}",
            f"{month_short[m]} {d}, {y}", f"{d} {month_short[m]} {y}",
            f"{month_names[m]} {d} {y}", f"{d} {month_names[m]}, {y}",
            f"{d:02d}/{m:02d}/{y % 100:02d}",
            f"{m:02d}/{d:02d}/{y % 100:02d}",
            f"{d:02d}.{m:02d}.{y % 100:02d}",
            f"{d:02d}-{m:02d}-{y % 100:02d}",
            f"{month_names[m].capitalize()} {d}, {y}",
            f"{d} {month_names[m].capitalize()} {y}",
            f"{month_short[m].capitalize()} {d}, {y}",
            f"{d} {month_short[m].capitalize()} {y}",
        ]

        text_lower = text.lower()
        text_normalized = re.sub(r"[/.\-]", " ", text_lower)

        for variant in variants:
            if variant.lower() in text_lower:
                result.date_found = True
                result.checks["date"] = True
                return True

        # Proximity fallback
        day_str = str(d)
        month_str = month_names[m]
        year_str = str(y)
        tokens = text_normalized.split()
        for i, token in enumerate(tokens):
            if day_str in token:
                nearby = " ".join(tokens[max(0, i - 3) : i + 4])
                if (month_str in nearby or str(m) in nearby) and year_str in nearby:
                    result.date_found = True
                    result.checks["date"] = True
                    return True

        result.checks["date"] = False
        result.rejection_reason = (
            "Could not find today's date in the photo. "
            "Please write today's date clearly on the paper note."
        )
        result.flags.append("DATE_NOT_FOUND")
        return False

    # ── Layer 10: Document Type + DOB + Age ────────────────────

    def _validate_document(self, text: str, result: AnalysisResult) -> bool:
        text_lower = text.lower()

        # Check for government ID keywords
        id_hits = sum(1 for kw in _ID_KEYWORDS if kw in text_lower)
        invalid_hits = sum(1 for kw in _INVALID_DOC_KEYWORDS if kw in text_lower)

        if invalid_hits >= 2:
            result.checks["document_type"] = False
            result.rejection_reason = (
                "This appears to be a non-government ID "
                "(student card, membership card, etc.). "
                "Please use a government-issued photo ID."
            )
            result.flags.append("INVALID_DOCUMENT_TYPE")
            return False

        if id_hits < 2:
            result.checks["document_type"] = False
            result.rejection_reason = (
                "Could not identify this as a government-issued ID. "
                "Please use a passport, driver's license, or national ID card."
            )
            result.flags.append("UNRECOGNIZED_DOCUMENT")
            return False

        result.checks["document_type"] = True
        result.document_valid = True

        # DOB extraction
        dob = self._extract_dob(text_lower)
        if dob is None:
            result.checks["dob"] = False
            result.rejection_reason = (
                "Could not extract date of birth from the ID. "
                "Please ensure the DOB is visible and not covered."
            )
            result.flags.append("DOB_NOT_FOUND")
            return False

        result.dob_extracted = dob.isoformat()
        today = datetime.now(timezone.utc).date()
        age = (
            today.year - dob.year
            - ((today.month, today.day) < (dob.month, dob.day))
        )
        result.age_detected = age
        result.checks["dob"] = True

        if age < 0 or age > 120:
            result.checks["age"] = False
            result.rejection_reason = f"Invalid age calculated ({age})."
            result.flags.append("INVALID_AGE")
            return False

        if age < self.min_age:
            result.checks["age"] = False
            result.rejection_reason = (
                f"You must be at least {self.min_age} years old to verify. "
                f"Detected age: {age}."
            )
            result.flags.append("UNDERAGE")
            return False

        result.checks["age"] = True
        return True

    def _extract_dob(self, text: str) -> datetime | None:
        """Try to extract date of birth from OCR text."""
        # Look for DOB label to narrow search region
        match = _DOB_LABELS.search(text)
        region = text[match.start() :] if match else text

        patterns = [
            # YYYY-MM-DD
            (r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", "ymd"),
            # DD/MM/YYYY or DD-MM-YYYY
            (r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", "dmy"),
            # DD Month YYYY
            (r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", "d_month_y"),
            # Month DD, YYYY
            (r"([a-z]+)\s+(\d{1,2}),?\s+(\d{4})", "month_d_y"),
        ]

        month_map = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12,
            "jan": 1, "feb": 2, "mar": 3, "apr": 4,
            "jun": 6, "jul": 7, "aug": 8, "sep": 9,
            "oct": 10, "nov": 11, "dec": 12,
        }

        current_year = datetime.now(timezone.utc).year
        for pattern, fmt in patterns:
            for m in re.finditer(pattern, region):
                try:
                    if fmt == "ymd":
                        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    elif fmt == "dmy":
                        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    elif fmt == "d_month_y":
                        d = int(m.group(1))
                        mo = month_map.get(m.group(2).lower(), 0)
                        y = int(m.group(3))
                    elif fmt == "month_d_y":
                        mo = month_map.get(m.group(1).lower(), 0)
                        d = int(m.group(2))
                        y = int(m.group(3))
                    else:
                        continue

                    if not (1920 <= y <= current_year - 5):
                        continue
                    if not (1 <= mo <= 12 and 1 <= d <= 31):
                        continue

                    return datetime(y, mo, d).date()
                except (ValueError, IndexError):
                    continue

        return None


def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr

    return prev[-1]
