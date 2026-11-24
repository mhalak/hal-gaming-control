# Third-party notices — Windows preview package

**Status: technical inventory, complete for the Windows 0.4.3 candidate;
several items are NOT CONFIRMED (section 6).** This file records what the
public Windows ZIP contains and what each upstream's own files say about its
license. It is an engineering inventory, **not legal advice and not a finished
compliance review**. First-party code is MIT-licensed ([LICENSE](LICENSE)).
Tracking issue: [#9](https://github.com/mhalak/hal-gaming-control/issues/9).

**Important:** the previously audited Windows ZIP from Actions run
`45459711030` lacked the project's `LICENSE`, this inventory, and most
upstream license texts. The new *source-only* preview packaging workflow
requires the project documents and stages the license texts found in the
exact-version installed Python/wheel distributions. This improvement **has
not yet been acceptance-tested against a newly built Windows ZIP**, and it
does **not** resolve the redistribution questions in section 6. See section 9.

## 1. Evidence and method

| Item | Value |
| --- | --- |
| Inspected build | Actions run `45459711030` (owner-triggered unsigned candidate), source `10d59d7`, artifact `UNSIGNED-windows-candidate-45459711030` (ID `14951773193`), archive digest `sha256:ab7e9c017cc9641b9485445585697a98743a17d2163d9398a50970dc74e63dc8` (re-computed locally: matches) |
| Same source as current `main`? | `windows_agent/` and `release.json` are byte-identical between `10d59d7` and `1b52844` (Windows 0.4.3); only workflows/docs/tools differ |
| Versions installed by CI | `pip install` log of that run: `PyYAML-6.0.4 cffi-2.1.1 cryptography-50.0.2 paho-mqtt-2.2.0 psutil-7.2.2 pycparser-3.12 pyinstaller-6.22.3 pyinstaller-hooks-contrib-2026.10 pywin32-312` (+ build/test-only packages, section 4) |
| Python | `3.12.10` (PyInstaller log line `Python: 3.12.10`, `actions/setup-python` `3.12`) |
| What is inside | Artifact unpacked and both PyInstaller archives read with PyInstaller's own archive reader (PYZ module list, bundled binaries, data files, dist-info) |
| Upstream metadata | Same-version wheels fetched from PyPI (`pip download --no-deps`, SHA-256 compared with the PyPI JSON digests); `METADATA` and license files read from the wheels. Wheel bytes are the PyPI files of the same name/version; the CI log does not print hashes, so identical bytes to CI's install are not proven. `cryptography` dist-info files in the artifact are byte-identical to the wheel's |
| Version resources | `pefile` read of the DLLs/PYDs in the artifact |

The ZIP published by the (not yet run) Pages workflow is assembled from the
same `build.ps1` output: `SmartHouseGamingControl/` and
`SmartHouseGamingUpdater/` onedir folders, `install.ps1`,
`install_helpers.ps1`, `uninstall.ps1`, `config.example.yaml`
(`tools/windows_download_page.py`).

## 2. First-party content (MIT)

`SmartHouseGamingControl.exe`, `SmartHouseGamingUpdater.exe` (project code
embedded in the PyInstaller archives), `install.ps1`, `install_helpers.ps1`,
`uninstall.ps1`, `config.example.yaml`, `version.txt`, `build-info.json`.
The three Python/PowerShell sources are covered by the repository
[LICENSE](LICENSE); no MIT text is shipped inside the ZIP today.

## 3. Components that are inside the ZIP

The table below describes the **historical audited candidate** from run
`45459711030`, not a future Pages ZIP that has not yet been published.
"Text in ZIP" = whether the upstream license text was physically present in
that audited candidate. "Confirmed" = license identified from a primary source
(package metadata/license file, version resource, or upstream tag).

| Component | Version | License (as stated) | Evidence | Text in ZIP | Confirmed |
| --- | --- | --- | --- | --- | --- |
| CPython runtime (`python312.dll`, stdlib in `base_library.zip`/PYZ, `_*.pyd`) | 3.12.10 | PSF License (Python License 2.0 and historical terms) | `python312.dll` version resource "Python Software Foundation 3.12.10"; [`LICENSE` at tag v3.12.10](https://raw.githubusercontent.com/python/cpython/v3.12.10/LICENSE) | No | Yes |
| OpenSSL (`libcrypto-3.dll`, `libssl-3.dll`, used by `_ssl`/`_hashlib`) | 3.0.16 | Apache-2.0 | DLL version resource "OpenSSL 3.0.16", string `OpenSSL 3.0.16 11 Feb 2025`; [`LICENSE.txt` at tag openssl-3.0.16](https://raw.githubusercontent.com/openssl/openssl/openssl-3.0.16/LICENSE.txt) is Apache License 2.0 | No | Yes |
| zlib (`zlib1.dll`, service package only) | 1.3.1 | zlib license | DLL version resource "zlib 1.3.1"; [`LICENSE` at tag v1.3.1](https://raw.githubusercontent.com/madler/zlib/v1.3.1/LICENSE) | No | Yes |
| libffi (`libffi-8.dll`) | 3.4.4 (inferred) | MIT-style | DLL has no version resource; CPython 3.12.10 `PCbuild/get_externals.bat` pins `libffi-3.4.4`; [`LICENSE` at tag v3.4.4](https://raw.githubusercontent.com/libffi/libffi/v3.4.4/LICENSE) | No | License yes; exact version inferred |
| Tcl/Tk (`tcl86t.dll`, `tk86t.dll`, `_tcl_data/`, `_tk_data/`, `tcl8/`; service package only, via `--hidden-import tkinter`) | 8.6.15 | Tcl/Tk license (BSD-style `license.terms`) | DLL version resources "Tcl 8.6.15 / Tk 8.6.15"; `_tk_data/license.terms` is shipped | Yes (`_internal/_tk_data/license.terms`, Tk only) | Yes |
| Microsoft C/C++ runtime (`VCRUNTIME140.dll`, `VCRUNTIME140_1.dll`) | 14.42.34438.0 | Microsoft redistributable terms | DLL version resources | No | **NOT CONFIRMED** (no terms text inspected) |
| Microsoft Universal CRT (`ucrtbase.dll`, 42 `api-ms-win-*.dll` stubs) | 10.0.26100.1742 | Microsoft redistributable terms | DLL version resources ("Microsoft Windows Operating System") | No | **NOT CONFIRMED** (no terms text inspected) |
| cryptography (`cryptography/`, `_rust.pyd`) | 50.0.2 | `Apache-2.0 OR BSD-3-Clause` | wheel `License-Expression`; `dist-info/licenses/{LICENSE,LICENSE.APACHE,LICENSE.BSD}` | **Yes** (both packages) | Yes |
| - OpenSSL statically linked into `_rust.pyd` | 4.0.3 | Apache-2.0 | shipped `dist-info/sboms/sbom.json` (`openssl` 4.0.3, flags `no-shared`); [`LICENSE.txt` at tag openssl-4.0.3](https://raw.githubusercontent.com/openssl/openssl/openssl-4.0.3/LICENSE.txt) is Apache License 2.0 | No | Yes |
| - 39 statically linked Rust crates | see SBOM | Per shipped `sboms/cryptography-rust.cyclonedx.json`: 23 `MIT OR Apache-2.0`, 7 `Apache-2.0 OR BSD-3-Clause`, 2 `BSD-3-Clause`, 2 `MIT`, 1 `Apache-2.0`, 1 `Apache-2.0 OR MIT`, 1 `Apache-2.0 OR GPL-2.0-only` (`self_cell`), 1 `Apache-2.0 WITH LLVM-exception` (`target-lexicon`), 1 `(MIT OR Apache-2.0) AND Unicode-3.0` (`unicode-ident`) | shipped SBOM (license expressions only) | Only the SBOM | Expressions yes; per-crate copyright notices **NOT CONFIRMED** |
| cffi backend (`_cffi_backend.cp312-win_amd64.pyd`; the `cffi` Python package is not in the PYZ) | 2.1.1 | `MIT-0` | wheel `License-Expression`; `LICENSE` ("MIT No Attribution") | No (none required by MIT-0) | Yes for cffi; statically linked code inside the PYD not examined |
| paho-mqtt (`paho/`, pure Python in PYZ) | 2.2.0 | `EPL-2.0 OR BSD-3-Clause` (EDL-1.0) | wheel `License-Expression`; `dist-info/licenses/{LICENSE.txt,edl-v10,epl-v20}` | No | Yes |
| psutil (`psutil/`, `_psutil_windows.pyd`) | 7.2.2 | BSD-3-Clause | wheel `License: BSD-3-Clause`; `dist-info/LICENSE` | No | Yes |
| PyYAML (`yaml/`, `_yaml.cp312-win_amd64.pyd`) | 6.0.4 | MIT | wheel `License: MIT`, classifier MIT; `dist-info/licenses/LICENSE` | No | Yes for PyYAML; a statically linked libyaml in `_yaml.pyd` is **NOT CONFIRMED** (not stated in the wheel; the PYD has no readable version string) |
| pywin32 (`win32/*.pyd` x14, `pywin32_system32/pywintypes312.dll`, PYZ: `pywintypes`, `win32con`, `win32serviceutil`, `win32timezone`, `win32evtlogutil`, `winerror`; service package only) | 312 | Metadata says `PSF` (classifier "Python Software Foundation License"); the shipped license texts (`win32/License.txt`, `com/License.txt`) are BSD-3-Clause-style (Mark Hammond; Greg Stein and Mark Hammond) | wheel `METADATA` and `dist-info/licenses/**` | No | **Partly**: metadata and license text disagree, which is not resolved here |
| PyInstaller bootloader and loader (embedded in both EXEs: `run.exe` bootloader; `pyimod01_archive`, `pyimod02_importers`, `pyimod03_ctypes`, `pyimod04_pywin32`, `pyiboot01_bootstrap`) | 6.22.3 | `GPL-2.0-or-later WITH Bootloader-exception` | wheel `License` metadata and `COPYING.txt` (section 5.1) | No | Yes |
| PyInstaller run-time hooks embedded (`pyi_rth__tkinter`, `pyi_rth_inspect`) | 6.22.3 | Apache-2.0 | `COPYING.txt`: run-time hooks in `PyInstaller/hooks/rthooks` are Apache-2.0; both files are present there | No | Yes |
| pyinstaller-hooks-contrib run-time hooks embedded (`pyi_rth_cryptography_openssl`, `pyi_rth_pywintypes`) | 2026.10 | Apache-2.0 (run-time hooks); standard hooks are GPL-2.0-or-later but are build-time only | `dist-info/licenses/LICENSE`; both files are in `_pyinstaller_hooks_contrib/rthooks` | No | Yes (wheel has no `License-Expression`; classifiers list Apache and GPLv2) |
| Tcl time-zone data (`_tcl_data/tzdata/**`) and Tcl message/encoding files | with Tcl 8.6.15 | No license file shipped | none in package | No | **NOT CONFIRMED** |
| Tk logo images (`_tk_data/images/*.gif`, `*.eps`, `README`) | with Tk 8.6.15 | The shipped `images/README` says the Tcl Powered logo may be used on products that employ Tcl/Tk | `_tk_data/images/README` | Yes (README) | As stated by the README; no further license text |
| Default EXE icon | PyInstaller 6.22.3 | Not stated separately in `COPYING.txt` | `build.ps1` passes no `--icon`, so PyInstaller's default icon (`PyInstaller/bootloader/images/icon-console.ico`) is expected; not verified inside the built EXE | n/a | **NOT CONFIRMED** |

## 4. Build/test-only packages (not in the ZIP)

Present in the CI virtualenv, verified absent from both PYZ archives and from
`_internal/` (only `cryptography-50.0.2.dist-info` exists as dist-info):

| Package | Version | License (metadata) | Role |
| --- | --- | --- | --- |
| PyInstaller (tool itself, apart from the embedded parts above) | 6.22.3 | GPL-2.0-or-later with exception | build tool |
| pyinstaller-hooks-contrib (standard hooks) | 2026.10 | GPL-2.0-or-later | build-time hooks |
| altgraph | 0.17.5 | MIT | PyInstaller dependency |
| pefile | 2024.8.26 | MIT | PyInstaller dependency |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause | PyInstaller dependency |
| packaging | 26.4 | `Apache-2.0 OR BSD-2-Clause` | PyInstaller dependency |
| setuptools | 84.2.1 | MIT (plus vendored packages with their own license files) | PyInstaller dependency |
| pycparser | 3.12 | BSD-3-Clause | cffi dependency; not in the package |
| pytest, pluggy, iniconfig, colorama, pygments | 9.2.0, 1.7.0, 2.3.1, 0.4.6, 2.21.0 | not examined | test only (`requirements-dev.txt`) |

## 5. Notices and exceptions that matter

### 5.1 PyInstaller Bootloader Exception (verbatim, from `COPYING.txt` of 6.22.3)

> In addition to the permissions in the GNU General Public License, the
> authors give you unlimited permission to link or embed compiled bootloader
> and related files into combinations with other programs, and to distribute
> those combinations without any restriction coming from the use of those
> files. (The General Public License restrictions do apply in other respects;
> for example, they cover modification of the files, and distribution when
> not linked into a combined executable.)

"Bootloader and related files" are the files embedded in the final
executable, including `./bootloader/` and `./PyInstaller/loader`. PyInstaller's
run-time hooks (`./PyInstaller/hooks/rthooks`) and fake modules are
Apache-2.0 instead. SPDX banner used by PyInstaller:
`GPL-2.0-or-later WITH Bootloader-exception`. The project does not modify
PyInstaller; this inventory does not decide whether any further obligation
applies to the unmodified bootloader.

### 5.2 Dual licenses: you choose one

`cryptography` (`Apache-2.0 OR BSD-3-Clause`), `paho-mqtt`
(`EPL-2.0 OR BSD-3-Clause`; the BSD-3-Clause text is Eclipse Distribution
License 1.0, shipped as `edl-v10`). The inventory does not record which
alternative the project elects; ship the upstream license files so recipients
see both.

### 5.3 pywin32

Metadata says PSF; the license files in the wheel (`win32/License.txt`,
`com/License.txt`, `pythonwin/License.txt`) are BSD-3-Clause-style, which
requires reproducing the copyright notice and disclaimer in binary
distributions. Resolve against upstream before publication. The MAPI MIT
notice in the wheel (`win32comext/mapi/NOTICE.md`) concerns `mapi.pyd` and
`exchange.pyd`, which are **not** in the package.

### 5.4 Permissive licenses that expect notice retention

BSD-3-Clause (`psutil`, `paho-mqtt` EDL path, `pywin32`), MIT (`PyYAML`,
libffi), Apache-2.0 (OpenSSL, `cryptography` path), zlib, Tcl/Tk and PSF terms
generally ask that the copyright notice and license text accompany binary
redistributions. Only `cryptography`'s and Tk's texts do today.

## 6. NOT CONFIRMED items

1. Microsoft VC++ runtime and Universal CRT/ApiSet DLLs: redistribution terms
   not inspected; owner must confirm they may be redistributed in a ZIP from
   this build (they are Microsoft-signed; do not re-sign).
2. pywin32: `PSF` metadata versus BSD-3-Clause-style shipped license texts.
3. Per-crate copyright notices of the 39 Rust crates linked into
   `cryptography`'s `_rust.pyd` (only SBOM expressions are shipped).
4. Whether `yaml/_yaml*.pyd` statically links libyaml, and under which
   notice.
5. Static content of `_cffi_backend*.pyd`, `psutil/_psutil_windows.pyd`.
6. Tcl time-zone data, Tcl message/encoding files: no license file shipped.
7. Default PyInstaller EXE icon provenance/license.
8. libffi exact version (inferred from the CPython 3.12.10 source tree).
9. Build reproducibility of this list (see findings).

## 7. Findings

- **Earlier candidate used version ranges.** The new Pages workflow uses
  `windows_agent/preview-constraints.txt` and an audited version snapshot
  for the Windows runtime and PyInstaller distributions. This is **not yet a
  SHA-256 wheel hash lock**, and PyInstaller transitive build/test packages
  have not all been frozen. Runtime/version mismatches fail the new
  collection stage; full build reproducibility remains outstanding.
- **Earlier candidate omitted notices.** The new package builder requires
  root `LICENSE` and `THIRD_PARTY_NOTICES.md`, plus the staged wheel and
  CPython license files and their SHA-256 manifest. A future Pages ZIP
  cannot be built without these files. Licensing of all embedded native
  dependencies has **not** been established by those mechanical checks.
- Most runtime components (CPython, OpenSSL 3.0.16, zlib, libffi, paho-mqtt,
  psutil, PyYAML, pywin32, PyInstaller, Microsoft runtimes) ship binaries
  without their license text.
- The Pages HTML page links source and policy documents, not this file.

## 8. Artwork and other resources

- **What the ZIP carries:** no project image, icon, font or sound file. The
  popup (`windows_agent/gaming_control/popup_helper.py`) draws its brand glyph
  with Tk `Canvas` primitives (code comment: "no remote images or executable
  themes") and requests the font family name `Segoe UI`; it is a Windows
  system font that is **not** bundled. The only images inside the package are
  Tcl/Tk's own logos (section 3).
- **Documented provenance in the repository** ([ASSETS.md](ASSETS.md)): the
  README banner `docs/assets/banner.png` and the integration icons
  `custom_components/hal_gaming_control/brand/icon.png` and `icon@2x.png`
  are "ChatGPT-generated; owner-authorized redistribution". ASSETS.md states
  it is the owner's provenance and redistribution authorization, **not** a
  representation of exclusive copyright ownership, third-party licensing or
  trademark clearance. These three files are **not** part of the Windows ZIP.
- **Missing documentation:** `docs/assets/illustrations/local-mode.png`
  (used in the README and `docs/features/local-mode.md`) is not listed in
  ASSETS.md and has no recorded provenance or license; it is not part of the
  Windows ZIP. No provenance or license record exists for any future Windows
  icon, installer artwork or font. Nothing in this section asserts legal
  permissibility of any asset.

## 9. Packaging implementation and outstanding compliance work

The Windows Pages publishing source now stages source texts found in the
exact installed `Python 3.12.10` interpreter and audited wheel
distributions using `tools/windows_preview_licenses.py`.
`tools/windows_download_page.py` requires those staged files with their
SHA-256 manifest, and includes `LICENSE` and `THIRD_PARTY_NOTICES.md`
at the ZIP root. Missing, modified or version-mismatched notices **block
packaging**. The manual publishing workflow remains owner-authorized only.

**This is not clearance to distribute.** The staged texts do not establish
permission to redistribute Microsoft VC++/UCRT DLLs, and do not necessarily
cover separately embedded OpenSSL, zlib, libffi, libyaml, Tcl or other static
libraries, Rust crates and PyInstaller icon resources. Resolve section 6
using upstream terms and primary evidence, collect any additionally required
license/attribution texts, create a reproducible hashed dependency lock,
and validate the resulting **real Windows ZIP** before asking the owner for
a separate public UNSIGNED-release approval. No SignPath application or
trusted Windows release has been submitted/published by this implementation.
