#! /bin/bash
#
# Quick&dirty Debian packaging
#
set -e

root=$(cd $(dirname "$0") && pwd)
pkgdir=dput-dav-0~$(date +'%Y.%m.%d')+git.$(git rev-parse HEAD)

rm -rf build/dput-dav_* build/$pkgdir 2>/dev/null || :
mkdir -p build/$pkgdir
pushd build/$pkgdir >/dev/null

echo "*** Building in $pkgdir"
set +x
cp "$root"/webdav.py .
cp -p /usr/bin/dput dput-dav
patch dput-dav <"$root"/dput.patch

export DEBFULLNAME="Juergen Hermann"
export DEBEMAIL="jh@web.de"
echo | dh_make -s --indep --createorig --native --copyright gpl2

git log -1 | while read line; do
    dch "$line"
done

cat >"debian/install" <<'EOF'
dput-dav usr/bin
webdav.py usr/share/dput
EOF

sed -i -e 's~^Homepage: .*$~Homepage: https://github.com/jhermann/artifactory-debian~' debian/control
sed -i -e 's/^Description: .*$/Description: dput derivative with extended WebDAV support/' debian/control
sed -i -e "s/^.*long desc.*\$/ Built for $(dput --version)./" debian/control
sed -i -e 's/^Depends: /Depends: dput, /' debian/control

dpkg-buildpackage -uc -us
popd >/dev/null

echo
dpkg-deb -c build/dput-dav_*.deb
echo
dpkg-deb -I build/dput-dav_*.deb
