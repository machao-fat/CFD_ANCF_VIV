from pathlib import Path


def validate_factory_target(stage_root: Path, branch: Path) -> None:
    stage_root = stage_root.resolve()
    branch = branch.resolve(strict=False)
    if branch.parent != stage_root:
        raise ValueError("factory branch target escapes the stage root")
    if branch.exists() or branch.is_symlink():
        raise FileExistsError(branch)


def prepare_stage_parent(stage_root: Path) -> None:
    stage_root.mkdir(parents=True, exist_ok=True)
    if stage_root.is_symlink():
        raise ValueError("stage root must not be a symbolic link")
