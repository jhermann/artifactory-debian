#! /bin/bash
#
# Debian packaging for a release
#
set -e

root=$(cd $(dirname "$0") && pwd)
cd "$root"

rm ../dput-webdav_[0-9]* || :
dpkg-buildpackage -uc -us $(sed -e 's/^/--source-option=-I/' <.gitignore)

echo
tar tvfz ../dput-webdav_*.tar.gz
echo
dpkg-deb -c ../dput-webdav_*.deb
echo
dpkg-deb -I ../dput-webdav_*.deb
