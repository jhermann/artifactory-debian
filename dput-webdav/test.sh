#! /bin/bash
set -e
dput=$(which dput-dav >/dev/null && echo "dput-dav" || echo "dput")

fail() { # fail with error message and exit code 1
    echo >&2 "ERROR:" "$@"
    exit 1
}

dput_test() {
    $dput --config dput.cf --debug --force --unchecked "$@"
}

mkdir -p build
export PRJDIR=$(cd $(dirname "$0") && pwd)
export ARTIFACTORY_CREDENTIALS="uploader:password"
echo "$ARTIFACTORY_CREDENTIALS" >build/artifactory-credentials

echo
echo "*** Python unit tests **"
python -m webdav

if test $(ls -1 build/*.changes | wc -l) -ne 1; then
    echo
    echo "*** Preparing test package **"
    rm -rf build/artifactory-debian-webdav-test* build/deb 2>/dev/null || :
    mkdir -p build/deb
    pushd build/deb >/dev/null
    echo | dh_make -s --indep --createorig -p artifactory-debian-webdav-test_1.0
    dpkg-buildpackage -uc -us 
    popd >/dev/null
fi

echo
echo "*** Printing effective test config **"
dput_test --print

echo
echo "*** $dput integration test - simulating an upload **"
test -r "/usr/share/dput/webdav.py" || fail "You need to install webdav.py to /usr/share/dput"
dput_test 'artifactory-debian:integration-test;repo=foo+bar' build/*.changes | tee build/dput.log
set +x
grep ".repo.: .foo bar." build/dput.log >/dev/null || fail "Host argument passing doesn't work"
grep "^D: webdav: Resolved login credentials to uploader:\\*" build/dput.log >/dev/null \
    || fail "Login env / file reference not resolved"

echo
if grep ".extended_info.: .1.," build/dput.log >/dev/null; then
    echo "INFO: You're running a successfully patched $dput with extended plugin info available."
else
    echo "WARN: You're running an unpatched $dput without extended plugin info," \
        "some 'webdav' features might be missing."
fi

echo
echo "** ALL OK **"

