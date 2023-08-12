#!/usr/bin/env sh

get_input_vault_all() {
  echo "$(op inject --in-file $1)\nvault_nas_01_syncoid_ssh_private_key: |\n$(op read "op://Personal/nas-01 - syncoid - SSH Key/private key" | sed 's/^/  /')"
}

populate_vault_from_onepassword() {
  input_vault_template_file_path=$1
  output_vault_file_path=${input_vault_template_file_path%.*}
  # echo $input_vault_template_file_path
  echo "Writing $output_vault_file_path..."

  # if [ "${input_vault_template_file_path#*"all/vault.yaml.tpl"}" != "$input_vault_template_file_path" ]; then
  #   get_input_vault_all $input_vault_template_file_path | ansible-vault encrypt --out $output_vault_file_path
  # else
    op inject --in-file $input_vault_template_file_path | ansible-vault encrypt --out $output_vault_file_path
  # fi
}

script_dir="$(dirname $0)/.."

export -f get_input_vault_all
export -f populate_vault_from_onepassword
find "$script_dir" -name '*vault.yaml.tpl' -exec /usr/bin/env sh -c 'populate_vault_from_onepassword "$1"' _ {} \;
