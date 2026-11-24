"""A copy of the project whose kernel fetches its page from a test server on this computer instead of from the
real site. The edits are made in the copy only; one of them adds trusted roots, which must never reach the
real project.

    kernel = build(port, roots=["a", "b"], extra=None)

`roots` names the test authorities (folders under tls/) whose roots are added to the kernel's list; an empty
list leaves the kernel's own 112. The copy also prints a digest of everything that arrived through the link.

With BOOS_PROVIDER=anthropic, every line of the copy goes to Anthropic (suites.py, "... with Anthropic"): a notebook
without a word about the provider means Anthropic, and Anthropic's key is kept under OrcaRouter's name, so that the
disks and the steps of the tests made for OrcaRouter serve as they are.

The copy lies in BOOS_COPIES when that is set (run_tests.py shares one copy among the tests it runs at once), and in
this checkout's work folder otherwise. It is changed and built in the build turn (turns.py), and the kernel that
build() gives back is a copy of its own in the test's work folder, so the next build cannot change it."""
import os
import shutil
import subprocess
import sys

from certs import test_keys
from places import PROJECT, RUNS, WASM
from turns import build_turn

COPY = os.path.join(os.environ.get("BOOS_COPIES") or RUNS, "net-copy")


def swap(text, old, new, count=1):
    assert text.count(old) == count, (old[:70], text.count(old))
    return text.replace(old, new)


def fresh():
    """Brings the copy's sources up to date with the project's; keeps the copy's build folder."""
    os.makedirs(COPY, exist_ok=True)
    for name in ["src", "vendor", ".cargo", "interpreter", "password-key"]:
        target = os.path.join(COPY, name)
        if name == "interpreter":
            shutil.rmtree(os.path.join(target, "src"), ignore_errors=True)
            os.makedirs(os.path.dirname(os.path.join(COPY, WASM)), exist_ok=True)
            shutil.copyfile(os.path.join(PROJECT, WASM), os.path.join(COPY, WASM))
            continue
        if name == "vendor" and os.path.exists(target):
            continue
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(os.path.join(PROJECT, name), target)
        # copytree keeps the files' old times, and cargo would then take an earlier build (with a break in it)
        # for up to date. New times make it build the copy's sources as they are now.
        if name == "src":
            for root, _, files in os.walk(target):
                for file in files:
                    os.utime(os.path.join(root, file), None)
    for name in ["Cargo.toml", "Cargo.lock"]:
        shutil.copyfile(os.path.join(PROJECT, name), os.path.join(COPY, name))


def build(port, roots=(), more=None, redirect=True):
    """With redirect=False the copy talks to the real sites, as the project's kernel does; only `more` differs."""
    with build_turn():
        built = _build(port, roots, more, redirect)
        kernel = os.path.join(RUNS, "net-copy-kernel.efi")
        os.makedirs(RUNS, exist_ok=True)
        shutil.copyfile(built, kernel)
    return kernel


def _build(port, roots, more, redirect):
    fresh()
    path = os.path.join(COPY, "src", "page.rs")
    page = open(path, "rb").read().decode().replace("\r\n", "\n")
    if redirect:
        page = swap(page, "const WEB_PORT: u16 = 443;", "const WEB_PORT: u16 = %d; // TEST" % port)
        page = swap(page, "    let address = name_lookup(interface, card, sockets, name_server, site)?;\n",
                    "    let _ = name_server;\n    let address = IpAddress::v4(10, 0, 2, 2); // TEST: the test server, no name question\n")
    page = swap(page, "    let mut answer = Answer::new();\n", "    let mut answer = Answer::new();\n    let mut test_digest = <sha2::Sha256 as sha2::Digest>::new(); // TEST\n    let mut test_count = 0usize;\n")
    page = swap(page, "        for byte in bytes {\n            answer.take(*byte);\n        }\n        true\n    })?;\n",
                "        sha2::Digest::update(&mut test_digest, bytes);\n        test_count += bytes.len();\n        for byte in bytes {\n            answer.take(*byte);\n        }\n        true\n    })?;\n"
                "    {\n        let done = sha2::Digest::finalize(test_digest);\n        let mut hex = alloc::string::String::new();\n        for byte in done.iter() {\n            hex.push_str(&format!(\"{:02x}\", byte));\n        }\n"
                "        serial_print(&format!(\"TEST digest {} of {} bytes\\r\\n\", hex, test_count));\n    }\n")
    if more and "page" in more:
        page = more["page"](page)
    open(path, "w", newline="").write(page)

    path = os.path.join(COPY, "src", "encryption.rs")
    code = open(path, "rb").read().decode().replace("\r\n", "\n")
    if roots:
        tls = test_keys().replace("\\", "/")
        files = ", ".join('include_bytes!("%s/%s/root.der")' % (tls, name) for name in roots)
        code = swap(code, "    rustls::RootCertStore::from_iter(webpki_roots::TLS_SERVER_ROOTS.iter().cloned())\n",
                    "    let mut roots = rustls::RootCertStore::from_iter(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());\n"
                    "    let test_roots: &[&[u8]] = &[%s]; // TEST: never in the real project\n" % files +
                    "    for der in test_roots {\n        roots.add(rustls::pki_types::CertificateDer::from(*der)).expect(\"a test root\");\n    }\n    roots\n")
    open(path, "w", newline="").write(code)
    if os.environ.get("BOOS_PROVIDER") == "anthropic":
        path = os.path.join(COPY, "src", "onboarding.rs")
        code = open(path, "rb").read().decode().replace("\r\n", "\n")
        code = swap(code, "static mut PROVIDER: Provider = Provider::OrcaRouter;\n", "static mut PROVIDER: Provider = Provider::Anthropic; // TEST\n")
        code = swap(code, "        Ok(Some(kept)) if kept == ANTHROPIC_KEPT => Provider::Anthropic,\n        _ => Provider::OrcaRouter,\n",
                    "        Ok(Some(kept)) if kept == ORCAROUTER_KEPT => Provider::OrcaRouter, // TEST\n        _ => Provider::Anthropic,\n")
        code = swap(code, "        Provider::Anthropic => ANTHROPIC_KEY_ENTRY,\n", "        Provider::Anthropic => KEY_ENTRY, // TEST\n")
        open(path, "w", newline="").write(code)
    if more:
        for name, change in more.items():
            if name in ("page", "interpreter"):
                continue
            path = os.path.join(COPY, "src", name)
            text = open(path, "rb").read().decode().replace("\r\n", "\n")
            open(path, "w", newline="").write(change(text))
    if more and "interpreter" in more:
        # A change to the interpreter's own source: the copy gets the interpreter's files, the change, and a
        # build of its own, whose file then takes the place of the project's in the copy.
        inner = os.path.join(COPY, "interpreter")
        for name in ["Cargo.toml", "Cargo.lock", os.path.join(".cargo", "config.toml"), os.path.join("src", "lib.rs")]:
            os.makedirs(os.path.dirname(os.path.join(inner, name)), exist_ok=True)
            shutil.copyfile(os.path.join(PROJECT, "interpreter", name), os.path.join(inner, name))
        path = os.path.join(inner, "src", "lib.rs")
        text = open(path, "rb").read().decode().replace("\r\n", "\n")
        open(path, "w", newline="").write(more["interpreter"](text))
        built = subprocess.run(["cargo", "build", "--release"], cwd=inner, capture_output=True, text=True)
        if built.returncode != 0:
            print("THE COPY'S INTERPRETER DID NOT BUILD")
            print(built.stderr[-3000:])
            sys.exit(1)

    kernel = os.path.join(COPY, "target", "x86_64-unknown-uefi", "debug", "boos.efi")
    # Removed first, so that a failed build can never leave an earlier build's kernel (with a break in it) behind.
    if os.path.exists(kernel):
        os.remove(kernel)
    built = subprocess.run(["cargo", "build"], cwd=COPY, capture_output=True, text=True)
    if built.returncode != 0 or not os.path.exists(kernel):
        print("THE COPY'S BUILD FAILED")
        print(built.stderr[-3000:])
        sys.exit(1)
    return kernel
