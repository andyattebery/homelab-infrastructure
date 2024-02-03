# nut

Installs and configures [NUT (Network UPS Tools)](https://networkupstools.org/) as either:
- Server (`nut_enable_server: true`) that is standalone or can have remote clients(`nut_enable_server_remote_access: true`) for monitoring the local UPS(es).
- Client (`nut_enable_client: true`) for monitoring a remote NUT server(s).

By default, nothing will happen unless `nut_enable_server` or `nut_enable_client` is set to `true`.

There is no reason to set both `nut_enable_server` and `nut_enable_client` to `true` because `nut_enable_server` enables monitoring of the local UPS(es).

## Use

### Server

1. Set the required variables:
    - `nut_enable_server` to `true`
    - `nut_enable_server_remote_access` to `true` if you want to configure remote clients)
    - `nut_monitor_primary_password` for the local upsmon
2. Run the role to install NUT.
3. Run `sudo nut-scanner` on the server.
4. Add an object to the `nut_upses` array variable with `name` and the values from the output of `nut-scanner`.
5. Run the role again to configure the UPS(es).

#### Example
```yaml
- role: nut
  vars:
    nut_enable_server: true
    nut_enable_server_remote_access: true
    nut_upses:
      - name: "{{ ups_monitor_rack_nut_ups_name }}"
        driver: usbhid-ups # required
        port: auto # required
        desc: APC Back-UPS RS1000G
        vendorid: "051D"
        productid: "0002"
    nut_monitor_primary_password: "{{ ups_monitor_rack_nut_upsmon_password }}"
    nut_monitor_secondary_users:
      - name: homeassistant
        password: "{{ ups_monitor_rack_nut_homeassistant_password }}"
    nut_notify_pushover_token: "{{ nut_pushover_token }}"
    nut_notify_pushover_user_key: "{{ pushover_user_key }}"
```

### Client

1. Set `nut_enable_client` and `nut_client_servers` variables.
2. Run role.

#### Example
```yaml
- role: nut
  vars:
    nut_enable_client: true
    nut_client_servers:
      - ups_name: ups_name_on_server
      server_address: server_address_that_can_be_ip_or_hostname_or_fqdn
      username: monitor_secondary_user_on_server
      password: monitor_secondary_user_password_on_server
```

## Variables

#### nut_enable_server

_Default: `false`_

`Bool` to configure as a server

#### nut_enable_client

_Default: `false`_

`Bool` to configure as a client for a remote server

### Server

#### nut_monitor_primary_password

_Required_

`String` for password for the local upsmon primary user

#### nut_enable_server_remote_access

_Default: `false`_

`Bool` to allow remote users

#### nut_enable_shutdown

_Default: `true`_

Set to `true` to [shutdown when UPS is on low power](https://networkupstools.org/docs/user-manual.chunked/Configuration_notes.html#UPS_shutdown).

#### nut_upses

_Optional, but pointless if not set_

Configuration for UPS(es). Only the `name`, `driver`, and `port` are required but additional fields such as `vendorid`, `productid`, and `serial` can be useful for disambiguating between multiple UPSes. These values can be obtained from running `sudo nut-scanner` once NUT is installed.

```yaml
nut_upses:
  - name: rack-ups
    driver: usbhid-ups # required
    port: auto # required
    desc: APC Back-UPS RS1000G
    vendorid: "051D"
    productid: "0002"
```

#### nut_admin_username

_Default: admin_

`String` of admin username

#### nut_admin_password

_Optional_

`String` of admin user password. Setting this will create an admin user with the username `nut_admin_username`.

#### nut_monitor_secondary_users

_Optional_

`Array` of secondary monitor users most likely used for remote clients.

```yaml
nut_monitor_secondary_users:
  - name: username
    password: password
```

#### nut_notify_pushover_token

_Optional_

`String` for [Pushover](https://pushover.net) application token. When `nut_notify_pushover_token` and `nut_notify_pushover_user_key` are both set, `upsmon_notify_pushover.sh` is set to the `upsmon.conf` `NOTIFYCMD` directive.

#### nut_notify_pushover_user_key

_Optional_

`String` for [Pushover](https://pushover.net) user key. When `nut_notify_pushover_token` and `nut_notify_pushover_user_key` are both set, `upsmon_notify_pushover.sh` is set to the `upsmon.conf` `NOTIFYCMD` directive.

#### nut_notify_pushover_script_directory

_Default: /usr/local/bin_

`String` for directory where `nut_notify_pushover_script_name` is copied.

#### nut_notify_pushover_script_name

_Default: upsmon_notify_pushover.sh_

`String` for upsmon_notify_pushover.sh name.

#### nut_notify_command

_Optional_

`String` of command that will be called for `nut_notify_command_types`. This sets the `upsmon.conf` `NOTIFYCMD` directive. `upsmon` sets the $UPSNAME and $NOTIFYTYPE environment variables and $1 as the notification message.

#### nut_notify_command_types

_Default: all possible values_

`Array` of notification types that send to `upsmon` `NOTIFYCMD`.

```yaml
nut_notify_command_types:
  # UPS is back online
  - "ONLINE"
  # UPS is on battery
  - "ONBATT"
  # UPS is on battery and has a low battery (is critical)
  - "LOWBATT"
  # UPS is being shutdown by the primary (FSD = "Forced Shutdown")
  - "FSD"
  # Communications established with the UPS
  - "COMMOK"
  # Communications lost to the UPS
  - "COMMBAD"
  # The system is being shutdown
  - "SHUTDOWN"
  # The UPS battery is bad and needs to be replaced
  - "REPLBATT"
  # A UPS is unavailable (can’t be contacted for monitoring)
  - "NOCOMM"
  # upsmon parent process died - shutdown impossible
  - "NOPARENT"
  # UPS calibration in progress
  - "CAL"
  # UPS calibration finished
  - "NOTCAL"
  # UPS administratively OFF or asleep
  - "OFF"
  # UPS no longer administratively OFF or asleep
  - "NOTOFF"
  # UPS on bypass (powered, not protecting)
  - "BYPASS"
  # UPS no longer on bypass
  - "NOTBYPASS"
```

#### nut_services_group

_Default: nut_

`String` for group the nut service run as.

#### nut_shutdown_command

_Default: `/sbin/shutdown -h +0`_

`String` for command that is called when the UPS is on low power

#### nut_nut_directives

_Optional_

`Array` of [directives for `nut.conf`](https://networkupstools.org/docs/man/nut.conf.html)

#### nut_ups_global_directives

_Default: below_

`Array` of [directives for `ups.conf`](https://networkupstools.org/docs/man/ups.conf.html)

```yaml
nut_ups_global_directives:
  # Set maxretry to 3 by default, this should mitigate race with slow devices
  maxretry: 3
```

#### nut_upsd_directives

_Optional_

`Array` of [directives for `upsd.conf`](https://networkupstools.org/docs/man/upsd.conf.html)

#### nut_upsmon_directives

_Optional_

`Array` of [directives for `upsmon.conf`](https://networkupstools.org/docs/man/upsmon.conf.html)

### Client

#### nut_client_servers

_Optional, but pointless if not set_

`Array` of remote servers to monitor

```yaml
nut_client_servers:
  - ups_name: ups_name_on_server
    server_address: server_address_that_can_be_ip_or_hostname_or_fqdn
    username: monitor_secondary_user_on_server
    password: monitor_secondary_user_password_on_server
```

## Notes

Many tutorials show configuring [`upssched`](https://networkupstools.org/docs/man/upssched.html) for notifications. However, this just allows notifications to be processed a specific time after they are emitted which appears to be for doing early shutdowns or cases where many notifications are being emitted by `upsmon`. Therefore in most situations it's most likely unnecessary and just creates another layer of configuration. So this role configures `upsmon` directly for sending notifications to a command (`NOTIFYCMD`).
