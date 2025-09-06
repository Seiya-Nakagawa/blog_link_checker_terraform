import json
import shutil
import hashlib
import base64
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


def run_cmd(cmd, cwd=None):
    """Run a subprocess command with error handling. All output to stderr."""
    try:
        subprocess.check_call(cmd, cwd=cwd)
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {' '.join(cmd)}", file=sys.stderr)
        sys.exit(e.returncode)


def main():
    project_root = Path(__file__).parent.parent.resolve()
    source_dir = project_root / "lambda"
    build_dir = project_root / "build"
    pkg_dir = build_dir / "lambda_package"
    output_path = build_dir / "lambda_package.zip"

    # 1. Clean up
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

    # 3. Copy handler
    handler_file = source_dir / "link_checker_lambda.py"
    if not handler_file.exists():
        print(f"Handler not found: {handler_file}", file=sys.stderr)
        sys.exit(1)
    shutil.copy(handler_file, pkg_dir / handler_file.name)

    # 4. Zip
    with ZipFile(output_path, "w", ZIP_DEFLATED) as zipf:
        for file_path in pkg_dir.rglob("*"):
            zipf.write(file_path, file_path.relative_to(pkg_dir))

    # 5. Hash
    with open(output_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).digest()
        b64_hash = base64.b64encode(file_hash).decode("utf-8")

    # 6. Pure JSON output
    print(json.dumps({
        "output_path": str(output_path),
        "output_base64sha256": b64_hash
    }))


if __name__ == "__main__":
    main()
