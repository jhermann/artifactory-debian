#! /bin/bash
set -e
##dput=$(which dput-dav >/dev/null && echo "dput-dav" || echo "dput")

fail() { # fail with error message and exit code 1
    echo >&2 "ERROR:" "$@"
    exit 1
}

dput_test() {
    $dput --config dput.cf --debug --force --unchecked "$@"
}

export PRJDIR=$(cd $(dirname "$0") && pwd)
cd "$PRJDIR"
mkdir -p build

export ARTIFACTORY_CREDENTIALS="uploader:password"
echo "$ARTIFACTORY_CREDENTIALS" >build/artifactory-credentials

# Link dputhelper, so pylint finds it
ln -nfs /usr/share/dput/helper/dputhelper.py .

# Make a copy of dput that finds our plugin
dput=$PRJDIR/build/dput
sed -re "s:/usr/share/dput/\\*\\.py:$PRJDIR/build/plugins/*.py:" </usr/bin/dput >$dput
patch $dput <dput.patch
chmod a+x $dput
mkdir -p build/plugins
ln -nfs /usr/share/dput/*.py build/plugins
ln -nfs "../../webdav.py" build/plugins

echo
echo "*** Python unit tests **"
python -m webdav

if test $(ls -1 build/artifactory-debian-webdav-test*.changes | wc -l) -ne 1; then
    echo
    echo "*** Preparing test package **"
    rm -rf build/artifactory-debian-webdav-test* build/deb 2>/dev/null || :
    mkdir -p build/deb
    pushd build/deb >/dev/null
    export DEBFULLNAME="Tests R. Us"
    export DEBEMAIL="tests@example.com"
    echo | dh_make -s --indep --createorig -p artifactory-debian-webdav-test_1.0
    dpkg-buildpackage -uc -us
    popd >/dev/null
fi

echo
echo "*** Test package metadata **"
dpkg-deb -I build/artifactory-debian-webdav-test*.deb

echo
echo "*** Printing effective test config **"
dput_test --print

echo
echo "*** $dput integration test - simulating an upload **"
##test -r "/usr/share/dput/webdav.py" || fail "You need to install webdav.py to /usr/share/dput"
( dput_test 'artifactory-debian:integration-test;repo=foo+bar' build/*.changes 2>&1 || echo "FAILURE: RC=$?" ) \
    | tee build/dput.log
set +x
egrep "^(FAILURE|FATAL|ERROR): " build/dput.log && fail "dput exited with an error" || :
grep ".repo.: .foo bar." build/dput.log >/dev/null || fail "Host argument passing doesn't work"
grep "^D: webdav: Resolved login credentials to uploader:\\*" build/dput.log >/dev/null \
    || fail "Login env / file reference not resolved"

dput_test 'artifactory-debian:integration-test' build/*.changes >build/dput2.log 2>&1 || :
grep "/debian-local/snapshots/" build/dput2.log >/dev/null || fail "Repository mapping doesn't work"

. .env --yes

echo
if which pylint >/dev/null; then
    echo "Running $(pylint --version | head -n1) from '$(which pylint)'..."
    pylint --rcfile ./pylint.cfg -d locally-disabled -rn webdav.py && RC=0 || RC=$?
    test $(($RC & 35)) -eq 0 || fail "pylint errors!"
else
    echo "WARN: You don't have pylint installed!"
fi

#echo
#if grep ".extended_info.: .1.," build/dput.log >/dev/null; then
#    echo "INFO: You're running a successfully patched $dput with extended plugin info available."
#else
#    echo "WARN: You're running an unpatched $dput without extended plugin info," \
#        "some 'webdav' features might be missing."
#fi

echo
echo "** ALL OK **"
