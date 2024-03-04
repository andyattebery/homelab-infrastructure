#!/bin/bash

usage() {
  echo "usage: $0 <input_number>"
  exit 1
}

pikvm_send_key() {
  key=$1
  curl --no-progress-meter --header "X-KVMD-User:$PIKVM_USERNAME" --header "X-KVMD-Passwd:$PIKVM_PASSWORD" --request POST "https://$PIKVM_HOSTNAME/api/hid/events/send_key?key=$key"
}

script_dir=$(realpath $(dirname $0))

if [[ "$1" == "" ]]; then
  usage
else
  INPUT_NUMBER="$1"
fi

ENV_CONFIG_FILE="$script_dir/ENV_CONFIG"
if [ -e $ENV_CONFIG_FILE ]; then
  source $ENV_CONFIG_FILE
fi

# ENVs from ENV_CONFIG_FILE
# PIKVM_USERNAME
# PIKVM_PASSWORD
# PIKVM_HOSTNAME
# PIKVM_KVM_INPUT_SWITCH_HOTKEY

echo "Sending $PIKVM_KVM_INPUT_SWITCH_HOTKEY + $PIKVM_KVM_INPUT_SWITCH_HOTKEY + $INPUT_NUMBER to $PIKVM_HOSTNAME"

pikvm_send_key $PIKVM_KVM_INPUT_SWITCH_HOTKEY
pikvm_send_key $PIKVM_KVM_INPUT_SWITCH_HOTKEY
pikvm_send_key "Digit$INPUT_NUMBER"
