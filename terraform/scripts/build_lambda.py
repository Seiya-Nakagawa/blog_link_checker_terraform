import json
import os
import subprocess
import sys
import shutil
import hashlib
import base64
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

def main():
    """
    This script prepares a Lambda deployment package.
    1. It installs dependencies from requirements.txt.
    2. It copies the Lambda handler source code.
    3. It zips the contents into a deployment package.
    4. It calculates the SHA256 hash of the zip file.
    5. It prints a JSON object to stdout with the path and hash for Terraform.
    """
    # This script is in 'scripts', so the project root is its parent directory.
    project_root = Path(__file__).parent.parent.resolve()
    
    source_dir = project_root / "lambda"
    build_dir = project_root / "build"
    pkg_dir = build_dir / "lambda_package"
    output_path = build_dir / "lambda_package.zip"

    # 1. Clean up previous build artifacts
    if build_dir.exists():
        shutil.rmtree(build_dir)
    pkg_dir.mkdir(parents=True, exist_ok=True)

    # 2. Install dependencies using pip
    # Using sys.executable ensures we use the same Python interpreter that runs this script.
    subprocess.check_call([
        sys.executable, "-m", "pip", "install",
        "-r", str(source_dir / "requirements.txt"),
        "-t", str(pkg_dir)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) # Suppress pip output

    # 3. Copy the Lambda handler source code into the package directory
    shutil.copy(
        source_dir / "link_checker_lambda.py",
        pkg_dir / "link_checker_lambda.py"
    )

    # 4. Create the zip file using Python's built-in zipfile library
    with ZipFile(output_path, 'w', ZIP_DEFLATED) as zipf:
        for file_path in pkg_dir.rglob('*'):
            zipf.write(file_path, file_path.relative_to(pkg_dir))

    # 5. Calculate the Base64-encoded SHA256 hash of the zip file
    with open(output_path, 'rb') as f:
        file_hash = hashlib.sha256(f.read()).digest()
        b64_hash = base64.b64encode(file_hash).decode('utf-8')

    # 6. Output a JSON object to stdout for Terraform to consume
    result = {
        "output_path": str(output_path),
        "output_base64sha256": b64_hash
    }
    print(json.dumps(result))

if __name__ == "__main__":
    main()