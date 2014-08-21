#! /bin/bash
#
# Index a set of Debian repos located in Artifactory
#
# Call "sudo deb-reindex.sh setup <repo-url>" before first use
#
# See https://github.com/jhermann/artifactory-debian/blob/master/README.md for more
#

set -e

action="$1"
repo_name="debian-local"
repo_url="${2:-$ARTIFACTORY_URL}" # e.g. http://repo.example.com/artifactory/
: ${repo_url:?"You MUST provide a repository URL as a parameter or in ARTIFACTORY_URL"}
repo_url="${repo_url%/}/$repo_name/"
repo_mount="/mnt/artifactory-$repo_name"
davfs_options="auto,_netdev,noexec,ro,uid=davfs2,gid=users,file_mode=440,dir_mode=550"
confdir="$(pwd)" # $(cd $(dirname "$0") && pwd)


fail() { # fail with error message and exit code 1
    echo >&2 "ERROR:" "$@"
    exit 1
}


repo_credentials() { # get credentials for uploading to Artifactory
    if test -n "$ARTIFACTORY_CREDENTIALS"; then
        echo "$ARTIFACTORY_CREDENTIALS"
    elif test -f ~/.artifactory.credentials; then
        cat ~/.artifactory.credentials
    else
        fail "Artifactory deployment credentials are missing"
    fi
}


init() { # initialization checks
    test -n "$repo_url" || fail "You MUST provide the Artifactory repository URL as the 2nd parameter," \
        "or in the ARTIFACTORY_URL environment variable"
}


setup() { # prepare indexing host
    test $(id -u) -eq 0 || fail "Setup must be done as root!"

    set -x
    apt-get install apt-utils curl gzip bzip2 davfs2

    test -d "$repo_mount" || mkdir "$repo_mount"

    grep "^$repo_mount" "/etc/davfs2/secrets" >/dev/null || { \
        echo >>"/etc/davfs2/secrets"; \
        echo "# Artifactory 'debian-local' repository access" >>"/etc/davfs2/secrets"; \
        echo -e "$repo_mount\tXXX_USERNAME_XXX\tXXX_PWD_XXX" >>"/etc/davfs2/secrets"; \
        ${EDITOR:-vi} $(test ${EDITOR:-vi} = "vi" && echo '+' || :) "/etc/davfs2/secrets"; \
    }

    grep "$repo_mount" "/etc/fstab" >/dev/null ||
        echo -e "$repo_url\t$repo_mount\tdavfs\t$davfs_options 0 0" >>"/etc/fstab"

    umount $repo_mount || :
    mount $repo_mount
    set +x

    echo
    echo "Artifactory successfully mounted..."
    mount | grep "$repo_mount"
    ls -l $repo_mount
}


repolabel() { # extract repository name from configuration file path
    local repo
    repo=$(basename "$repo_conf"); repo=${repo%.*}; repo=${repo#repo-}
    echo ${repo}
}


reindex() { # create index files in current working directory
    mkdir -p tmp work; touch {tmp,work}/.deb-index

    # Create writable symlinked tree of read-only repository for indexing
    for repo_conf in $confdir/repo-*.conf; do
        repo=$(repolabel "$repo_conf")
        pushd work >/dev/null
        mkdir -p ${repo}
        find ${repo} -type l -print0 | xargs -0i+ rm "+" # clean existing links

        # make sure we have a proper mount
        test -d $repo_mount/${repo} || fail "$repo_mount/${repo} doesn't exist"

        # link all package subdirs for index creation
        find $repo_mount/${repo} -mindepth 1 -maxdepth 1 -type d | while read subdir; do
            ln -nfs "$subdir" ${repo}/$(basename "$subdir")
        done
        popd >/dev/null
    done

    # Update index databases
    ( cd work && apt-ftparchive generate $confdir/apt-ftparchive.conf )

    # Generate the APT index
    for repo_conf in $confdir/repo-*.conf; do
        repo=$(repolabel "$repo_conf")
        pushd work >/dev/null

        # Create index files
        apt-ftparchive sources ${repo} >${repo}/Sources
        gzip <${repo}/Sources >${repo}/Sources.gz
        bzip2 <${repo}/Sources >${repo}/Sources.bz2
        apt-ftparchive -c ${repo_conf} release ${repo} >${repo}/Release

        # Report package names found
        echo "${repo}:" $(grep ^Package: ${repo}/Packages | cut -f2- -d: | sort -u)
        popd >/dev/null
    done
}


upload() { # upload index files created by 'reindex'
    test -d work || fail "Nothing to upload in $(pwd)"

    log=$(pwd)/work/upload.log
    date >"$log"
    echo >>"$log"

    for repo_conf in $confdir/repo-*.conf; do
        repo=$(repolabel "$repo_conf")
        pushd work >/dev/null
        for file in $repo/*; do
            test -f $file || continue # skip the symlinks
            test -s $file || fail "'$file' is empty"
            echo "PUTting $repo_url$file"
            echo "$repo_url$file" >>"$log"
            curl -X PUT -u "$(repo_credentials)" -f --data-binary @$file $repo_url$file >>"$log"
            echo >>"$log"
            echo >>"$log"
        done
        popd >/dev/null
    done
}


clean() { # clean up temporary files owned by us
    for dir in tmp work; do
        test -f $dir/.deb-index && rm -rf "$dir" || :
    done
}


case "$action" in
    setup)      init; setup ;;
    create)     init; reindex ;;
    upload)     init; upload ;;
    refresh)    init; reindex; echo; upload ;;
    clean)      clean ;;
    *)
        echo >&2 "usage: $(basename $0) refresh|setup [<repo-url>]"
        exit 1
        ;;
esac
