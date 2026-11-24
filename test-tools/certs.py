"""Test certificates for the stand-in servers, made on this computer when first needed.

A real site's certificate cannot be had for a server on this computer, so the tests use a chain of their own:
a test root, an intermediate, and one leaf made out to every name the kernel asks for (the example site, the
provider's site, and the made-up sites the tests of downloads fetch files from), so that one stand-in can answer
for all of them. They are made with OpenSSL (the one that comes
with Git does) into the tests' work folder, never into the project and never into the computer's store of
certificates. A kernel that trusts the test root is only ever built in a copy (see net_copy.py).

    folder = test_keys()   # folder/a/root.der, folder/a/both-chain.pem, folder/a/both.key"""
import os
import shutil
import subprocess

from places import WORK

SITES = ["example.com", "api.orcarouter.ai", "files.example.org", "other.example.net", "api.anthropic.com"]


def openssl():
    found = shutil.which("openssl")
    if found:
        return found
    git = shutil.which("git")
    if git:
        # Git for Windows keeps git.exe in <Git>\cmd and its OpenSSL in <Git>\usr\bin.
        candidate = os.path.join(os.path.dirname(os.path.dirname(git)), "usr", "bin", "openssl.exe")
        if os.path.exists(candidate):
            return candidate
    raise RuntimeError("OpenSSL was not found (it comes with Git for Windows)")


def test_keys():
    folder = os.path.join(WORK, "tls")
    authority = os.path.join(folder, "a")
    # Made anew when the names they were made out to are not the names above.
    names = os.path.join(authority, "names.txt")
    if os.path.exists(os.path.join(authority, "both-chain.pem")) and os.path.exists(names) and open(names).read() == " ".join(SITES):
        return folder
    shutil.rmtree(authority, ignore_errors=True)
    os.makedirs(authority)
    tool = openssl()
    environment = dict(os.environ, MSYS_NO_PATHCONV="1")

    def run(*words):
        subprocess.run([tool] + list(words), cwd=authority, check=True, env=environment,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def key(name):
        run("genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", name + ".key")

    with open(os.path.join(authority, "ca.ext"), "w") as handle:
        handle.write("basicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\n")
    with open(os.path.join(authority, "both.ext"), "w") as handle:
        handle.write("subjectAltName=" + ",".join("DNS:" + site for site in SITES) + "\n"
                     "basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\n")
    key("root")
    run("req", "-x509", "-new", "-key", "root.key", "-sha256", "-days", "3650", "-subj", "/O=boos tests/CN=boos test root a",
        "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign", "-out", "root.pem")
    run("x509", "-in", "root.pem", "-outform", "DER", "-out", "root.der")
    key("inter")
    run("req", "-new", "-key", "inter.key", "-subj", "/O=boos tests/CN=boos test intermediate a", "-out", "inter.csr")
    run("x509", "-req", "-in", "inter.csr", "-CA", "root.pem", "-CAkey", "root.key", "-CAcreateserial", "-days", "1825",
        "-sha256", "-extfile", "ca.ext", "-out", "inter.pem")
    key("both")
    run("req", "-new", "-key", "both.key", "-subj", "/CN=" + SITES[0], "-out", "both.csr")
    run("x509", "-req", "-in", "both.csr", "-CA", "inter.pem", "-CAkey", "inter.key", "-CAcreateserial", "-sha256",
        "-days", "365", "-extfile", "both.ext", "-out", "both.pem")
    with open(os.path.join(authority, "both-chain.pem"), "wb") as chain:
        for name in ("both.pem", "inter.pem"):
            chain.write(open(os.path.join(authority, name), "rb").read())
    with open(names, "w") as handle:
        handle.write(" ".join(SITES))
    return folder


if __name__ == "__main__":
    print(test_keys())
