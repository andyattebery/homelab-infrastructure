#!/usr/bin/env sh

ROLES_DIRECTORY=$(dirname $0)/../roles

for d in $(ls $ROLES_DIRECTORY); do
    readme_path="$ROLES_DIRECTORY/$d/README.md"
    if [ ! -e $readme_path ]; then
        cat << EOF > $readme_path
# $d

## Status: WIP

EOF
    fi
done
