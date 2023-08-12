#!/usr/bin/env sh

export op_item_name=$1
export server_name=$2
wireguard_config_dir="$(cd "$3" && pwd)"

add_peer() {
    peer_dir_path="$(cd "$1" && pwd)"
    peer_dir_name="$(basename $peer_dir_path)"
    peer_name="$(echo $peer_dir_name | sed 's/peer_//')"
    # echo $peer_dir_path
    # echo $peer_dir_name
    # echo $peer_name

    peer_presharedkey="$(cat $peer_dir_path/presharedkey-$peer_dir_name)"
    peer_privatekey="$(cat $peer_dir_path/privatekey-$peer_dir_name)"
    peer_publickey="$(cat $peer_dir_path/publickey-$peer_dir_name)"

    peer_conf_file_path="$peer_dir_path/$peer_dir_name.conf"
    peer_qrcode_file_path="$peer_dir_path/$peer_dir_name.png"

    op_peer_presharedkey_parameter="$peer_name.presharedkey[text]=$peer_presharedkey"
    op_peer_privatekey_parameter="$peer_name.privatekey[text]=$peer_privatekey"
    op_peer_publickey_parameter="$peer_name.publickey[text]=$peer_publickey"
    op_peer_conf_file_parameter="${peer_name}.${server_name}_${peer_name}\.conf[file]=$peer_conf_file_path"
    op_peer_qrcode_file_parameter="${peer_name}.${server_name}_${peer_name}\.png[file]=$peer_qrcode_file_path"

    op item edit "$op_item_name" \
        "$op_peer_presharedkey_parameter" \
        "$op_peer_privatekey_parameter" \
        "$op_peer_publickey_parameter" \
        "$op_peer_conf_file_parameter" \
        "$op_peer_qrcode_file_parameter" \
        1>/dev/null
}

export -f add_peer

find $wireguard_config_dir -type d -name 'peer_*' -exec /usr/bin/env sh -c 'add_peer "$1"' _ {} \;
