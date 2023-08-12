#!/usr/bin/env sh

script_directory_path="$(cd "$( dirname "$0" )" && pwd)"
role_directory_path="$(cd $1 && pwd)"
role_name="$(basename $role_directory_path)"
# role_name=$(echo $role_directory_path | sed -E 's/.*\/([_[:alpha:][:digit:]]*)\/?$/\1/')
# echo $role_name
# variables=$(grep --only-matching --no-filename --extended-regexp '{{[[:space:]]*([_[:alpha:][:digit:]]*)[[:space:]]*}}' --recursive $role_directory_path | sed -E 's/[{}[:space:]]//g' | sort | uniq)

# echo $variables

ansible-playbook \
    --extra-vars \
        "role_directory_path=$role_directory_path script_directory_path=$script_directory_path role_name=$role_name" \
    $script_directory_path/playbook.yaml
