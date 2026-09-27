"""Machine-readable validation findings and exit status."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Severity = Literal["ERROR", "WARNING"]
ValidationStatus = Literal["PASS", "WARNING", "ERROR"]


@dataclass(frozen=True)
class ValidationFinding:
    severity: Severity
    code: str
    message: str
    count: int | None = None


@dataclass(frozen=True)
class ValidationReport:
    findings: tuple[ValidationFinding, ...]

    @property
    def status(self) -> ValidationStatus:
        if any(finding.severity == "ERROR" for finding in self.findings):
            return "ERROR"
        if self.findings:
            return "WARNING"
        return "PASS"

    @property
    def exit_code(self) -> int:
        return 2 if self.status == "ERROR" else 0

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "findings": [asdict(finding) for finding in self.findings],
        }
