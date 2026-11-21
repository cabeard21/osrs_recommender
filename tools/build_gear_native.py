"""Explicit optional desktop extension build: python -m tools.build_gear_native.

Install the native-build extra first. Standard package installation never invokes
this helper or requires a compiler. Generated build products are ignored.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import json
import os
import shutil
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--coverage", action="store_true", help="Build separate traced test binaries"
    )
    args = parser.parse_args()
    try:
        import Cython
        from Cython.Build import cythonize
        from setuptools import Distribution, Extension
    except ImportError as exc:
        raise SystemExit(
            "Install optional build tools: python -m pip install -e .[native-build]"
        ) from exc
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    # Relative sources prevent distutils from duplicating the full checkout path
    # inside the object directory, exceeding MSVC's path limit on long worktrees.
    build = Path(".tmp") / "native-build" / ("coverage" if args.coverage else "release")
    build.mkdir(parents=True, exist_ok=True)
    from tracker.gear.native.readiness import MODULES

    extensions = [
        Extension(
            f"tracker.gear.native.{name}",
            [str(Path("tracker") / "gear" / "native" / f"{name}.pyx")],
            language="c++",
            define_macros=[("CYTHON_TRACE_NOGIL", "1")] if args.coverage else [],
            extra_compile_args=["/O2", "/fp:strict", "/std:c++17"]
            if os.name == "nt"
            else ["-O3", "-ffp-contract=off", "-std=c++17"],
        )
        for name in MODULES
    ]
    distribution = Distribution(
        {
            "name": "gear-native-experiment",
            "ext_modules": cythonize(
                extensions,
                build_dir=str(build / "generated"),
                compiler_directives={"language_level": 3, "linetrace": args.coverage},
                force=True,
            ),
        }
    )
    command = distribution.get_command_obj("build_ext")
    command.inplace = True
    command.build_temp = str(build / "temp")
    command.build_lib = str(build / "lib")
    distribution.run_command("build_ext")
    # Cython.Coverage discovers generated source beside the extension. Keeping
    # this ignored copy makes traced native lines visible to coverage.py.
    for name in MODULES:
        shutil.copyfile(
            build / "generated" / "tracker" / "gear" / "native" / f"{name}.cpp",
            root / "tracker" / "gear" / "native" / f"{name}.cpp",
        )
    compiler_path = Path(command.compiler.cc)
    binaries = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for name in MODULES
        for suffix in importlib.machinery.EXTENSION_SUFFIXES
        for path in [root / "tracker" / "gear" / "native" / f"{name}{suffix}"]
        if path.is_file()
    }
    metadata = {
        "cython_version": Cython.__version__,
        "python_version": sys.version,
        "coverage": args.coverage,
        "compile_args": extensions[0].extra_compile_args,
        "compiler_path": str(compiler_path),
        "compiler_sha256": hashlib.sha256(compiler_path.read_bytes()).hexdigest(),
        "binary_hashes": binaries,
        "source_hashes": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((root / "tracker" / "gear" / "native").iterdir())
            if path.suffix in {".pyx", ".pxd", ".pxi"}
        },
    }
    from tracker.gear.native.readiness import MANIFEST, release_manifest

    native_dir = root / "tracker" / "gear" / "native"
    (native_dir / MANIFEST).write_text(
        json.dumps(release_manifest(native_dir, coverage=args.coverage), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (root / ".tmp" / "native-build" / "last-build.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
