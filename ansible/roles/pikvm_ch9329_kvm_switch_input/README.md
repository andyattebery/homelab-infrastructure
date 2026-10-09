# pikvm_ch9329_kvm_switch_input

Installs a script that switches a KVM switch's input from a PiKVM menu button. It types the switch's hotkey (ScrollLock,
ScrollLock, the input's digit) on the USB keyboard that a CH9329 chip presents to the switch. kvmd's GPIO `cmd` driver runs it.

## Status: Production

## Hardware

The script expects a CH340 + CH9329 cable:
- **The small end** is a CH340 USB-serial adapter. It goes into the PiKVM, where it shows up in `lsusb` as `1a86:7523 … CH340
  serial converter` and its port as `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`.
- **The end with both chips** goes into the KVM switch's keyboard port.

Plugged in backwards, the PiKVM has no `ttyUSB`, and its `lsusb` lists `1a86:e129 … WCH UART TO KB-MS` instead, which is the
keyboard side.

The script talks to the chip at 9600 baud in protocol mode, which are both factory defaults.

## Inputs

### `pikvm_ch9329_kvm_switch_input_script_path` (default `/usr/local/bin/pikvm_ch9329_kvm_switch_input`)

Where the script is installed.
- The host's `override.yaml` calls the script by this path, and a different role renders that file. So set the variable in the
  host's `host_vars`, where both roles read the same value.
- If the two paths differ, every button press makes kvmd log that the command could not be run.

The serial port and the input number are not role inputs. `override.yaml` passes them as arguments in each button's `cmd`.

## Playbook

`playbook-pikvm.yaml`:

```yaml
    - role: pikvm_ch9329_kvm_switch_input
      when: inventory_hostname == 'pikvm'
      tags: kvm_switch
```

`host_vars/pikvm/vars.yaml`:

```yaml
pikvm_ch9329_kvm_switch_input_script_path: /usr/local/bin/pikvm_ch9329_kvm_switch_input
pikvm_ch9329_device_path: /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
```

`files/pikvm/override.yaml.j2` has one GPIO driver per button. Input 1:

```yaml
            kvm_switch_input_1:
                type: cmd
                cmd: ['{{ pikvm_ch9329_kvm_switch_input_script_path }}', '{{ pikvm_ch9329_device_path }}', 1]
```

## The script

`pikvm_ch9329_kvm_switch_input <device> <input_number>`, where the input is 1–9.
- It opens the port exclusively and sends each key as a press and then a release, waiting `KEY_GAP` (0.25 s) between keys.
- On success it exits 0.
- On any error (missing port, permission, no reply from the chip, an error status from the chip) it exits 1 and prints an
  `error:` line.
- kvmd logs the script's output in `journalctl -u kvmd` as `CMD(kvm_switch_input_<N>) => …`.

Tests: `cd ansible && .venv/bin/pytest roles/pikvm_ch9329_kvm_switch_input/tests/ -q`.

## Traps

- **It imports kvmd internals.** The framing and reply checking come from
  `kvmd.plugins.hid.ch9329.chip.ChipConnection`, the module PiKVM's own CH9329 HID mode uses. It is not a public API. If a kvmd
  update moves it, every button press logs an `ImportError`, and the import at the top of the script needs updating.
- **kvmd waits forever.** kvmd's `cmd` driver gives the script no timeout. The script's 0.5 s read and write timeouts on the port
  are the only limit, so a chip that stops answering fails the press within about a second instead of hanging the button.
- **The by-id name is not unique.** The CH340 has no USB serial number, so its `/dev/serial/by-id/` name is unique only while it
  is the only CH340 on the host. If a second one is added, use the `/dev/serial/by-path/` name of the USB port instead.
- **Permissions.** `/dev/ttyUSB*` is `root:uucp 0660`, and kvmd's `kvmd` user is in `uucp` (kvmd's `sysusers.conf`).
- **Baud rate.** A CH9329 that has been reconfigured to another baud rate stays silent at 9600, and every press logs "Too short
  response, HID might be disconnected". Change `SPEED` in the script to match.
- **Timing.** The serial link alone puts about 22 ms between a key's press and release at 9600 baud. If the KVM switch ignores
  the sequence, change `KEY_GAP` in the script.
