#!/usr/bin/env bash

config_json_path=$1

openseachest_powercontrol_command="/usr/bin/openSeaChest/openSeaChest_PowerControl --noBanner"

# From: https://github.com/jqlang/jq/wiki/FAQ#general-questions
# 𝑸: How can a stream of JSON texts produced by jq be converted into a bash array of corresponding values?
readarray -t hard_drive_configs <<< $(jq --compact-output '.[]' "$config_json_path")

for hard_drive_config in ${!hard_drive_configs[@]}; do
    # From: https://stackoverflow.com/a/26717401
    declare -A hard_drive_config="($(jq -r '. | to_entries | .[] | "[\"" + .key + "\"]=" + (.value | @sh)' <<< "${hard_drive_configs[0]}"))"

    # From: https://stackoverflow.com/a/15394738
    if [[ " ${hard_drive_configs[*]} " =~ "[[:space:]]epc_idle_a[[:space:]]" ]]; then
        # whatever you want to do when array contains value
    fi

    for key in ${!hard_drive_config[@]}; do
        echo "$key = ${hard_drive_config[$key]}"
    done
done
