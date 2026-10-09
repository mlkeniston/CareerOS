from __future__ import annotations

import re
from pathlib import Path, PurePosixPath


class UnsafePortfolioPath(ValueError):
    pass


class PortfolioPaths:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir).resolve() / "portfolio"
        self.staging_root = self.root / ".staging"

    def proposal_dir(self, proposal_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f-]{36}", proposal_id):
            raise UnsafePortfolioPath("Invalid proposal ID")
        if self.root.is_symlink() or self.staging_root.is_symlink():
            raise UnsafePortfolioPath("Portfolio staging cannot use symlinks")
        managed_root = self.root.resolve(strict=False)
        resolved_staging = self.staging_root.resolve(strict=False)
        if resolved_staging != managed_root and managed_root not in resolved_staging.parents:
            raise UnsafePortfolioPath("Portfolio staging must stay inside its managed folder")
        proposal = self.staging_root / proposal_id
        if proposal.is_symlink():
            raise UnsafePortfolioPath("Portfolio staging cannot use symlinks")
        resolved_proposal = proposal.resolve(strict=False)
        if resolved_proposal != resolved_staging and resolved_staging not in resolved_proposal.parents:
            raise UnsafePortfolioPath("Proposal staging must stay inside the staging folder")
        return proposal

    def project_root(self, project_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", project_id or ""):
            raise UnsafePortfolioPath("Project ID must use lowercase letters, numbers, and hyphens")
        if self.root.is_symlink():
            raise UnsafePortfolioPath("Portfolio root cannot be a symlink")
        base = self.root / project_id
        if base.is_symlink():
            raise UnsafePortfolioPath("Project folders cannot be symlinks")
        root = self.root.resolve(strict=False)
        resolved = base.resolve(strict=False)
        if resolved != root and root not in resolved.parents:
            raise UnsafePortfolioPath("Project folder escapes the managed portfolio root")
        return base

    def destination(self, project_id: str, relative_path: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", project_id or ""):
            raise UnsafePortfolioPath("Project ID must use lowercase letters, numbers, and hyphens")
        if not isinstance(relative_path, str) or len(relative_path) > 240 or "\0" in relative_path or "\\" in relative_path:
            raise UnsafePortfolioPath("Invalid portfolio path")
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in relative_path.split("/")):
            raise UnsafePortfolioPath("Portfolio paths must stay inside the project folder")
        if any(part.lower() in {".env", ".git", ".staging"} for part in pure.parts):
            raise UnsafePortfolioPath("Sensitive portfolio paths are not allowed")
        base = self.project_root(project_id)
        managed_root = self.root.resolve(strict=False)
        resolved_base = base.resolve(strict=False)
        if resolved_base != managed_root and managed_root not in resolved_base.parents:
            raise UnsafePortfolioPath("Project folder escapes the managed portfolio root")
        candidate = base.joinpath(*pure.parts)
        resolved = candidate.resolve(strict=False)
        if resolved != resolved_base and resolved_base not in resolved.parents:
            raise UnsafePortfolioPath("Portfolio path escapes its managed folder")
        current = base
        for part in pure.parts:
            current = current / part
            if current.is_symlink():
                raise UnsafePortfolioPath("Symlinks are not allowed in portfolio paths")
        return candidate
