import json
import shutil
import hashlib
import base64
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def run_cmd(cmd, cwd=None):
    """Run a subprocess command with error handling."""
    try:
        subprocess.check_call(cmd, cwd=cwd)
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {' '.join(cmd)}", file=sys.stderr)
        sys.exit(e.returncode)


def main():
    """
    Prepares a Lambda deployment package:
    1. Clean previous artifacts.
    2. Install dependencies.
    3. Copy Lambda handler.
    4. Create ZIP.
    5. Compute SHA256 hash.
    6. Print JSON for Terraform.
    """
    project_root = Path(__file__).parent.parent.resolve()
    source_dir = project_root / "lambda"
    build_dir = project_root / "build"
    pkg_dir = build_dir / "lambda_package"
    output_path = build_dir / "lambda_package.zip"

    # 1. Clean up previous build artifacts safely
    if pkg_dir.exists():
        shutil.rmtree(pkg_dir)
    if output_path.exists():
        output_path.unlink()
    pkg_dir.mkdir(parents=True, exist_ok=True)

    # 2. Install dependencies
    requirements = source_dir / "requirements.txt"
    if requirements.exists():
        run_cmd([
            sys.executable, "-m", "pip", "install",
            "-r", str(requirements),
            "-t", str(pkg_dir)
        ])
    else:
        print("No requirements.txt found, skipping dependency installation", file=sys.stderr)

    # 3. Copy Lambda handler
    handler_file = source_dir / "link_checker_lambda.py"
    if not handler_file.exists():
        print(f"Handler not found: {handler_file}", file=sys.stderr)
        sys.exit(1)
    shutil.copy(handler_file, pkg_dir / handler_file.name)

    # 4. Create ZIP
    with ZipFile(output_path, "w", ZIP_DEFLATED) as zipf:
        for file_path in pkg_dir.rglob("*"):
            zipf.write(file_path, file_path.relative_to(pkg_dir))

    # 5. Compute Base64 SHA256 hash
    with open(output_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).digest()
        b64_hash = base64.b64encode(file_hash).decode("utf-8")

    # 6. Print JSON for Terraform
    result = {
        "output_path": str(output_path),
        "output_base64sha256": b64_hash,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
